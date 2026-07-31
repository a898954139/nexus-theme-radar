"use strict";

const LATEST_URL = "./data/public-theme-momentum-latest-v0.9.json";
const HISTORY_URL = "./data/public-theme-momentum-history-v0.9.json";
const LATEST_SCHEMA = "nexus_public_theme_momentum_latest.v0.9";
const HISTORY_SCHEMA = "nexus_public_theme_momentum_history.v0.9";
const MOMENTUM_RULE = "public_theme_momentum_v0.9";
const INCLUSION_RULE = "public_theme_momentum_inclusion_v0.9";
const HEAT_RULE = "public_theme_heat_v0.8";
const FRESHNESS_LIMIT_MS = 2 * 60 * 60 * 1000;
const SVG_NS = "http://www.w3.org/2000/svg";
const RANGE_LABELS = { 24: "24h", 72: "72h", 168: "7d" };

let latestPayload = null;
let historyPayload = null;
let selectedRangeHours = 72;

function isObject(value) {
  return value !== null && typeof value === "object" && !Array.isArray(value);
}

function hasExactKeys(value, expected) {
  return isObject(value)
    && Object.keys(value).length === expected.length
    && expected.every((key) => Object.hasOwn(value, key));
}

function parseTimestamp(value, label) {
  if (typeof value !== "string" || !value) throw new Error(`${label} is missing`);
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) throw new Error(`${label} is invalid`);
  return parsed;
}

function requireExactHour(value, label) {
  const parsed = parseTimestamp(value, label);
  if (parsed.getUTCMinutes() || parsed.getUTCSeconds() || parsed.getUTCMilliseconds()) {
    throw new Error(`${label} is not an exact hour`);
  }
  return parsed;
}

function isIntegerInRange(value, minimum, maximum = Number.MAX_SAFE_INTEGER) {
  return Number.isInteger(value) && value >= minimum && value <= maximum;
}

function isFiniteNumberInRange(value, minimum, maximum) {
  return typeof value === "number" && Number.isFinite(value)
    && value >= minimum && value <= maximum;
}

function validateThemeMetrics(theme, label) {
  if (!isIntegerInRange(theme.heat_score, 0, 100)
      || !isIntegerInRange(theme.momentum_score, 0, 100)
      || !isIntegerInRange(theme.event_count, 0)
      || !isIntegerInRange(theme.source_count, 0)
      || !isIntegerInRange(theme.tracking_candidate_count, 0)
      || !isIntegerInRange(theme.taiwan_mapping_count, 0)
      || !isIntegerInRange(theme.direct_mapping_event_count, 0, theme.event_count)
      || !isFiniteNumberInRange(theme.single_source_concentration, 0, 1)) {
    throw new Error(`${label} metrics are invalid`);
  }
  const lifecycleStages = ["new", "accelerating", "cooling", "rising", "steady"];
  if (!lifecycleStages.includes(theme.lifecycle_stage)) {
    throw new Error(`${label} lifecycle is invalid`);
  }
  const qualified = theme.qualification_status === "qualified"
    && theme.near_threshold_reason === null;
  const nearThreshold = theme.qualification_status === "near_threshold"
    && ["events_1_of_2", "sources_1_of_2"].includes(theme.near_threshold_reason);
  if (!qualified && !nearThreshold) throw new Error(`${label} inclusion is invalid`);
  parseTimestamp(theme.latest_qualifying_event_at, `${label} timestamp`);
}

function validateLatest(payload) {
  const topKeys = [
    "schema_version", "ranking_rule_version", "inclusion_rule_version",
    "heat_rule_version", "generated_at", "observed_hour", "market_id",
    "market_scope", "window_hours", "freshness_status", "theme_count", "themes",
  ];
  if (!hasExactKeys(payload, topKeys)) throw new Error("latest schema fields are invalid");
  if (payload.schema_version !== LATEST_SCHEMA
      || payload.ranking_rule_version !== MOMENTUM_RULE
      || payload.inclusion_rule_version !== INCLUSION_RULE
      || payload.heat_rule_version !== HEAT_RULE
      || payload.market_id !== "TW_EQUITY"
      || JSON.stringify(payload.market_scope) !== '["TW_EQUITY"]'
      || payload.window_hours !== 72) {
    throw new Error("latest versions or market are incompatible");
  }
  parseTimestamp(payload.generated_at, "latest.generated_at");
  requireExactHour(payload.observed_hour, "latest.observed_hour");
  if (!["current", "partial", "stale"].includes(payload.freshness_status)) {
    throw new Error("latest freshness_status is invalid");
  }
  if (!Array.isArray(payload.themes) || payload.theme_count !== payload.themes.length) {
    throw new Error("latest theme count is invalid");
  }
  const themeKeys = [
    "rank", "theme_id", "name_zh", "qualification_status",
    "near_threshold_reason", "momentum_score", "lifecycle_stage", "heat_score",
    "heat_change_24h", "source_change_24h", "event_count", "source_count",
    "tracking_candidate_count", "taiwan_mapping_count", "direct_mapping_event_count",
    "single_source_concentration", "latest_qualifying_event_at",
  ];
  const seen = new Set();
  payload.themes.forEach((theme, index) => {
    if (!hasExactKeys(theme, themeKeys) || theme.rank !== index + 1) {
      throw new Error("latest producer order is invalid");
    }
    if (!theme.theme_id || !theme.name_zh || seen.has(theme.theme_id)) {
      throw new Error("latest theme identity is invalid");
    }
    seen.add(theme.theme_id);
    validateThemeMetrics(theme, "latest theme");
    for (const change of [theme.heat_change_24h, theme.source_change_24h]) {
      if (change !== null && !Number.isInteger(change)) {
        throw new Error("latest 24h change is invalid");
      }
    }
  });
  return payload;
}

function validateHistory(payload) {
  const topKeys = [
    "schema_version", "ranking_rule_version", "inclusion_rule_version",
    "heat_rule_version", "generated_at", "market_id", "market_scope",
    "retention_hours", "oldest_observed_hour", "newest_observed_hour",
    "observation_count", "observations",
  ];
  if (!hasExactKeys(payload, topKeys)) throw new Error("history schema fields are invalid");
  if (payload.schema_version !== HISTORY_SCHEMA
      || payload.ranking_rule_version !== MOMENTUM_RULE
      || payload.inclusion_rule_version !== INCLUSION_RULE
      || payload.heat_rule_version !== HEAT_RULE
      || payload.market_id !== "TW_EQUITY"
      || JSON.stringify(payload.market_scope) !== '["TW_EQUITY"]'
      || payload.retention_hours !== 720) {
    throw new Error("history versions or market are incompatible");
  }
  parseTimestamp(payload.generated_at, "history.generated_at");
  requireExactHour(payload.oldest_observed_hour, "history oldest hour");
  requireExactHour(payload.newest_observed_hour, "history newest hour");
  if (!Array.isArray(payload.observations)
      || payload.observation_count !== payload.observations.length) {
    throw new Error("history observation count is invalid");
  }
  const themeKeys = [
    "theme_id", "rank", "qualification_status", "near_threshold_reason",
    "momentum_score", "lifecycle_stage", "heat_score", "event_count",
    "source_count", "tracking_candidate_count", "taiwan_mapping_count",
    "direct_mapping_event_count", "single_source_concentration",
    "latest_qualifying_event_at",
  ];
  let previousHour = -Infinity;
  payload.observations.forEach((observation) => {
    if (!hasExactKeys(observation, ["observed_hour", "themes"]) || !Array.isArray(observation.themes)) {
      throw new Error("history observation fields are invalid");
    }
    const hour = requireExactHour(observation.observed_hour, "history observed hour").getTime();
    if (hour <= previousHour) throw new Error("history hours are not ascending");
    previousHour = hour;
    observation.themes.forEach((theme) => {
      if (!hasExactKeys(theme, themeKeys)) throw new Error("history theme fields are invalid");
      if (!theme.theme_id || !isIntegerInRange(theme.rank, 1)) {
        throw new Error("history theme identity is invalid");
      }
      validateThemeMetrics(theme, "history theme");
    });
  });
  return payload;
}

async function fetchJson(url) {
  const response = await fetch(url, { cache: "no-store" });
  if (!response.ok) throw new Error(`HTTP ${response.status}`);
  return response.json();
}

function setState(state, message) {
  const status = document.getElementById("momentumStatus");
  status.dataset.state = state;
  status.textContent = message;
}

function formatHour(value) {
  return new Intl.DateTimeFormat("zh-TW", {
    month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit",
    hour12: false, timeZone: "Asia/Taipei",
  }).format(parseTimestamp(value, "display timestamp"));
}

function metricText(value) {
  if (value === null) return "尚無 24h 基準";
  return `${value > 0 ? "+" : ""}${value}`;
}

function renderLatest(payload) {
  const container = document.getElementById("latestThemes");
  container.replaceChildren();
  document.getElementById("latestObservedAt").textContent = `觀測 ${formatHour(payload.observed_hour)}`;
  payload.themes.forEach((theme) => {
    const article = document.createElement("article");
    article.className = "theme-card";
    const qualification = theme.qualification_status === "qualified" ? "已達門檻" : "接近門檻";
    article.innerHTML = `
      <div class="theme-card-top">
        <span class="rank">#${theme.rank}</span>
        <span class="qualification">${qualification}</span>
      </div>
      <h3></h3>
      <div class="score-row">
        <strong class="score">${theme.momentum_score}</strong>
        <span class="score-label">動能 / 100</span>
      </div>
      <div class="metric-row"><span>目前熱度</span><strong>${theme.heat_score}</strong></div>
      <div class="metric-row"><span>24h 熱度變化</span><strong>${metricText(theme.heat_change_24h)}</strong></div>
      <div class="metric-row"><span>獨立來源</span><strong>${theme.source_count}</strong></div>
      <div class="metric-row"><span>階段</span><strong class="lifecycle">${theme.lifecycle_stage}</strong></div>
    `;
    article.querySelector("h3").textContent = theme.name_zh;
    container.append(article);
  });
  container.setAttribute("aria-busy", "false");
}

function splitSeriesAtGaps(points) {
  const segments = [];
  points.forEach((point) => {
    const current = segments.at(-1);
    if (!current || point.hour - current.at(-1).hour > 60 * 60 * 1000) {
      segments.push([point]);
    } else {
      current.push(point);
    }
  });
  return segments;
}

function historyUsability(latest, history, now = Date.now()) {
  if (latest.ranking_rule_version !== history.ranking_rule_version
      || latest.inclusion_rule_version !== history.inclusion_rule_version
      || latest.heat_rule_version !== history.heat_rule_version) {
    return { usable: false, state: "mixed-version", message: "最新資料與歷史資料版本不同，走勢暫停顯示。" };
  }
  if (now - parseTimestamp(history.generated_at, "history.generated_at").getTime() > FRESHNESS_LIMIT_MS) {
    return { usable: false, state: "stale", message: "歷史資料更新延遲；最新排行仍可查看。" };
  }
  if (history.newest_observed_hour !== latest.observed_hour || history.observations.length < 2) {
    return { usable: false, state: "accumulating", message: "歷史資料累積中；最新排行仍可查看。" };
  }
  return { usable: true, state: "ready", message: "題材動能已更新。" };
}

function filteredObservations(payload, rangeHours) {
  const newest = requireExactHour(payload.newest_observed_hour, "history newest hour").getTime();
  const cutoff = newest - (rangeHours - 1) * 60 * 60 * 1000;
  return payload.observations.filter((item) => {
    const hour = requireExactHour(item.observed_hour, "history observed hour").getTime();
    return hour >= cutoff && hour <= newest;
  });
}

function addSvgLine(svg, x1, y1, x2, y2) {
  const line = document.createElementNS(SVG_NS, "line");
  line.setAttribute("class", "chart-grid");
  line.setAttribute("x1", String(x1));
  line.setAttribute("x2", String(x2));
  line.setAttribute("y1", String(y1));
  line.setAttribute("y2", String(y2));
  svg.append(line);
}

function renderHistory(latest, history, rangeHours) {
  const observations = filteredObservations(history, rangeHours);
  const svg = document.getElementById("momentumChart");
  const title = svg.querySelector("title").cloneNode(true);
  const description = svg.querySelector("desc").cloneNode(true);
  svg.replaceChildren(title, description);
  [30, 90, 150, 210].forEach((y) => addSvgLine(svg, 55, y, 875, y));

  const firstHour = requireExactHour(history.newest_observed_hour, "newest").getTime()
    - (rangeHours - 1) * 60 * 60 * 1000;
  const span = Math.max(1, (rangeHours - 1) * 60 * 60 * 1000);
  let hasGap = false;
  latest.themes.forEach((theme, themeIndex) => {
    const points = observations.flatMap((observation) => {
      const row = observation.themes.find((candidate) => candidate.theme_id === theme.theme_id);
      return row ? [{ hour: new Date(observation.observed_hour).getTime(), score: row.momentum_score }] : [];
    });
    const segments = splitSeriesAtGaps(points);
    if (segments.length > 1) hasGap = true;
    segments.forEach((segment) => {
      if (segment.length < 2) return;
      const polyline = document.createElementNS(SVG_NS, "polyline");
      polyline.setAttribute("class", "chart-line");
      polyline.setAttribute("opacity", String(Math.max(0.35, 1 - themeIndex * 0.1)));
      polyline.setAttribute("points", segment.map((point) => {
        const x = 55 + ((point.hour - firstHour) / span) * 820;
        const y = 250 - point.score * 2.15;
        return `${x.toFixed(1)},${y.toFixed(1)}`;
      }).join(" "));
      svg.append(polyline);
    });
  });

  const names = new Map(latest.themes.map((theme) => [theme.theme_id, theme.name_zh]));
  const body = document.getElementById("historyTableBody");
  body.replaceChildren();
  observations.forEach((observation) => {
    observation.themes.forEach((theme) => {
      if (!names.has(theme.theme_id)) return;
      const row = document.createElement("tr");
      [
        formatHour(observation.observed_hour),
        names.get(theme.theme_id),
        theme.momentum_score,
        theme.heat_score,
        theme.lifecycle_stage,
      ].forEach((value) => {
        const cell = document.createElement("td");
        cell.textContent = String(value);
        row.append(cell);
      });
      body.append(row);
    });
  });
  document.getElementById("historyMeta").textContent = `${RANGE_LABELS[rangeHours]} · ${observations.length} 個觀測小時`;
  return hasGap;
}

function setRange(hours) {
  selectedRangeHours = hours;
  document.querySelectorAll("[data-range-hours]").forEach((button) => {
    const active = Number(button.dataset.rangeHours) === hours;
    button.classList.toggle("active", active);
    button.setAttribute("aria-pressed", String(active));
  });
  if (latestPayload && historyPayload) {
    const usability = historyUsability(latestPayload, historyPayload);
    if (usability.usable) {
      const hasGap = renderHistory(latestPayload, historyPayload, hours);
      setState(hasGap ? "gap" : "ready", hasGap ? "歷史資料含缺口；圖線不跨越缺少的小時。" : usability.message);
    }
  }
}

async function init() {
  setState("loading", "題材動能載入中…");
  document.querySelectorAll("[data-range-hours]").forEach((button) => {
    button.addEventListener("click", () => setRange(Number(button.dataset.rangeHours)));
  });
  const [latestResult, historyResult] = await Promise.allSettled([
    fetchJson(LATEST_URL),
    fetchJson(HISTORY_URL),
  ]);
  if (latestResult.status !== "fulfilled") {
    document.getElementById("latestThemes").setAttribute("aria-busy", "false");
    setState("latest-error", "最新題材動能暫時無法載入，請稍後再試。");
    return;
  }
  try {
    latestPayload = validateLatest(latestResult.value);
  } catch (error) {
    setState("latest-error", "最新題材動能格式不相容，暫停顯示。");
    return;
  }
  renderLatest(latestPayload);
  if (!latestPayload.themes.length) {
    setState("empty", "目前沒有達到已選門檻或接近門檻的題材。");
    return;
  }
  if (historyResult.status !== "fulfilled") {
    setState("history-error", "歷史走勢暫時無法載入；最新排行仍可查看。");
    return;
  }
  try {
    historyPayload = validateHistory(historyResult.value);
  } catch (error) {
    setState("history-error", "歷史走勢格式不相容；最新排行仍可查看。");
    return;
  }
  const usability = historyUsability(latestPayload, historyPayload);
  if (!usability.usable) {
    setState(usability.state, usability.message);
    return;
  }
  const hasGap = renderHistory(latestPayload, historyPayload, selectedRangeHours);
  if (hasGap) {
    setState("gap", "歷史資料含缺口；圖線不跨越缺少的小時。");
  } else if (latestPayload.freshness_status === "partial") {
    setState("partial", "部分來源暫時無法更新；目前排行與門檻維持有效。");
  } else if (latestPayload.freshness_status === "stale") {
    setState("stale", "最新排行更新延遲，請留意觀測時間。");
  } else {
    setState("ready", usability.message);
  }
}

init();
