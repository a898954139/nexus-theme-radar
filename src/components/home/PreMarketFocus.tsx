import React, { useMemo, useState } from 'react';
import { DeviceType, FlowPanel, FocusEvent, PreMarketData, PulseIndex, SectorChange } from '../../types';

interface PreMarketFocusProps {
  data: PreMarketData;
  device: DeviceType;
}

/** Split "A → B → C" into pills. The chain is the product's core claim -- it
 *  says how a headline reaches a Taiwan share price -- so it sits directly
 *  under the title rather than at the foot of the card. */
function channelSteps(channel: string): string[] {
  return channel.split('→').map((step) => step.trim()).filter(Boolean);
}

function formatTime(iso: string): string {
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return '—';
  const now = new Date();
  const sameDay = date.toDateString() === now.toDateString();
  const hhmm = `${String(date.getHours()).padStart(2, '0')}:${String(date.getMinutes()).padStart(2, '0')}`;
  if (sameDay) return hhmm;
  const md = `${String(date.getMonth() + 1).padStart(2, '0')}/${String(date.getDate()).padStart(2, '0')}`;
  return `${md} ${hhmm}`;
}

/** Sparkline as a normalised polyline. Points are remapped to a fixed box, so a
 *  symbol with fewer accumulated closes still draws at full width.
 *
 *  The series accumulates one point per pipeline run, so a freshly deployed
 *  board has a single close. That draws a flat baseline rather than nothing:
 *  an empty slot next to eight populated ones reads as a broken chart, while a
 *  flat line correctly says "no movement recorded yet". */
function sparkPoints(series: number[], width = 52, height = 16): string {
  if (series.length === 0) return '';
  const mid = (height / 2).toFixed(1);
  if (series.length === 1) return `${width * 0.3},${mid} ${width * 0.7},${mid}`;
  const min = Math.min(...series);
  const max = Math.max(...series);
  const span = max - min || 1;
  return series
    .map((value, index) => {
      const x = (index / (series.length - 1)) * width;
      const y = height - ((value - min) / span) * height;
      return `${x.toFixed(1)},${y.toFixed(1)}`;
    })
    .join(' ');
}

const PulseBar: React.FC<{ pulse: PulseIndex[] }> = ({ pulse }) => (
  <div className="pulse-wrap">
    <div className="pulse-bar" role="list" aria-label="國際市場">
    {pulse.map((item) => {
      const points = sparkPoints(item.series);
      return (
        <div className={`pulse-item ${item.up ? 'is-up' : 'is-down'}`} role="listitem" key={item.id}>
          <span className="pulse-label">{item.label}</span>
          <span className="pulse-value mono-num">{item.value}</span>
          <span className="pulse-delta mono-num">{item.delta}</span>
          {points ? (
            <svg className="pulse-spark" viewBox="0 0 52 16" aria-hidden="true" focusable="false">
              <polyline points={points} fill="none" strokeWidth="1.5" vectorEffect="non-scaling-stroke" />
            </svg>
          ) : null}
        </div>
      );
    })}
    </div>
  </div>
);

const FocusCard: React.FC<{ event: FocusEvent }> = ({ event }) => {
  const [showEn, setShowEn] = useState(false);
  const [showRelated, setShowRelated] = useState(false);
  const steps = channelSteps(event.channel);

  return (
    <article className={`focus-card focus-${event.tier}`}>
      <div className="focus-card-head">
        {event.tier === 'critical' ? <span className="focus-badge">重大</span> : null}
        <span className="focus-act">{event.actLabel}</span>
        <span className="focus-path">{event.pathLabel}</span>
        <span className="focus-time mono-num">{formatTime(event.publishedAt)}</span>
      </div>

      <h3 className="focus-title">
        <a href={event.url || '#'} target="_blank" rel="noreferrer">{event.titleZh}</a>
      </h3>

      <div className="focus-chain" aria-label="傳導鏈">
        {steps.map((step, index) => (
          <React.Fragment key={`${event.id}-step-${index}`}>
            {index > 0 ? <span className="focus-chain-arrow" aria-hidden="true">→</span> : null}
            <span className="focus-chain-pill">{step}</span>
          </React.Fragment>
        ))}
      </div>

      {event.sectors.length > 0 ? (
        <div className="focus-sectors">
          {event.sectors.map((sector) => (
            <span className="focus-sector-chip" key={`${event.id}-${sector}`}>{sector}</span>
          ))}
        </div>
      ) : null}

      <div className="focus-card-foot">
        <span className="focus-speaker">{event.speaker}</span>
        <button
          type="button"
          className={`focus-en-toggle ${showEn ? 'is-open' : ''}`}
          aria-expanded={showEn}
          aria-label="顯示英文原文"
          onClick={() => setShowEn((open) => !open)}
        >EN</button>
        {event.related.length > 0 ? (
          <button
            type="button"
            className="focus-related-toggle"
            aria-expanded={showRelated}
            onClick={() => setShowRelated((open) => !open)}
          >＋{event.related.length} 則</button>
        ) : null}
      </div>

      {showEn ? <p className="focus-en">{event.titleEn}</p> : null}

      {showRelated ? (
        <ul className="focus-related">
          {event.related.map((item, index) => (
            <li key={`${event.id}-rel-${index}`}>
              <a href={item.url || '#'} target="_blank" rel="noreferrer">{item.title}</a>
            </li>
          ))}
        </ul>
      ) : null}
    </article>
  );
};

const SectorBoard: React.FC<{ sectors: SectorChange[] }> = ({ sectors }) => {
  // Bars scale against the strongest move on each side, so a flat day still
  // reads as a distribution rather than a row of stubs.
  const peak = useMemo(
    () => Math.max(1, ...sectors.map((sector) => Math.abs(sector.chg))),
    [sectors]
  );

  return (
    <div className="sector-board">
      {sectors.map((sector) => (
        <div className="sector-row" key={sector.name}>
          <span className="sector-name">{sector.name}</span>
          <div className="sector-track">
            <div
              className={`sector-bar ${sector.chg >= 0 ? 'is-up' : 'is-down'}`}
              style={{ width: `${Math.max(2, (Math.abs(sector.chg) / peak) * 100)}%` }}
            />
          </div>
          <span className={`sector-chg mono-num ${sector.chg >= 0 ? 'is-up' : 'is-down'}`}>
            {sector.chg >= 0 ? '+' : ''}{sector.chg.toFixed(2)}%
          </span>
        </div>
      ))}
    </div>
  );
};

const FlowBoard: React.FC<{ panels: FlowPanel[]; asOf: string | null }> = ({ panels, asOf }) => (
  <div className="flow-board">
    {panels.map((panel) => (
      <div className="flow-panel" key={panel.id}>
        <div className="flow-panel-head">
          <strong>{panel.title}</strong>
          <span className="mono-num">{panel.unit}{asOf ? ` · ${asOf}` : ''}</span>
        </div>
        <div className="flow-panel-body">
          <div className="flow-side">
            <span className="flow-side-label is-buy">買超</span>
            {panel.buy.length > 0 ? panel.buy.map((row) => (
              <div className="flow-row" key={`${panel.id}-b-${row.rank}`}>
                <span className="flow-rank mono-num">{row.rank}</span>
                <span className="flow-name">{row.name}</span>
                <span className="flow-value mono-num is-buy">+{row.value.toLocaleString()}</span>
              </div>
            )) : <div className="flow-empty">—</div>}
          </div>
          <div className="flow-side">
            <span className="flow-side-label is-sell">賣超</span>
            {panel.sell.length > 0 ? panel.sell.map((row) => (
              <div className="flow-row" key={`${panel.id}-s-${row.rank}`}>
                <span className="flow-rank mono-num">{row.rank}</span>
                <span className="flow-name">{row.name}</span>
                <span className="flow-value mono-num is-sell">{row.value.toLocaleString()}</span>
              </div>
            )) : <div className="flow-empty">—</div>}
          </div>
        </div>
      </div>
    ))}
  </div>
);

export const PreMarketFocus: React.FC<PreMarketFocusProps> = ({ data, device }) => {
  // On a quiet morning nothing is critical. That is the common case, not an
  // error state, so the section says so instead of rendering an empty shell.
  const critical = data.events.filter((event) => event.tier === 'critical');
  const watch = data.events.filter((event) => event.tier === 'watch');
  const hasSectors = data.sectors.length > 0;
  const hasFlows = data.flows.panels.some((panel) => panel.buy.length + panel.sell.length > 0);

  // Mobile collapses the three data boards into one switcher so a single
  // screen does not scroll past several full-width charts.
  const [board, setBoard] = useState<'sectors' | 'flows'>('sectors');
  const isMobile = device === 'mobile';

  return (
    <section className="pre-market-section">
      {data.pulse && data.pulse.length > 0 ? <PulseBar pulse={data.pulse} /> : null}

      <header className="page-intro">
        <span className="page-kicker">PRE-MARKET FOCUS</span>
        <h1>盤前焦點</h1>
        <div className="gold-rule" />
        <p>開盤前的國際消息面：只留下有台股傳導路徑的事件，並標明它會影響哪些族群。</p>
      </header>

      {critical.length > 0 ? (
        <div className="focus-grid focus-grid-critical">
          {critical.map((event) => <FocusCard event={event} key={event.id} />)}
        </div>
      ) : (
        <div className="focus-calm">
          <strong>今日盤前無重大事件</strong>
          <span>國際消息面平靜，以下為次要留意事項與一般新聞。</span>
        </div>
      )}

      {watch.length > 0 ? (
        <div className="focus-watch-block">
          <div className="section-heading">
            <h2>留意</h2><span className="mono-num">{watch.length} 則</span>
          </div>
          <div className="focus-grid focus-grid-watch">
            {watch.map((event) => <FocusCard event={event} key={event.id} />)}
          </div>
        </div>
      ) : null}

      {(hasSectors || hasFlows) ? (
        <div className="market-boards">
          {isMobile ? (
            <div className="filter-tabs board-tabs" role="tablist" aria-label="市場數據">
              <button type="button" role="tab" aria-selected={board === 'sectors'}
                className={board === 'sectors' ? 'is-selected' : ''}
                onClick={() => setBoard('sectors')}>類股漲跌</button>
              <button type="button" role="tab" aria-selected={board === 'flows'}
                className={board === 'flows' ? 'is-selected' : ''}
                onClick={() => setBoard('flows')}>資金流向</button>
            </div>
          ) : null}

          {hasSectors && (!isMobile || board === 'sectors') ? (
            <section className="board-section">
              <div className="section-heading">
                <h2>類股漲跌表現</h2><span className="mono-num">{data.sectors.length} 類股</span>
              </div>
              <SectorBoard sectors={data.sectors} />
            </section>
          ) : null}

          {hasFlows && (!isMobile || board === 'flows') ? (
            <section className="board-section">
              <div className="section-heading">
                <h2>類股買賣超排行</h2>
                <span className="section-note">前一交易日</span>
              </div>
              <FlowBoard panels={data.flows.panels} asOf={data.flows.as_of} />
            </section>
          ) : null}
        </div>
      ) : null}
    </section>
  );
};
