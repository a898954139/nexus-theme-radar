import React, { useEffect, useRef, useState } from 'react';
import { MoatFailure, MoatRule, MoatScreenData, MoatScreenItem } from '../../types';
import { SectionHead } from '../home/FeedBlocks';
import './moat-screen.css';

// Rule set moat_v1 (job/scripts/moat_screen.py). Values come from the API;
// only the wording and the reasoning behind each line live here.
const RULES: MoatRule[] = ['roe_ttm', 'gross_margin_4q', 'debt_ratio', 'operating_cash_flow_ttm'];

const ruleLabel: Record<MoatRule, string> = {
  roe_ttm: 'ROE（近四季）',
  gross_margin_4q: '毛利率（近四季平均）',
  debt_ratio: '負債比',
  operating_cash_flow_ttm: '營業現金流（近四季）'
};

const shortLabel: Record<MoatRule, string> = {
  roe_ttm: 'ROE',
  gross_margin_4q: '毛利率',
  debt_ratio: '負債比',
  operating_cash_flow_ttm: '營業現金流'
};

const ruleBasis: Record<MoatRule, string> = {
  roe_ttm: '股東的錢一年要能賺回 8% 以上，大約是資金成本的下限；比全市場中位數略高。',
  gross_margin_4q: '毛利率長期低於 15% 多是代工或大宗商品，沒有定價權；約在全市場後 25% 的位置。',
  debt_ratio: '沿用台股分析的高槓桿警戒線（同「高槓桿」標記），景氣反轉時最先出事。',
  operating_cash_flow_ttm: '賺的是真錢，不是應收帳款（同「現金流轉弱」標記）。只擋長線：景氣上行時備貨會燒現金，短線不扣。'
};

function pct(value: number | null): string {
  return value === null ? '—' : `${(value * 100).toFixed(1)}%`;
}

function money(value: number | null): string {
  if (value === null) return '—';
  return `${value.toLocaleString('zh-TW', { maximumFractionDigits: Math.abs(value) < 10 ? 1 : 0 })} 億`;
}

function formatValue(rule: MoatRule, value: number | null): string {
  return rule === 'operating_cash_flow_ttm' ? money(value) : pct(value);
}

function thresholdText(rule: MoatRule, data: MoatScreenData): string {
  const t = data.thresholds;
  if (rule === 'roe_ttm') return `≥ ${pct(t.roe_ttm_min)}`;
  if (rule === 'gross_margin_4q') return `≥ ${pct(t.gross_margin_4q_min)}`;
  if (rule === 'debt_ratio') return `≤ ${pct(t.debt_ratio_max)}`;
  return `> ${t.operating_cash_flow_ttm_min_exclusive}`;
}

function ruleFailed(item: MoatScreenItem, rule: MoatRule): boolean {
  return item.failed.includes(rule) || item.failed.includes(`${rule}_missing` as MoatFailure) || item.failed.includes('no_fundamentals');
}

export function failureReason(failure: MoatFailure, item: MoatScreenItem, data: MoatScreenData): string {
  if (failure === 'no_fundamentals') return '沒有財報資料';
  if (failure.endsWith('_missing')) return `${shortLabel[failure.replace('_missing', '') as MoatRule]}資料不足`;
  const rule = failure as MoatRule;
  const value = formatValue(rule, item.metrics[rule]);
  if (rule === 'roe_ttm') return `ROE ${value}，未達 ${pct(data.thresholds.roe_ttm_min)}`;
  if (rule === 'gross_margin_4q') return `毛利率 ${value}，未達 ${pct(data.thresholds.gross_margin_4q_min)}`;
  if (rule === 'debt_ratio') return `負債比 ${value}，超過 ${pct(data.thresholds.debt_ratio_max)}`;
  return `營業現金流 ${value}，不是正的`;
}

/** Index of the report by instrument id, for the rows of the ranked lists. */
export function moatIndex(data: MoatScreenData | null): Map<string, MoatScreenItem> {
  return new Map((data?.items ?? []).map((item) => [item.instrument.instrument_id, item]));
}

/**
 * "?" next to the ranking title: a compact popover with how the list is
 * screened and why. Replaces the full-width rule table (user: too heavy).
 */
export const MoatInfo: React.FC<{ data: MoatScreenData; horizon: 'short' | 'long' }> = ({ data, horizon }) => {
  const [open, setOpen] = useState(false);
  const wrap = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!open) return undefined;
    const onDown = (event: MouseEvent) => { if (wrap.current && !wrap.current.contains(event.target as Node)) setOpen(false); };
    const onKey = (event: KeyboardEvent) => { if (event.key === 'Escape') setOpen(false); };
    document.addEventListener('mousedown', onDown);
    document.addEventListener('keydown', onKey);
    return () => { document.removeEventListener('mousedown', onDown); document.removeEventListener('keydown', onKey); };
  }, [open]);
  const c = data.candidates;
  const ruleCount = horizon === 'short' ? 3 : 4;
  const passed = horizon === 'short' ? c.short_pass : c.long_pass;
  const notSelected = data.items.filter((item) => (horizon === 'short' ? item.short_pass : item.long_pass) && !item.selected_top50).length;
  const updated = new Date(data.generated_at);
  const time = Number.isNaN(updated.getTime())
    ? data.generated_at
    : updated.toLocaleString('zh-TW', { timeZone: 'Asia/Taipei', month: 'numeric', day: 'numeric', hour: '2-digit', minute: '2-digit', hour12: false });
  const rules = data.rules.filter((stat) => (horizon === 'short' ? stat.in_short : stat.in_long));
  return (
    <div className="moat-info" ref={wrap}>
      <button
        type="button"
        className={`moat-info-btn${open ? ' is-open' : ''}`}
        aria-expanded={open}
        aria-controls="moat-info-pop"
        aria-label="怎麼篩選這些股票"
        title="怎麼篩選這些股票"
        onClick={() => setOpen((shown) => !shown)}
      ><i aria-hidden="true">?</i></button>
      {open ? (
        <div className="moat-info-pop" id="moat-info-pop" role="dialog" aria-label="篩選方式">
          <div className="moat-info-title"><b>怎麼選出這些股票</b><small className="mono-num">{data.rule_version} · {time}</small></div>
          <ol className="moat-info-steps">
            <li><b className="mono-num">{c.count}</b> 檔：新聞與題材帶到的股票</li>
            <li><b className="mono-num">{c.evaluated}</b> 檔：有財報可以檢查</li>
            <li><b className="mono-num">{passed}</b> 檔：過{horizon === 'short' ? '短線' : '長線'}財報門檻（{ruleCount} 條全過）</li>
            <li>依題材熱度排序取前 50{notSelected ? `；另有 ${notSelected} 檔過門檻但熱度不夠` : ''}</li>
          </ol>
          <p className="moat-info-why">新聞只決定「看誰」，財報決定「能不能進榜」：題材再熱，財報不及格就不排名。</p>
          <ul className="moat-info-rules">
            {rules.map((stat) => (
              <li key={stat.rule}>
                <div><b>{ruleLabel[stat.rule]}</b><em className="mono-num moat-threshold">{thresholdText(stat.rule, data)}</em></div>
                <p>{ruleBasis[stat.rule]}</p>
              </li>
            ))}
          </ul>
          <p className="moat-info-foot">每檔股票的「門檻」按鈕可看它每一條的實際數字。</p>
        </div>
      ) : null}
    </div>
  );
};

export const MoatToggle: React.FC<{ item: MoatScreenItem | undefined; horizon: 'short' | 'long'; open: boolean; onToggle: () => void }> = ({ item, horizon, open, onToggle }) => {
  if (!item) return null;
  const rules = horizon === 'short' ? RULES.slice(0, 3) : RULES;
  const passed = rules.filter((rule) => !ruleFailed(item, rule)).length;
  return (
    <button
      type="button"
      className={`moat-toggle${open ? ' is-open' : ''}`}
      aria-expanded={open}
      onClick={(event) => { event.stopPropagation(); onToggle(); }}
      onKeyDown={(event) => event.stopPropagation()}
    >
      門檻 {passed}/{rules.length} {open ? '▴' : '▾'}
    </button>
  );
};

export const MoatDetail: React.FC<{ item: MoatScreenItem; data: MoatScreenData; horizon: 'short' | 'long' }> = ({ item, data, horizon }) => (
  <div className="moat-detail" aria-label={`${item.instrument.name_zh} 財報門檻對照`}>
    {RULES.map((rule) => {
      const applies = horizon === 'long' || rule !== 'operating_cash_flow_ttm';
      const failed = ruleFailed(item, rule);
      return (
        <span className={`moat-cell${failed ? ' is-fail' : ' is-pass'}${applies ? '' : ' is-off'}`} key={rule}>
          <small>{ruleLabel[rule]}</small>
          <b className="mono-num">{formatValue(rule, item.metrics[rule])}</b>
          <em>門檻 {thresholdText(rule, data)} {failed ? '✗' : '✓'}{applies ? '' : '（短線不看）'}</em>
        </span>
      );
    })}
  </div>
);

const REJECTED_VISIBLE = 12;

export const MoatRejected: React.FC<{ data: MoatScreenData; horizon: 'short' | 'long' }> = ({ data, horizon }) => {
  const [showAll, setShowAll] = useState(false);
  const rejected = data.items
    .filter((item) => (horizon === 'short' ? !item.short_pass : !item.long_pass))
    .sort((left, right) =>
      Number(right.themes.some((t) => t.relation === 'direct')) - Number(left.themes.some((t) => t.relation === 'direct'))
      || left.failed.length - right.failed.length
      || left.instrument.instrument_id.localeCompare(right.instrument.instrument_id));
  if (!rejected.length) return null;
  return (
    <section className="moat-rejected" aria-label="沒過門檻的股票">
      <SectionHead level={3} title="被刷掉的股票" note={`${rejected.length} 檔 · 新聞有帶到，但財報沒過${horizon === 'short' ? '短線' : '長線'}門檻`} />
      <div className="moat-rejected-table" role="table">
        <div className="moat-rejected-head" role="row">
          <span role="columnheader">股票</span><span role="columnheader">題材</span>
          {RULES.map((rule) => <span role="columnheader" key={rule}>{shortLabel[rule]}</span>)}
          <span role="columnheader">沒過的原因</span>
        </div>
        {(showAll ? rejected : rejected.slice(0, REJECTED_VISIBLE)).map((item) => (
          <div className="moat-rejected-row" role="row" key={item.instrument.instrument_id}>
            <span role="cell" className="moat-stock"><b>{item.instrument.name_zh || item.instrument.symbol}</b><small className="mono-num">{item.instrument.symbol} · {item.instrument.exchange}</small></span>
            <span role="cell" className="moat-themes">{item.themes.slice(0, 2).map((t) => t.name_zh).join(' · ') || '—'}</span>
            {RULES.map((rule) => (
              <span role="cell" key={rule} className={`mono-num${ruleFailed(item, rule) && (horizon === 'long' || rule !== 'operating_cash_flow_ttm') ? ' is-fail' : ''}`}>
                {formatValue(rule, item.metrics[rule])}
              </span>
            ))}
            <span role="cell" className="moat-reasons">
              {item.failed
                .filter((failure) => horizon === 'long' || !failure.startsWith('operating_cash_flow_ttm'))
                .map((failure) => failureReason(failure, item, data))
                .join('；')}
            </span>
          </div>
        ))}
      </div>
      {rejected.length > REJECTED_VISIBLE ? (
        <div className="list-more"><button type="button" onClick={() => setShowAll((shown) => !shown)}>{showAll ? `收合至前 ${REJECTED_VISIBLE} 檔` : `顯示全部 ${rejected.length} 檔`}</button></div>
      ) : null}
    </section>
  );
};
