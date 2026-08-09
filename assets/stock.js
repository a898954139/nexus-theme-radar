/**
 * stock.js - Individual Stock Financial Detail Page Logic
 */

document.addEventListener('DOMContentLoaded', () => {
  initStockPage();
});

async function initStockPage() {
  const stockError = document.getElementById('stockError');
  const dataNotice = document.getElementById('dataNotice');
  const stockHeaderSection = document.getElementById('stockHeaderSection');
  const tabsSection = document.getElementById('tabsSection');

  // 1. Read 'code' from query parameters
  const params = new URLSearchParams(window.location.search);
  const code = params.get('code')?.trim();

  if (!code) {
    showError(
      '未指定股票代碼',
      '網址中未提供股票代碼（例如 stock.html?code=2330）。請從題材雷達頁面選擇標的查看。',
      null
    );
    return;
  }

  try {
    // 2. Fetch the lightweight fundamentals index and optional supporting data.
    // Commentary is optional: it is generated separately and quarterly, so the
    // page must render the numbers whether or not any prose exists yet.
    const [indexResp, aliasesResp, commentaryResp, flowsResp] = await Promise.all([
      fetch('./data/fundamentals-index.json', { cache: 'no-store' }),
      fetch('./config/symbol_aliases.tw.json').catch(() => null),
      fetch('./data/fundamental-commentary.json', { cache: 'no-store' }).catch(() => null),
      fetch('./data/institutional-flows.json', { cache: 'no-store' }).catch(() => null)
    ]);

    if (!indexResp.ok) {
      throw new Error(`無法讀取個股財務索引 (HTTP ${indexResp.status})`);
    }

    const fundamentalsIndex = await indexResp.json();
    const aliasesData = aliasesResp && aliasesResp.ok ? await aliasesResp.json() : null;
    const commentaryData =
      commentaryResp && commentaryResp.ok
        ? await commentaryResp.json().catch(() => null)
        : null;
    const flowsData =
      flowsResp && flowsResp.ok
        ? await flowsResp.json().catch(() => null)
        : null;

    const symbolsMap = fundamentalsIndex.symbols || {};

    // 3. Match entry key ending with ":<code>" or matching "<code>"
    const matchedKey = Object.keys(symbolsMap).find(
      (k) => k === code || k.endsWith(':' + code)
    );

    if (!matchedKey) {
      const availableCodes = Object.keys(symbolsMap).map((k) => {
        const parts = k.split(':');
        const ticker = parts[1] || parts[0];
        const name = aliasesData?.symbols?.[ticker]?.name_zh || ticker;
        return { ticker, name };
      });

      showError(
        `查無此標的：${code}`,
        '系統中暫無此個股的季報財務數據。',
        availableCodes
      );
      return;
    }

    const detailFile = symbolsMap[matchedKey]?.file;
    if (!detailFile) {
      throw new Error('個股財務索引缺少明細檔路徑');
    }
    const detailResp = await fetch(
      `./data/fundamentals/${encodeURIComponent(detailFile)}`,
      { cache: 'no-store' }
    );
    if (!detailResp.ok) {
      throw new Error(`無法讀取個股財務明細 (HTTP ${detailResp.status})`);
    }
    const symbolData = await detailResp.json();
    const aliasInfo = aliasesData?.symbols?.[code] || {};
    const exchange = aliasInfo.exchange || matchedKey.split(':')[0] || 'TWSE';
    const nameZh = aliasInfo.name_zh || code;

    // Surface missing data notice if non-empty
    if (symbolData.missing && symbolData.missing.length > 0) {
      dataNotice.style.display = 'block';
      dataNotice.innerHTML = `<strong>⚠️ 數據品質提示：</strong> 本期部分財報欄位未提供或缺漏：${symbolData.missing.join(
        '；'
      )}`;
    }

    // Render Page Title and Header
    document.title = `${nameZh} (${code}) 財務明細｜Taiwan Equity Theme Radar`;
    renderHeader(nameZh, code, exchange, symbolData);

    // Show main section and tabs
    stockHeaderSection.style.display = 'block';
    tabsSection.style.display = 'block';

    // Render Tab 1 Contents
    renderKpiCards(symbolData);
    renderCommentary(commentaryData, matchedKey, symbolData.fiscal_quarter);
    renderCharts(symbolData);
    renderTables(symbolData);

    // Render Tab 2 Contents (Institutional Money-Flows)
    renderInstitutionalFlows(code, flowsData, flowsResp && !flowsResp.ok);

    // Init Accessible Tabs
    setupTabs();
  } catch (err) {
    showError('資料載入失敗', err.message || '無法處理財務數據', null);
  }
}

/**
 * Render the generated commentary, if any exists for this exact quarter.
 *
 * Commentary is generated separately and quarterly, so it can lag the figures
 * by a full quarter. Prose describing 2025Q4 rendered beside 2026Q1 numbers
 * reads as a statement about the numbers on screen, which is worse than
 * showing no prose at all -- so a quarter mismatch renders nothing.
 */
function renderCommentary(commentaryData, matchedKey, fiscalQuarter) {
  const container = document.getElementById('commentary');
  if (!container) return;
  container.replaceChildren();

  const entry = commentaryData?.symbols?.[matchedKey];
  if (!entry || entry.fiscal_quarter !== fiscalQuarter) return;

  const highlights = Array.isArray(entry.highlights) ? entry.highlights : [];
  const usable = highlights.filter((item) => typeof item === 'string' && item.trim());
  if (!usable.length) return;

  const box = document.createElement('section');
  box.className = 'commentary-box';

  const title = document.createElement('h2');
  title.className = 'commentary-title';
  title.textContent = `🔍 ${fiscalQuarter} 財務重點`;
  box.append(title);

  const list = document.createElement('ul');
  list.className = 'commentary-list';
  for (const item of usable) {
    const li = document.createElement('li');
    // textContent, not innerHTML: this string came from a language model.
    li.textContent = item;
    list.append(li);
  }
  box.append(list);

  const note = document.createElement('p');
  note.className = 'commentary-note';
  note.textContent = '本段由模型依上述財報數字生成，僅描述已發生的財務事實，不構成投資建議。';
  box.append(note);

  container.append(box);
}

/* -------------------------------------------------------------------------- */
/* Helper Functions & Formatting                                              */
/* -------------------------------------------------------------------------- */

function formatNum(val, decimals = 2) {
  if (val === null || val === undefined || Number.isNaN(val)) return '—';
  return val.toLocaleString('zh-TW', {
    minimumFractionDigits: decimals,
    maximumFractionDigits: decimals
  });
}

function formatPct(fraction, decimals = 1) {
  if (fraction === null || fraction === undefined || Number.isNaN(fraction)) return '—';
  return (fraction * 100).toFixed(decimals) + '%';
}

function calcQoQ(curr, prev, isPctPoint = false, prevFormatted = '') {
  if (curr === null || curr === undefined || prev === null || prev === undefined) {
    return { dir: 'flat', text: '—' };
  }

  if (isPctPoint) {
    const diffPP = (curr - prev) * 100;
    const sign = diffPP > 0 ? '+' : '';
    const dir = diffPP > 0 ? 'up' : diffPP < 0 ? 'down' : 'flat';
    const symbol = diffPP > 0 ? '▲' : diffPP < 0 ? '▼' : '■';
    const prevText = prevFormatted ? `（前季 ${prevFormatted}）` : '';
    return {
      dir,
      text: `${symbol} ${sign}${diffPP.toFixed(1)}pp QoQ${prevText}`
    };
  } else {
    if (prev === 0) {
      const prevText = prevFormatted ? `（前季 ${prevFormatted}）` : '';
      return { dir: 'flat', text: `■ 0.0% QoQ${prevText}` };
    }
    const pctChange = ((curr - prev) / Math.abs(prev)) * 100;
    const sign = pctChange > 0 ? '+' : '';
    const dir = pctChange > 0 ? 'up' : pctChange < 0 ? 'down' : 'flat';
    const symbol = pctChange > 0 ? '▲' : pctChange < 0 ? '▼' : '■';
    const prevText = prevFormatted ? `（前季 ${prevFormatted}）` : '';
    return {
      dir,
      text: `${symbol} ${sign}${pctChange.toFixed(1)}% QoQ${prevText}`
    };
  }
}

function getTrendSymbol(latest, oldest) {
  if (latest === null || latest === undefined || oldest === null || oldest === undefined) {
    return { symbol: '—', cls: 'flat' };
  }
  if (latest > oldest) return { symbol: '▲', cls: 'up' };
  if (latest < oldest) return { symbol: '▼', cls: 'down' };
  return { symbol: '■', cls: 'flat' };
}

/* -------------------------------------------------------------------------- */
/* Error Rendering                                                            */
/* -------------------------------------------------------------------------- */

function showError(title, message, availableCodes) {
  const stockError = document.getElementById('stockError');
  stockError.style.display = 'block';

  let listHtml = '';
  if (availableCodes && availableCodes.length > 0) {
    listHtml = `
      <div class="available-list">
        <span style="width:100%; font-weight:700; margin-bottom:0.25rem;">可供查看之標的列表：</span>
        ${availableCodes
          .map(
            (item) =>
              `<a class="available-tag" href="stock.html?code=${item.ticker}">${item.ticker} ${item.name}</a>`
          )
          .join('')}
      </div>
    `;
  }

  stockError.innerHTML = `
    <div class="error-title">${title}</div>
    <div>${message}</div>
    ${listHtml}
    <div style="margin-top:1rem;">
      <a class="back-link" href="./theme-momentum.html">← 返回題材雷達頁面</a>
    </div>
  `;
}

/* -------------------------------------------------------------------------- */
/* Header Rendering                                                           */
/* -------------------------------------------------------------------------- */

function renderHeader(nameZh, code, exchange, symbolData) {
  const stockTitle = document.getElementById('stockTitle');
  const stockMeta = document.getElementById('stockMeta');
  const stockActions = document.getElementById('stockActions');

  stockTitle.textContent = `${nameZh} (${code})`;

  const typek = exchange === 'TPEX' ? 'otc' : 'sii';
  const mopsUrl = `https://mops.twse.com.tw/mops/web/t05st01?step=1&co_id=${code}&TYPEK=${typek}`;

  stockMeta.innerHTML = `
    <span class="stock-meta-item">市場類別：<strong>${exchange}</strong></span>
    <span class="stock-meta-item">資料期別：<strong>${symbolData.fiscal_quarter || '—'}</strong></span>
    <span class="stock-meta-item">資料編製：<strong>${symbolData.basis === 'parent_only' ? '個體財報' : '合併財報'}</strong></span>
    <span class="stock-meta-item">資料來源：<strong>${symbolData.source || 'Goodinfo.tw'}</strong></span>
    <span class="stock-meta-item">擷取時間：<strong>${symbolData.fetched_at ? symbolData.fetched_at.replace('T', ' ').substring(0, 19) : '—'}</strong></span>
  `;

  stockActions.innerHTML = `
    <a class="btn-mops" href="${mopsUrl}" target="_blank" rel="noopener noreferrer">
      📋 公開資訊觀測站 (MOPS) ↗
    </a>
  `;
}

/* -------------------------------------------------------------------------- */
/* KPI Cards Rendering                                                        */
/* -------------------------------------------------------------------------- */

function renderKpiCards(symbolData) {
  const kpiGrid = document.getElementById('kpiGrid');
  const quarters = symbolData.quarters || [];
  const latestQ = quarters[0] || {};
  const prevQ = quarters[1] || {};

  const statements = symbolData.statements || {};
  const balance = statements.balance || {};

  const latestPeriod = quarters[0]?.period;
  const prevPeriod = quarters[1]?.period;

  const latestBal = latestPeriod ? balance[latestPeriod] || {} : {};
  const prevBal = prevPeriod ? balance[prevPeriod] || {} : {};

  // Current ratio calculation
  const latestCR = symbolData.health?.current_ratio ?? (latestBal.current_liabilities ? latestBal.current_assets / latestBal.current_liabilities : null);
  const prevCR = prevBal.current_liabilities ? prevBal.current_assets / prevBal.current_liabilities : null;

  // Debt ratio calculation
  const latestDR = symbolData.health?.debt_ratio ?? (latestBal.total_assets ? latestBal.total_liabilities / latestBal.total_assets : null);
  const prevDR = prevBal.total_assets ? prevBal.total_liabilities / prevBal.total_assets : null;

  // QoQ Objects
  const revQoQ = calcQoQ(latestQ.revenue, prevQ.revenue, false, `${formatNum(prevQ.revenue, 1)} 億`);
  const epsQoQ = calcQoQ(latestQ.eps, prevQ.eps, false, `${formatNum(prevQ.eps, 2)} 元`);
  const gmQoQ = calcQoQ(latestQ.gross_margin, prevQ.gross_margin, true, formatPct(prevQ.gross_margin, 1));
  const omQoQ = calcQoQ(latestQ.operating_margin, prevQ.operating_margin, true, formatPct(prevQ.operating_margin, 1));
  const nmQoQ = calcQoQ(latestQ.net_margin, prevQ.net_margin, true, formatPct(prevQ.net_margin, 1));
  const crQoQ = calcQoQ(latestCR, prevCR, true, formatPct(prevCR, 1));
  const drQoQ = calcQoQ(latestDR, prevDR, true, formatPct(prevDR, 1));

  const ttmEps = symbolData.valuation?.ttm_eps;

  const cards = [
    {
      label: `${latestQ.period || ''} 營業收入`,
      value: formatNum(latestQ.revenue, 1) + (latestQ.revenue !== undefined ? ' 億' : ''),
      change: revQoQ.text,
      dir: revQoQ.dir,
      cardClass: 'blue'
    },
    {
      label: `${latestQ.period || ''} 每股盈餘 (EPS)`,
      value: formatNum(latestQ.eps, 2) + (latestQ.eps !== undefined ? ' 元' : ''),
      change: epsQoQ.text,
      dir: epsQoQ.dir,
      cardClass: ''
    },
    {
      label: `${latestQ.period || ''} 毛利率`,
      value: formatPct(latestQ.gross_margin, 1),
      change: gmQoQ.text,
      dir: gmQoQ.dir,
      cardClass: ''
    },
    {
      label: `${latestQ.period || ''} 營業利益率`,
      value: formatPct(latestQ.operating_margin, 1),
      change: omQoQ.text,
      dir: omQoQ.dir,
      cardClass: ''
    },
    {
      label: `${latestQ.period || ''} 淨利率`,
      value: formatPct(latestQ.net_margin, 1),
      change: nmQoQ.text,
      dir: nmQoQ.dir,
      cardClass: ''
    },
    {
      label: '流動比率',
      value: formatPct(latestCR, 1),
      change: crQoQ.text,
      dir: crQoQ.dir,
      cardClass: 'teal'
    },
    {
      label: '負債比率',
      value: formatPct(latestDR, 1),
      change: drQoQ.text,
      dir: drQoQ.dir,
      cardClass: 'orange'
    },
    {
      label: '近 4 季 TTM EPS',
      value: formatNum(ttmEps, 2) + (ttmEps !== undefined ? ' 元' : ''),
      change: '近 4 季累積每股盈餘',
      dir: 'flat',
      cardClass: 'purple'
    }
  ];

  kpiGrid.innerHTML = cards
    .map(
      (c) => `
    <div class="kpi-card ${c.cardClass}">
      <div class="kpi-label">${c.label}</div>
      <div class="kpi-value">${c.value}</div>
      <div class="kpi-change ${c.dir}">${c.change}</div>
    </div>
  `
    )
    .join('');
}

/* -------------------------------------------------------------------------- */
/* Charts Rendering                                                           */
/* -------------------------------------------------------------------------- */

function renderCharts(symbolData) {
  if (typeof Chart === 'undefined') {
    document.querySelectorAll('.chart-container').forEach((el) => {
      el.innerHTML =
        '<div class="chart-fallback">⚠️ 圖表元件載入受阻（Chart.js 庫未完成載入）。請參閱下方詳細數據表格。</div>';
    });
    return;
  }

  // Quarters in JSON are NEWEST FIRST. Reverse array so X-axis is OLDEST -> NEWEST.
  const chronologicalQuarters = [...(symbolData.quarters || [])].reverse();
  const periods = chronologicalQuarters.map((q) => q.period);

  const statements = symbolData.statements || {};
  const incomeStmt = statements.income || {};
  const balanceStmt = statements.balance || {};
  const cashFlowStmt = statements.cash_flow || {};

  const getStmtVal = (stmtObj, period, field) => {
    const val = stmtObj?.[period]?.[field];
    return val !== undefined && val !== null ? val : null;
  };

  const chartOptionsBase = {
    responsive: true,
    maintainAspectRatio: false,
    spanGaps: false,
    plugins: {
      legend: {
        position: 'top',
        labels: { font: { size: 11 }, boxWidth: 12 }
      }
    },
    scales: {
      x: { grid: { display: false } },
      y: { grid: { color: '#eef0eb' } }
    }
  };

  // 1. 營業收入與毛利率 (Dual Axis)
  const revData = periods.map((p) => getStmtVal(incomeStmt, p, 'revenue'));
  const gmData = chronologicalQuarters.map((q) => (q.gross_margin !== undefined ? q.gross_margin * 100 : null));

  new Chart(document.getElementById('chartRevenueMargin'), {
    type: 'bar',
    data: {
      labels: periods,
      datasets: [
        {
          label: '營業收入 (億元)',
          data: revData,
          backgroundColor: 'rgba(43, 108, 176, 0.65)',
          borderColor: '#2b6cb0',
          borderWidth: 1,
          yAxisID: 'y'
        },
        {
          label: '毛利率 (%)',
          type: 'line',
          data: gmData,
          borderColor: '#12684a',
          backgroundColor: '#12684a',
          pointRadius: 4,
          tension: 0.25,
          yAxisID: 'y2'
        }
      ]
    },
    options: {
      ...chartOptionsBase,
      scales: {
        x: { grid: { display: false } },
        y: {
          position: 'left',
          grid: { color: '#eef0eb' },
          title: { display: true, text: '億元', font: { size: 11 } }
        },
        y2: {
          position: 'right',
          grid: { display: false },
          ticks: { callback: (v) => v + '%' }
        }
      }
    }
  });

  // 2. 三層利潤率趨勢 (Lines)
  const omData = chronologicalQuarters.map((q) => (q.operating_margin !== undefined ? q.operating_margin * 100 : null));
  const nmData = chronologicalQuarters.map((q) => (q.net_margin !== undefined ? q.net_margin * 100 : null));

  new Chart(document.getElementById('chartMargins'), {
    type: 'line',
    data: {
      labels: periods,
      datasets: [
        {
          label: '毛利率 (%)',
          data: gmData,
          borderColor: '#2b6cb0',
          backgroundColor: '#2b6cb0',
          pointRadius: 4,
          tension: 0.25
        },
        {
          label: '營業利益率 (%)',
          data: omData,
          borderColor: '#12684a',
          backgroundColor: '#12684a',
          pointRadius: 4,
          tension: 0.25
        },
        {
          label: '淨利率 (%)',
          data: nmData,
          borderColor: '#dd6b20',
          backgroundColor: '#dd6b20',
          pointRadius: 4,
          tension: 0.25
        }
      ]
    },
    options: {
      ...chartOptionsBase,
      scales: {
        ...chartOptionsBase.scales,
        y: {
          grid: { color: '#eef0eb' },
          ticks: { callback: (v) => v + '%' }
        }
      }
    }
  });

  // 3. 營業費用結構 (Stacked Bars)
  const rdData = periods.map((p) => getStmtVal(incomeStmt, p, 'rd_expense'));
  const adminData = periods.map((p) => getStmtVal(incomeStmt, p, 'admin_expense'));
  const sellingData = periods.map((p) => getStmtVal(incomeStmt, p, 'selling_expense'));
  
  const hasEcl = periods.some((p) => getStmtVal(incomeStmt, p, 'expected_credit_loss') !== null);
  const eclData = hasEcl ? periods.map((p) => getStmtVal(incomeStmt, p, 'expected_credit_loss')) : null;

  const opexDatasets = [
    { label: '研究發展費用', data: rdData, backgroundColor: '#805ad5' },
    { label: '管理費用', data: adminData, backgroundColor: '#dd6b20' },
    { label: '推銷費用', data: sellingData, backgroundColor: '#319795' }
  ];

  if (hasEcl) {
    opexDatasets.push({ label: '預期信用減損', data: eclData, backgroundColor: '#e53e3e' });
  }

  new Chart(document.getElementById('chartOpex'), {
    type: 'bar',
    data: {
      labels: periods,
      datasets: opexDatasets
    },
    options: {
      ...chartOptionsBase,
      scales: {
        x: { stacked: true, grid: { display: false } },
        y: {
          stacked: true,
          grid: { color: '#eef0eb' },
          title: { display: true, text: '億元', font: { size: 11 } }
        }
      }
    }
  });

  // 4. 每股盈餘 EPS (Bar)
  const epsData = chronologicalQuarters.map((q) => (q.eps !== undefined ? q.eps : null));

  new Chart(document.getElementById('chartEps'), {
    type: 'bar',
    data: {
      labels: periods,
      datasets: [
        {
          label: 'EPS (元)',
          data: epsData,
          backgroundColor: 'rgba(18, 104, 74, 0.7)',
          borderColor: '#12684a',
          borderWidth: 1
        }
      ]
    },
    options: {
      ...chartOptionsBase,
      scales: {
        ...chartOptionsBase.scales,
        y: {
          grid: { color: '#eef0eb' },
          title: { display: true, text: '元', font: { size: 11 } }
        }
      }
    }
  });

  // 5. 現金流量三表 (Grouped Bars)
  const opCfData = periods.map((p) => getStmtVal(cashFlowStmt, p, 'operating'));
  const invCfData = periods.map((p) => getStmtVal(cashFlowStmt, p, 'investing'));
  const finCfData = periods.map((p) => getStmtVal(cashFlowStmt, p, 'financing'));

  new Chart(document.getElementById('chartCashFlow'), {
    type: 'bar',
    data: {
      labels: periods,
      datasets: [
        { label: '營業活動 CF', data: opCfData, backgroundColor: '#12684a' },
        { label: '投資活動 CF', data: invCfData, backgroundColor: '#dd6b20' },
        { label: '融資活動 CF', data: finCfData, backgroundColor: '#805ad5' }
      ]
    },
    options: {
      ...chartOptionsBase,
      scales: {
        ...chartOptionsBase.scales,
        y: {
          grid: { color: '#eef0eb' },
          title: { display: true, text: '億元', font: { size: 11 } }
        }
      }
    }
  });

  // 6. 資產負債結構 (Stacked Bars: Current vs Non-Current Assets)
  const curAssetsData = periods.map((p) => getStmtVal(balanceStmt, p, 'current_assets'));
  const nonCurAssetsData = periods.map((p) => {
    const tot = getStmtVal(balanceStmt, p, 'total_assets');
    const cur = getStmtVal(balanceStmt, p, 'current_assets');
    return tot !== null && cur !== null ? tot - cur : null;
  });

  new Chart(document.getElementById('chartBalance'), {
    type: 'bar',
    data: {
      labels: periods,
      datasets: [
        { label: '流動資產', data: curAssetsData, backgroundColor: '#2b6cb0' },
        { label: '非流動資產', data: nonCurAssetsData, backgroundColor: '#319795' }
      ]
    },
    options: {
      ...chartOptionsBase,
      scales: {
        x: { stacked: true, grid: { display: false } },
        y: {
          stacked: true,
          grid: { color: '#eef0eb' },
          title: { display: true, text: '億元', font: { size: 11 } }
        }
      }
    }
  });
}

/* -------------------------------------------------------------------------- */
/* Tables Rendering                                                           */
/* -------------------------------------------------------------------------- */

function renderTables(symbolData) {
  // Tables display quarters with NEWEST FIRST (matching JSON array order)
  const quarters = symbolData.quarters || [];
  const periods = quarters.map((q) => q.period);
  const statements = symbolData.statements || {};
  const incomeStmt = statements.income || {};
  const balanceStmt = statements.balance || {};
  const cashFlowStmt = statements.cash_flow || {};

  const buildHeaderHtml = () => `
    <tr>
      <th scope="col">項目</th>
      ${periods.map((p) => `<th scope="col">${p}</th>`).join('')}
      <th scope="col">趨勢評估</th>
    </tr>
  `;

  // 1. 損益表明細
  const incomeTable = document.getElementById('tableIncome');
  incomeTable.querySelector('thead').innerHTML = buildHeaderHtml();

  const quarterMap = {};
  quarters.forEach((q) => {
    quarterMap[q.period] = q;
  });

  const getInc = (p, field) => incomeStmt[p]?.[field];

  const hasEcl = periods.some((p) => getInc(p, 'expected_credit_loss') !== undefined && getInc(p, 'expected_credit_loss') !== null);

  const incomeRows = [
    { label: '營業收入', getVal: (p) => getInc(p, 'revenue'), format: (v) => formatNum(v, 1) },
    { label: '營業成本', getVal: (p) => getInc(p, 'cost_of_sales'), format: (v) => formatNum(v, 1) },
    { label: '營業毛利', getVal: (p) => getInc(p, 'gross_profit'), format: (v) => formatNum(v, 1), isTotal: true },
    { label: '毛利率', getVal: (p) => quarterMap[p]?.gross_margin, format: (v) => formatPct(v, 1) },
    { label: '營業費用', isHeader: true },
    { label: '推銷費用', getVal: (p) => getInc(p, 'selling_expense'), format: (v) => formatNum(v, 1) },
    { label: '管理費用', getVal: (p) => getInc(p, 'admin_expense'), format: (v) => formatNum(v, 1) },
    { label: '研究發展費用', getVal: (p) => getInc(p, 'rd_expense'), format: (v) => formatNum(v, 1) }
  ];

  if (hasEcl) {
    incomeRows.push({
      label: '預期信用減損',
      getVal: (p) => getInc(p, 'expected_credit_loss'),
      format: (v) => formatNum(v, 2)
    });
  }

  incomeRows.push(
    { label: '營業費用合計', getVal: (p) => getInc(p, 'operating_expense'), format: (v) => formatNum(v, 1) },
    { label: '營業利益', getVal: (p) => getInc(p, 'operating_income'), format: (v) => formatNum(v, 1), isTotal: true },
    { label: '營業利益率', getVal: (p) => quarterMap[p]?.operating_margin, format: (v) => formatPct(v, 1) },
    { label: '稅前淨利', getVal: (p) => getInc(p, 'pretax_income'), format: (v) => formatNum(v, 1) },
    { label: '稅後淨利', getVal: (p) => getInc(p, 'net_income'), format: (v) => formatNum(v, 1), isTotal: true },
    { label: '淨利率', getVal: (p) => quarterMap[p]?.net_margin, format: (v) => formatPct(v, 1) },
    { label: '每股盈餘 (EPS)', getVal: (p) => getInc(p, 'eps'), format: (v) => formatNum(v, 2) }
  );

  incomeTable.querySelector('tbody').innerHTML = renderTableBody(incomeRows, periods);

  // 2. 資產負債表摘要
  const balanceTable = document.getElementById('tableBalance');
  balanceTable.querySelector('thead').innerHTML = buildHeaderHtml();

  const getBal = (p, field) => balanceStmt[p]?.[field];

  const balanceRows = [
    { label: '現金及約當現金', getVal: (p) => getBal(p, 'cash'), format: (v) => formatNum(v, 1) },
    { label: '應收款項合計', getVal: (p) => getBal(p, 'receivables'), format: (v) => formatNum(v, 1) },
    { label: '存貨', getVal: (p) => getBal(p, 'inventory'), format: (v) => formatNum(v, 1) },
    { label: '流動資產合計', getVal: (p) => getBal(p, 'current_assets'), format: (v) => formatNum(v, 1), isTotal: true },
    {
      label: '非流動資產',
      getVal: (p) => {
        const tot = getBal(p, 'total_assets');
        const cur = getBal(p, 'current_assets');
        return tot !== undefined && cur !== undefined ? tot - cur : undefined;
      },
      format: (v) => formatNum(v, 1)
    },
    { label: '資產總額', getVal: (p) => getBal(p, 'total_assets'), format: (v) => formatNum(v, 1) },
    { label: '流動負債合計', getVal: (p) => getBal(p, 'current_liabilities'), format: (v) => formatNum(v, 1) },
    {
      label: '非流動負債',
      getVal: (p) => {
        const tot = getBal(p, 'total_liabilities');
        const cur = getBal(p, 'current_liabilities');
        return tot !== undefined && cur !== undefined ? tot - cur : undefined;
      },
      format: (v) => formatNum(v, 1)
    },
    { label: '負債總額', getVal: (p) => getBal(p, 'total_liabilities'), format: (v) => formatNum(v, 1) },
    { label: '股東權益總額', getVal: (p) => getBal(p, 'total_equity'), format: (v) => formatNum(v, 1), isTotal: true },
    {
      label: '流動比率',
      getVal: (p) => {
        const curA = getBal(p, 'current_assets');
        const curL = getBal(p, 'current_liabilities');
        return curA !== undefined && curL !== undefined && curL !== 0 ? curA / curL : undefined;
      },
      format: (v) => formatPct(v, 1)
    },
    {
      label: '負債比率',
      getVal: (p) => {
        const totL = getBal(p, 'total_liabilities');
        const totA = getBal(p, 'total_assets');
        return totL !== undefined && totA !== undefined && totA !== 0 ? totL / totA : undefined;
      },
      format: (v) => formatPct(v, 1)
    }
  ];

  balanceTable.querySelector('tbody').innerHTML = renderTableBody(balanceRows, periods);

  // 3. 現金流量摘要
  const cashFlowTable = document.getElementById('tableCashFlow');
  cashFlowTable.querySelector('thead').innerHTML = buildHeaderHtml();

  const getCf = (p, field) => cashFlowStmt[p]?.[field];

  const cashFlowRows = [
    { label: '營業活動淨現金流', getVal: (p) => getCf(p, 'operating'), format: (v) => formatNum(v, 1), isTotal: true },
    { label: '折舊費用', getVal: (p) => getCf(p, 'depreciation'), format: (v) => formatNum(v, 1) },
    { label: '投資活動淨現金流', getVal: (p) => getCf(p, 'investing'), format: (v) => formatNum(v, 1) },
    { label: '資本支出 (Capex)', getVal: (p) => getCf(p, 'capex'), format: (v) => formatNum(v, 1) },
    { label: '融資活動淨現金流', getVal: (p) => getCf(p, 'financing'), format: (v) => formatNum(v, 1) },
    { label: '發放現金股利', getVal: (p) => getCf(p, 'dividends_paid'), format: (v) => formatNum(v, 1) },
    {
      // Critical Rule 3: Free Cash Flow = operating + capex (capex is negative when investing)
      label: '自由現金流 (FCF)',
      getVal: (p) => {
        const op = getCf(p, 'operating');
        const cap = getCf(p, 'capex');
        return op !== undefined && cap !== undefined ? op + cap : undefined;
      },
      format: (v) => formatNum(v, 1),
      isTotal: true
    },
    { label: '期末現金餘額', getVal: (p) => getCf(p, 'ending_cash'), format: (v) => formatNum(v, 1) }
  ];

  cashFlowTable.querySelector('tbody').innerHTML = renderTableBody(cashFlowRows, periods);
}

function renderTableBody(rows, periods) {
  return rows
    .map((row) => {
      if (row.isHeader) {
        return `<tr class="section-header"><td colspan="${periods.length + 2}">${row.label}</td></tr>`;
      }

      const values = periods.map((p) => row.getVal(p));
      const latestVal = values[0];
      const oldestVal = values[values.length - 1];

      const trend = getTrendSymbol(latestVal, oldestVal);
      const rowClass = row.isTotal ? 'total-row' : '';

      const cells = values.map((v) => `<td>${row.format(v)}</td>`).join('');

      return `
      <tr class="${rowClass}">
        <td>${row.label}</td>
        ${cells}
        <td><span class="trend-badge ${trend.cls}">${trend.symbol}</span></td>
      </tr>
    `;
    })
    .join('');
}

/* -------------------------------------------------------------------------- */
/* Tab Switching Logic                                                        */
/* -------------------------------------------------------------------------- */

function setupTabs() {
  const tabBtn1 = document.getElementById('tabBtn1');
  const tabBtn2 = document.getElementById('tabBtn2');
  const tabPanel1 = document.getElementById('tabPanel1');
  const tabPanel2 = document.getElementById('tabPanel2');

  const switchTab = (activeBtn, activePanel, inactiveBtn, inactivePanel) => {
    activeBtn.classList.add('active');
    activeBtn.setAttribute('aria-selected', 'true');

    inactiveBtn.classList.remove('active');
    inactiveBtn.setAttribute('aria-selected', 'false');

    activePanel.style.display = 'block';
    activePanel.removeAttribute('hidden');

    inactivePanel.style.display = 'none';
    inactivePanel.setAttribute('hidden', 'true');
  };

  tabBtn1.addEventListener('click', () => switchTab(tabBtn1, tabPanel1, tabBtn2, tabPanel2));
  tabBtn2.addEventListener('click', () => switchTab(tabBtn2, tabPanel2, tabBtn1, tabPanel1));

  // Keyboard navigation for tablist
  const tabButtons = [tabBtn1, tabBtn2];
  tabButtons.forEach((btn, index) => {
    btn.addEventListener('keydown', (e) => {
      let targetIndex = null;
      if (e.key === 'ArrowRight') {
        targetIndex = (index + 1) % tabButtons.length;
      } else if (e.key === 'ArrowLeft') {
        targetIndex = (index - 1 + tabButtons.length) % tabButtons.length;
      }
      if (targetIndex !== null) {
        e.preventDefault();
        tabButtons[targetIndex].focus();
        tabButtons[targetIndex].click();
      }
    });
  });
}

/* -------------------------------------------------------------------------- */
/* Tab 2: Institutional Money-Flow Rendering                                  */
/* -------------------------------------------------------------------------- */

function renderInstitutionalFlows(code, flowsData, isFetchError) {
  const instNotice = document.getElementById('instFlowsNotice');
  const instError = document.getElementById('instFlowsError');
  const instContent = document.getElementById('instFlowsContent');

  if (!instNotice || !instError || !instContent) return;

  if (isFetchError) {
    instError.style.display = 'block';
    instError.innerHTML =
      '<div class="error-title">資料載入失敗</div><div>無法讀取三大法人籌碼數據檔案 (data/institutional-flows.json)。</div>';
    instContent.style.display = 'none';
    instNotice.style.display = 'none';
    return;
  }

  if (!flowsData || !flowsData.symbols) {
    instNotice.style.display = 'block';
    instNotice.innerHTML = '<strong>本標的當期無法人交易資料</strong>';
    instContent.style.display = 'none';
    instError.style.display = 'none';
    return;
  }

  // Resolve symbol key in institutional-flows.json (e.g. TWSE:2330 or TPEX:8299 or 2330)
  const symbolsMap = flowsData.symbols || {};
  const matchedKey = Object.keys(symbolsMap).find(
    (k) => k === code || k.endsWith(':' + code)
  );

  const entries = matchedKey ? symbolsMap[matchedKey] : null;

  if (!entries || !Array.isArray(entries) || entries.length === 0) {
    instNotice.style.display = 'block';
    instNotice.innerHTML = '<strong>本標的當期無法人交易資料</strong>';
    instContent.style.display = 'none';
    instError.style.display = 'none';
    return;
  }

  // Hide notice & error, show content
  instNotice.style.display = 'none';
  instError.style.display = 'none';
  instContent.style.display = 'block';

  // Render components
  renderInstKpiCards(entries);
  renderInstCharts(entries);
  renderInstTable(entries);
}

function formatSignedShares(val) {
  if (val === null || val === undefined || Number.isNaN(val)) return '—';
  const prefix = val > 0 ? '+' : '';
  return prefix + val.toLocaleString('zh-TW') + ' 股';
}

function getNetDirClass(val) {
  if (val === null || val === undefined) return 'flat';
  return val > 0 ? 'up' : val < 0 ? 'down' : 'flat';
}

function getNetDirText(val) {
  if (val === null || val === undefined) return '—';
  return val > 0 ? '買超' : val < 0 ? '賣超' : '平盤';
}

function renderInstKpiCards(entries) {
  const kpiGrid = document.getElementById('instKpiGrid');
  if (!kpiGrid) return;

  // Array is NEWEST FIRST; entries[0] is latest trading day
  const latest = entries[0] || {};
  const dateStr = latest.date || '';

  const cards = [
    {
      label: `${dateStr} 外資買賣超`,
      value: formatSignedShares(latest.foreign_net),
      change: getNetDirText(latest.foreign_net),
      dir: getNetDirClass(latest.foreign_net),
      cardClass: 'blue'
    },
    {
      label: `${dateStr} 投信買賣超`,
      value: formatSignedShares(latest.trust_net),
      change: getNetDirText(latest.trust_net),
      dir: getNetDirClass(latest.trust_net),
      cardClass: 'purple'
    },
    {
      label: `${dateStr} 自營商買賣超`,
      value: formatSignedShares(latest.dealer_net),
      change: getNetDirText(latest.dealer_net),
      dir: getNetDirClass(latest.dealer_net),
      cardClass: 'orange'
    },
    {
      label: `${dateStr} 三大法人合計`,
      value: formatSignedShares(latest.total_net),
      change: getNetDirText(latest.total_net),
      dir: getNetDirClass(latest.total_net),
      cardClass: 'teal'
    }
  ];

  kpiGrid.innerHTML = cards
    .map(
      (c) => `
    <div class="kpi-card ${c.cardClass}">
      <div class="kpi-label">${c.label}</div>
      <div class="kpi-value">${c.value}</div>
      <div class="kpi-change ${c.dir}">${c.change}</div>
    </div>
  `
    )
    .join('');
}

function renderInstCharts(entries) {
  if (typeof Chart === 'undefined') {
    document.querySelectorAll('#instChartsGrid .chart-container').forEach((el) => {
      el.innerHTML =
        '<div class="chart-fallback">⚠️ 圖表元件載入受阻（Chart.js 庫未完成載入）。請參閱下方詳細數據表格。</div>';
    });
    return;
  }

  // Array in JSON is NEWEST FIRST. Reverse array so X-axis is OLDEST -> NEWEST.
  const chronological = [...entries].reverse();
  const dates = chronological.map((e) => e.date);

  const chartOptionsBase = {
    responsive: true,
    maintainAspectRatio: false,
    spanGaps: false,
    plugins: {
      legend: {
        position: 'top',
        labels: { font: { size: 11 }, boxWidth: 12 }
      },
      tooltip: {
        callbacks: {
          label: (ctx) =>
            `${ctx.dataset.label}: ${
              ctx.parsed.y !== null
                ? (ctx.parsed.y > 0 ? '+' : '') + ctx.parsed.y.toLocaleString('zh-TW') + ' 股'
                : '—'
            }`
        }
      }
    },
    scales: {
      x: { grid: { display: false } },
      y: {
        grid: { color: '#eef0eb' },
        ticks: { callback: (v) => v.toLocaleString('zh-TW') }
      }
    }
  };

  // Chart 1: Grouped Bars per day (外資 / 投信 / 自營商)
  const canvas1 = document.getElementById('chartInstDaily');
  if (canvas1) {
    new Chart(canvas1, {
      type: 'bar',
      data: {
        labels: dates,
        datasets: [
          {
            label: '外資 (股)',
            data: chronological.map((e) => (e.foreign_net !== undefined ? e.foreign_net : null)),
            backgroundColor: '#2b6cb0'
          },
          {
            label: '投信 (股)',
            data: chronological.map((e) => (e.trust_net !== undefined ? e.trust_net : null)),
            backgroundColor: '#805ad5'
          },
          {
            label: '自營商 (股)',
            data: chronological.map((e) => (e.dealer_net !== undefined ? e.dealer_net : null)),
            backgroundColor: '#dd6b20'
          }
        ]
      },
      options: chartOptionsBase
    });
  }

  // Chart 2: 三大法人合計 per day + Cumulative Line
  let runningCum = 0;
  const cumData = chronological.map((e) => {
    if (e.total_net !== null && e.total_net !== undefined) {
      runningCum += e.total_net;
      return runningCum;
    }
    return null;
  });

  const canvas2 = document.getElementById('chartInstCum');
  if (canvas2) {
    new Chart(canvas2, {
      type: 'bar',
      data: {
        labels: dates,
        datasets: [
          {
            label: '單日合計 (股)',
            data: chronological.map((e) => (e.total_net !== undefined ? e.total_net : null)),
            backgroundColor: 'rgba(43, 108, 176, 0.65)',
            borderColor: '#2b6cb0',
            borderWidth: 1,
            yAxisID: 'y'
          },
          {
            label: '累計籌碼流向 (股)',
            type: 'line',
            data: cumData,
            borderColor: '#12684a',
            backgroundColor: '#12684a',
            pointRadius: 4,
            tension: 0.25,
            yAxisID: 'y'
          }
        ]
      },
      options: chartOptionsBase
    });
  }
}

function renderInstTable(entries) {
  const table = document.getElementById('tableInstFlows');
  if (!table) return;

  const tbody = table.querySelector('tbody');
  if (!tbody) return;

  // Display newest first (entries array order)
  tbody.innerHTML = entries
    .map((item) => {
      const dirText = getNetDirText(item.total_net);
      const dirClass = getNetDirClass(item.total_net);

      return `
      <tr>
        <td>${item.date || '—'}</td>
        <td>${formatSignedShares(item.foreign_net)}</td>
        <td>${formatSignedShares(item.trust_net)}</td>
        <td>${formatSignedShares(item.dealer_net)}</td>
        <td style="font-weight:700;">${formatSignedShares(item.total_net)}</td>
        <td><span class="trend-badge ${dirClass}">${dirText}</span></td>
      </tr>
    `;
    })
    .join('');
}
