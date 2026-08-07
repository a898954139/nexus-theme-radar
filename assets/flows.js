/**
 * flows.js - Institutional Money-Flow Rankings Page Logic
 */

document.addEventListener('DOMContentLoaded', () => {
  initFlowsPage();
});

let globalRankingsData = null;
let currentMetric = 'netbuy'; // 'netbuy' | 'change'
let currentWindow = '5';      // '5' | '10' | '20' | '30'
let currentSide = 'up';        // 'up' | 'down'
let hideEtf = true;           // default ON (hidden)

async function initFlowsPage() {
  const flowsStatus = document.getElementById('flowsStatus');
  const flowsError = document.getElementById('flowsError');

  setupControls();

  try {
    flowsStatus.style.display = 'block';
    flowsStatus.textContent = '載入三大法人籌碼排行數據中…';

    const resp = await fetch('./data/institutional-rankings.json', { cache: 'no-store' });
    if (!resp.ok) {
      throw new Error(`無法讀取法人籌碼排行資料檔 (HTTP ${resp.status})`);
    }

    globalRankingsData = await resp.json();
    flowsStatus.style.display = 'none';

    renderCurrentBoard();
  } catch (err) {
    flowsStatus.style.display = 'none';
    showFlowsError('資料載入失敗', err.message || '無法處理法人籌碼排行數據');
  }
}

function showFlowsError(title, message) {
  const flowsError = document.getElementById('flowsError');
  flowsError.style.display = 'block';
  flowsError.innerHTML = `
    <div class="error-title">${title}</div>
    <div>${message}</div>
    <div style="margin-top:1rem;">
      <a class="back-link" href="./theme-momentum.html">← 返回題材雷達頁面</a>
    </div>
  `;
}

function setupControls() {
  const metricBtns = document.querySelectorAll('#metricControls .toggle-btn');
  metricBtns.forEach((btn) => {
    btn.addEventListener('click', () => {
      metricBtns.forEach((b) => {
        b.classList.remove('active');
        b.setAttribute('aria-checked', 'false');
      });
      btn.classList.add('active');
      btn.setAttribute('aria-checked', 'true');
      currentMetric = btn.dataset.metric;
      renderCurrentBoard();
    });
  });

  const windowBtns = document.querySelectorAll('#windowControls .toggle-btn');
  windowBtns.forEach((btn) => {
    btn.addEventListener('click', () => {
      windowBtns.forEach((b) => {
        b.classList.remove('active');
        b.setAttribute('aria-checked', 'false');
      });
      btn.classList.add('active');
      btn.setAttribute('aria-checked', 'true');
      currentWindow = btn.dataset.window;
      renderCurrentBoard();
    });
  });

  const sideBtns = document.querySelectorAll('#sideControls .toggle-btn');
  sideBtns.forEach((btn) => {
    btn.addEventListener('click', () => {
      sideBtns.forEach((b) => {
        b.classList.remove('active');
        b.setAttribute('aria-checked', 'false');
      });
      btn.classList.add('active');
      btn.setAttribute('aria-checked', 'true');
      currentSide = btn.dataset.side;
      renderCurrentBoard();
    });
  });

  const etfToggle = document.getElementById('etfToggle');
  if (etfToggle) {
    etfToggle.addEventListener('change', (e) => {
      hideEtf = e.target.checked;
      renderCurrentBoard();
    });
  }
}

function renderCurrentBoard() {
  if (!globalRankingsData || !globalRankingsData.rankings) return;

  const boardKey = `top_three_inst_${currentMetric}_${currentWindow}_${currentSide}`;
  const board = globalRankingsData.rankings[boardKey];

  const boardTitle = document.getElementById('boardTitle');
  const boardKicker = document.getElementById('boardKicker');
  const boardMeta = document.getElementById('boardMeta');
  const etfNotice = document.getElementById('etfNotice');
  const tableRankings = document.getElementById('tableRankings');

  if (!board) {
    boardTitle.textContent = '無此排行板塊';
    boardKicker.textContent = `BOARD: ${boardKey}`;
    boardMeta.innerHTML = '';
    tableRankings.querySelector('thead').innerHTML = '';
    tableRankings.querySelector('tbody').innerHTML = '<tr><td colspan="8" style="text-align:center;">暫無相關排行榜資料。</td></tr>';
    return;
  }

  // Header titles
  const metricLabel = currentMetric === 'netbuy' ? '三大法人買賣超' : '三大法人持股比重變化';
  const sideLabel = currentSide === 'up'
    ? (currentMetric === 'netbuy' ? '買超排行' : '增加排行')
    : (currentMetric === 'netbuy' ? '賣超排行' : '減少排行');

  boardTitle.textContent = `近 ${currentWindow} 日${metricLabel}${sideLabel}`;
  boardKicker.textContent = `BOARD: ${boardKey}`;

  let dateRangeStr = '—';
  if (board.date_range && board.date_range.start && board.date_range.end) {
    dateRangeStr = `${board.date_range.start} ～ ${board.date_range.end}`;
  }

  const unitStr = board.unit || (currentMetric === 'netbuy' ? '張' : '%');

  boardMeta.innerHTML = `
    <span class="meta-item">統計區間：<strong>${dateRangeStr}</strong></span>
    <span class="meta-item">資料單位：<strong>${unitStr}</strong></span>
  `;

  const rawEntries = board.entries || [];
  const totalEtfs = rawEntries.filter((e) => e.is_etf === true).length;

  let displayEntries = rawEntries;
  if (hideEtf) {
    displayEntries = rawEntries.filter((e) => e.is_etf !== true);
    etfNotice.textContent = `「已隱藏 ${totalEtfs} 檔 ETF」`;
  } else {
    etfNotice.textContent = `（包含 ${totalEtfs} 檔 ETF，共 ${rawEntries.length} 檔標的）`;
  }

  // Render Table Head & Body based on metric
  if (currentMetric === 'netbuy') {
    renderNetbuyTable(tableRankings, displayEntries, unitStr);
  } else {
    renderChangeTable(tableRankings, displayEntries);
  }
}

function formatSignedVal(val, decimals = 0, suffix = '') {
  if (val === null || val === undefined || Number.isNaN(val)) return '—';
  const prefix = val > 0 ? '+' : '';
  const formatted = decimals > 0
    ? val.toFixed(decimals)
    : val.toLocaleString('zh-TW');
  return prefix + formatted + suffix;
}

function getValColorCls(val) {
  if (val === null || val === undefined || Number.isNaN(val)) return '';
  return val > 0 ? 'up' : val < 0 ? 'down' : 'flat';
}

function renderNetbuyTable(table, entries, unitStr) {
  const thead = table.querySelector('thead');
  const tbody = table.querySelector('tbody');

  thead.innerHTML = `
    <tr>
      <th scope="col" style="text-align:center;">排名</th>
      <th scope="col">標的名稱 (代碼)</th>
      <th scope="col" style="text-align:center;">市場</th>
      <th scope="col">外資 (${unitStr})</th>
      <th scope="col">投信 (${unitStr})</th>
      <th scope="col">自營商 (${unitStr})</th>
      <th scope="col">三大法人合計 (${unitStr})</th>
      <th scope="col" style="text-align:center;">標記</th>
    </tr>
  `;

  if (entries.length === 0) {
    tbody.innerHTML = '<tr><td colspan="8" style="text-align:center;">此篩選條件下無符合標的。</td></tr>';
    return;
  }

  tbody.innerHTML = entries
    .map((e) => {
      const isUniverse = e.in_universe === true;
      const isOut = e.ratio_out_of_range === true;
      const rowCls = isUniverse ? 'in-universe-row' : '';

      const nameCell = `<a class="stock-link" href="./stock.html?code=${e.code}">${e.name || e.code} (${e.code})</a>`;
      const rankVal = e.rank !== undefined && e.rank !== null ? e.rank : '—';

      let badges = [];
      if (isOut) {
        badges.push(`<span class="warning-tag" title="數據持股比率超出一般範圍 (>100%)">⚠️ 比率異常</span>`);
      }
      if (isUniverse) {
        badges.push(`<span class="universe-tag">★ 追蹤中</span>`);
      }
      if (e.is_etf) {
        badges.push(`<span class="etf-tag">ETF</span>`);
      }

      const badgeStr = badges.length > 0 ? badges.join(' ') : '—';

      return `
      <tr class="${rowCls}">
        <td style="text-align:center; font-weight:700;">${rankVal}</td>
        <td>${nameCell}</td>
        <td style="text-align:center;">${e.exchange || '—'}</td>
        <td class="${getValColorCls(e.foreign)}">${formatSignedVal(e.foreign, 0)}</td>
        <td class="${getValColorCls(e.trust)}">${formatSignedVal(e.trust, 0)}</td>
        <td class="${getValColorCls(e.dealer)}">${formatSignedVal(e.dealer, 0)}</td>
        <td class="${getValColorCls(e.total)}" style="font-weight:700;">${formatSignedVal(e.total, 0)}</td>
        <td style="text-align:center;">${badgeStr}</td>
      </tr>
    `;
    })
    .join('');
}

function renderChangeTable(table, entries) {
  const thead = table.querySelector('thead');
  const tbody = table.querySelector('tbody');

  thead.innerHTML = `
    <tr>
      <th scope="col" style="text-align:center;">序號</th>
      <th scope="col">標的名稱 (代碼)</th>
      <th scope="col" style="text-align:center;">市場</th>
      <th scope="col">三大法人持股比率 (%)</th>
      <th scope="col">持股比重變化 (pp)</th>
      <th scope="col" style="text-align:center;">標記</th>
    </tr>
  `;

  if (entries.length === 0) {
    tbody.innerHTML = '<tr><td colspan="6" style="text-align:center;">此篩選條件下無符合標的。</td></tr>';
    return;
  }

  tbody.innerHTML = entries
    .map((e, idx) => {
      const isUniverse = e.in_universe === true;
      const isOut = e.ratio_out_of_range === true;
      const rowCls = isUniverse ? 'in-universe-row' : '';

      const nameCell = `<a class="stock-link" href="./stock.html?code=${e.code}">${e.name || e.code} (${e.code})</a>`;

      const ratioValStr = e.three_inst_ratio !== undefined && e.three_inst_ratio !== null
        ? e.three_inst_ratio.toFixed(2) + '%'
        : '—';

      let badges = [];
      if (isOut) {
        badges.push(`<span class="warning-tag" title="持股比率超出一般範圍 (>100%: ${ratioValStr})">⚠️ 比率異常</span>`);
      }
      if (isUniverse) {
        badges.push(`<span class="universe-tag">★ 追蹤中</span>`);
      }
      if (e.is_etf) {
        badges.push(`<span class="etf-tag">ETF</span>`);
      }

      const badgeStr = badges.length > 0 ? badges.join(' ') : '—';
      const ratioDisplay = isOut
        ? `<span class="warning-text" title="數據持股比率過高 (${ratioValStr})">${ratioValStr} ⚠️</span>`
        : ratioValStr;

      return `
      <tr class="${rowCls}">
        <td style="text-align:center; font-weight:700;">${idx + 1}</td>
        <td>${nameCell}</td>
        <td style="text-align:center;">${e.exchange || '—'}</td>
        <td>${ratioDisplay}</td>
        <td class="${getValColorCls(e.change)}" style="font-weight:700;">${formatSignedVal(e.change, 2, ' pp')}</td>
        <td style="text-align:center;">${badgeStr}</td>
      </tr>
    `;
    })
    .join('');
}
