/**
 * flows.js - Institutional Money-Flow Rankings Page Logic
 */

document.addEventListener('DOMContentLoaded', () => {
  initFlowsPage();
  initLookup();
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

// --- Stock Lookup Feature Logic ---
let indexDataCache = null;
let isFetchingIndex = false;
let lookupChartInstances = [];

function initLookup() {
  const form = document.getElementById('lookupForm');
  if (form) {
    form.addEventListener('submit', (e) => {
      e.preventDefault();
      const input = document.getElementById('lookupInput');
      const code = input ? input.value : '';
      performLookup(code);
    });
  }

  // Pre-fill input and perform lookup if ?code= is present in URL
  const urlParams = new URLSearchParams(window.location.search);
  const initialCode = urlParams.get('code');
  if (initialCode && initialCode.trim()) {
    const input = document.getElementById('lookupInput');
    if (input) {
      input.value = initialCode.trim();
    }
    performLookup(initialCode.trim());
  }
}

async function getOrFetchIndex() {
  if (indexDataCache) return indexDataCache;
  if (isFetchingIndex) {
    while (isFetchingIndex) {
      await new Promise((resolve) => setTimeout(resolve, 50));
    }
    return indexDataCache;
  }

  isFetchingIndex = true;
  try {
    const resp = await fetch('./data/flows/index.json');
    if (!resp.ok) {
      throw new Error(`HTTP ${resp.status}`);
    }
    indexDataCache = await resp.json();
    populateStockDatalist(indexDataCache);
    return indexDataCache;
  } finally {
    isFetchingIndex = false;
  }
}

function populateStockDatalist(indexData) {
  const datalist = document.getElementById('stockDatalist');
  if (!datalist || !indexData || !indexData.symbols) return;

  datalist.innerHTML = '';
  const fragment = document.createDocumentFragment();
  Object.keys(indexData.symbols).forEach((code) => {
    const item = indexData.symbols[code];
    const opt = document.createElement('option');
    opt.value = code;
    opt.label = `${code} ${item.name || ''} (${item.exchange || ''})`;
    fragment.appendChild(opt);
  });
  datalist.appendChild(fragment);
}

function showLookupError(title, message) {
  const errContainer = document.getElementById('lookupError');
  const resultContainer = document.getElementById('lookupResult');
  if (resultContainer) resultContainer.style.display = 'none';

  if (errContainer) {
    errContainer.style.display = 'block';
    errContainer.innerHTML = `
      <div class="lookup-error-title">${title}</div>
      <div>${message}</div>
    `;
  }
}

function clearLookupError() {
  const errContainer = document.getElementById('lookupError');
  if (errContainer) {
    errContainer.style.display = 'none';
    errContainer.innerHTML = '';
  }
}

function formatSignedShares(val) {
  if (val === null || val === undefined || typeof val !== 'number' || Number.isNaN(val)) {
    return '—';
  }
  const prefix = val > 0 ? '+' : '';
  return prefix + val.toLocaleString('zh-TW') + ' 股';
}

function getShareColorCls(val) {
  if (val === null || val === undefined || typeof val !== 'number' || Number.isNaN(val)) {
    return 'flat';
  }
  return val > 0 ? 'up' : val < 0 ? 'down' : 'flat';
}

function getFieldIndexes(fields) {
  const map = {
    date: 0,
    foreign_net: 1,
    trust_net: 2,
    dealer_net: 3,
    total_net: 4
  };
  if (Array.isArray(fields)) {
    fields.forEach((f, idx) => {
      map[f] = idx;
    });
  }
  return map;
}

async function performLookup(rawCode) {
  const code = (rawCode || '').trim().toUpperCase();

  if (!code) {
    showLookupError('請輸入代號', '請在上方輸入框填寫台股股票或 ETF 代號（例如：2330 或 8299）。');
    return;
  }

  clearLookupError();

  const resultContainer = document.getElementById('lookupResult');
  if (resultContainer) {
    resultContainer.style.display = 'block';
    resultContainer.innerHTML = '<div style="color:var(--muted); padding:1rem; text-align:center;">查詢標的籌碼數據中…</div>';
  }

  // Update URL state without page reload
  try {
    const newUrl = `${window.location.pathname}?code=${encodeURIComponent(code)}`;
    window.history.replaceState(null, '', newUrl);
  } catch (e) {
    // Ignore history state errors
  }

  // Destroy previous chart instances
  lookupChartInstances.forEach((c) => {
    try {
      c.destroy();
    } catch (e) {}
  });
  lookupChartInstances = [];

  let indexData;
  try {
    indexData = await getOrFetchIndex();
  } catch (err) {
    showLookupError('索引檔讀取失敗', `無法載入全市場標的索引資訊 (${err.message})。`);
    return;
  }

  const symbolEntry = indexData.symbols && indexData.symbols[code];
  if (!symbolEntry) {
    showLookupError('「查無此代號」', '資料庫中無此代號。目前僅收錄具備三大法人交易活動之 TWSE / TPEX 上市櫃股票與 ETF。');
    return;
  }

  // Handle alternates if present (show both instead of silently picking one)
  const targets = [symbolEntry];
  if (Array.isArray(symbolEntry.alternates)) {
    targets.push(...symbolEntry.alternates);
  }

  const loadedInstruments = [];

  for (const target of targets) {
    try {
      const resp = await fetch(`./data/flows/${target.file}`, { cache: 'no-store' });
      if (!resp.ok) {
        throw new Error(`HTTP ${resp.status}`);
      }
      const data = await resp.json();
      loadedInstruments.push(data);
    } catch (err) {
      showLookupError('數據檔讀取失敗', `無法載入標的 ${target.name || code} (${target.exchange || ''}) 之籌碼數據 (${err.message})。`);
      return;
    }
  }

  if (loadedInstruments.length === 0) {
    showLookupError('「查無此代號」', '無法讀取該標的籌碼數據。');
    return;
  }

  // Render all loaded instruments
  let html = '';
  loadedInstruments.forEach((data, index) => {
    const fMap = getFieldIndexes(data.fields);
    const series = data.series || [];

    if (series.length === 0) {
      html += `
        <div class="symbol-detail-block">
          <div class="symbol-heading-row">
            <div class="symbol-title-group">
              <h3>${data.name || data.symbol || code} (${data.symbol || code})</h3>
              <span class="exchange-badge">${data.exchange || '—'}</span>
            </div>
            <a href="./stock.html?code=${data.symbol || code}" class="stock-detail-link">個股財務明細 (${data.symbol || code}) →</a>
          </div>
          <div class="lookup-error-panel error">此標的暫無三大法人買賣超歷史數據記錄。</div>
        </div>
      `;
      return;
    }

    const latestRow = series[0];
    const latestDate = latestRow[fMap.date] || '—';
    const latestForeign = latestRow[fMap.foreign_net];
    const latestTrust = latestRow[fMap.trust_net];
    const latestDealer = latestRow[fMap.dealer_net];
    const latestTotal = latestRow[fMap.total_net];

    const chartCanvasId = `lookupChartCanvas_${index}`;

    // Render Table rows (newest first)
    const tableRows = series
      .map((row) => {
        const d = row[fMap.date] || '—';
        const f = row[fMap.foreign_net];
        const t = row[fMap.trust_net];
        const dl = row[fMap.dealer_net];
        const tot = row[fMap.total_net];

        return `
        <tr>
          <td style="font-weight:700; text-align:center;">${d}</td>
          <td class="${getShareColorCls(f)}">${formatSignedShares(f)}</td>
          <td class="${getShareColorCls(t)}">${formatSignedShares(t)}</td>
          <td class="${getShareColorCls(dl)}">${formatSignedShares(dl)}</td>
          <td class="${getShareColorCls(tot)}" style="font-weight:700;">${formatSignedShares(tot)}</td>
        </tr>
      `;
      })
      .join('');

    html += `
      <div class="symbol-detail-block">
        <div class="symbol-heading-row">
          <div class="symbol-title-group">
            <h3>${data.name || data.symbol || code} (${data.symbol || code})</h3>
            <span class="exchange-badge">${data.exchange || '—'}</span>
          </div>
          <a href="./stock.html?code=${data.symbol || code}" class="stock-detail-link">個股財務明細 (${data.symbol || code}) →</a>
        </div>

        <div class="kpi-grid">
          <div class="kpi-card">
            <span class="kpi-label">外資買賣超</span>
            <span class="kpi-value ${getShareColorCls(latestForeign)}">${formatSignedShares(latestForeign)}</span>
            <span class="kpi-meta">最新交易日：${latestDate}</span>
          </div>
          <div class="kpi-card">
            <span class="kpi-label">投信買賣超</span>
            <span class="kpi-value ${getShareColorCls(latestTrust)}">${formatSignedShares(latestTrust)}</span>
            <span class="kpi-meta">最新交易日：${latestDate}</span>
          </div>
          <div class="kpi-card">
            <span class="kpi-label">自營商買賣超</span>
            <span class="kpi-value ${getShareColorCls(latestDealer)}">${formatSignedShares(latestDealer)}</span>
            <span class="kpi-meta">最新交易日：${latestDate}</span>
          </div>
          <div class="kpi-card">
            <span class="kpi-label">三大法人合計</span>
            <span class="kpi-value ${getShareColorCls(latestTotal)}">${formatSignedShares(latestTotal)}</span>
            <span class="kpi-meta">最新交易日：${latestDate}</span>
          </div>
        </div>

        <div class="chart-wrapper">
          <div class="chart-title">三大法人每日買賣超趨勢圖（時間依舊至新）</div>
          <div class="lookup-chart-container">
            <canvas id="${chartCanvasId}"></canvas>
          </div>
        </div>

        <div class="lookup-table-wrapper">
          <div class="table-scroll">
            <table class="data-table">
              <caption>每日三大法人買賣超數據明細（最新日在上，單位：股）</caption>
              <thead>
                <tr>
                  <th scope="col" style="text-align:center;">日期</th>
                  <th scope="col">外資買賣超 (股)</th>
                  <th scope="col">投信買賣超 (股)</th>
                  <th scope="col">自營商買賣超 (股)</th>
                  <th scope="col">三大法人合計 (股)</th>
                </tr>
              </thead>
              <tbody>
                ${tableRows}
              </tbody>
            </table>
          </div>
        </div>
      </div>
    `;
  });

  resultContainer.innerHTML = html;

  // Render Charts for each loaded instrument with series data
  loadedInstruments.forEach((data, index) => {
    if (data.series && data.series.length > 0) {
      renderLookupChart(`lookupChartCanvas_${index}`, data.series, data.fields);
    }
  });
}

function renderLookupChart(canvasId, seriesData, fields) {
  if (typeof window.Chart !== 'function') {
    console.warn('Chart.js 尚未載入，已略過圖表繪製，表格資訊不受影響。');
    return;
  }

  const canvas = document.getElementById(canvasId);
  if (!canvas) return;

  try {
    const fMap = getFieldIndexes(fields);
    // Reverse series for chart (series is newest first -> chart needs oldest first)
    const chronological = [...seriesData].reverse();
    const labels = chronological.map((r) => r[fMap.date]);
    const foreignData = chronological.map((r) => r[fMap.foreign_net]);
    const trustData = chronological.map((r) => r[fMap.trust_net]);
    const dealerData = chronological.map((r) => r[fMap.dealer_net]);

    const chartInstance = new window.Chart(canvas, {
      type: 'bar',
      data: {
        labels: labels,
        datasets: [
          {
            label: '外資買賣超',
            data: foreignData,
            backgroundColor: 'rgba(18, 104, 74, 0.85)',
            borderColor: '#12684a',
            borderWidth: 1
          },
          {
            label: '投信買賣超',
            data: trustData,
            backgroundColor: 'rgba(43, 108, 176, 0.85)',
            borderColor: '#2b6cb0',
            borderWidth: 1
          },
          {
            label: '自營商買賣超',
            data: dealerData,
            backgroundColor: 'rgba(138, 90, 22, 0.85)',
            borderColor: '#8a5a16',
            borderWidth: 1
          }
        ]
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        spanGaps: false,
        plugins: {
          legend: {
            position: 'top',
            labels: {
              font: { family: 'Inter, system-ui, sans-serif', weight: '600', size: 12 },
              color: '#17221c'
            }
          },
          tooltip: {
            callbacks: {
              label: function (context) {
                const val = context.raw;
                const sign = val > 0 ? '+' : '';
                return `${context.dataset.label}: ${sign}${val !== undefined && val !== null ? val.toLocaleString('zh-TW') : '0'} 股`;
              }
            }
          }
        },
        scales: {
          x: {
            grid: { display: false },
            ticks: { color: '#5f6f65', font: { size: 11 } }
          },
          y: {
            grid: { color: 'rgba(214, 217, 206, 0.6)' },
            ticks: {
              color: '#5f6f65',
              font: { size: 11 },
              callback: function (val) {
                return val.toLocaleString('zh-TW');
              }
            }
          }
        }
      }
    });

    lookupChartInstances.push(chartInstance);
  } catch (err) {
    console.error('Chart.js 繪製失敗:', err);
  }
}

