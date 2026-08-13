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

const PulseCards: React.FC<{ pulse: PulseIndex[] }> = ({ pulse }) => (
  <div className="pulse-grid" role="list" aria-label="國際指數">
    {pulse.map((item) => {
      const points = sparkPoints(item.series, 96, 34);
      return (
        <div className={`pulse-card ${item.up ? 'is-up' : 'is-down'}`} role="listitem" key={item.id}>
          <div className="pulse-card-head">
            <span className="pulse-label">{item.label}</span>
            <span className="pulse-delta mono-num">{item.delta}</span>
          </div>
          <div className="pulse-card-body">
            <strong className="pulse-value mono-num">{item.value}</strong>
            {points ? (
              <svg className="pulse-spark" viewBox="0 0 96 34" preserveAspectRatio="none"
                   aria-hidden="true" focusable="false">
                <polyline points={points} fill="none" strokeWidth="2" vectorEffect="non-scaling-stroke" />
              </svg>
            ) : null}
          </div>
        </div>
      );
    })}
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
  // Columns are scaled against the largest absolute move so the zero axis sits
  // where the data puts it, rather than at a fixed mid-height.
  const { up, down } = useMemo(() => ({
    up: Math.max(0.01, ...sectors.map((s) => s.chg)),
    down: Math.min(-0.01, ...sectors.map((s) => s.chg))
  }), [sectors]);
  const span = up - down;
  const zeroPct = (up / span) * 100;

  return (
    <div className="sector-chart-scroll">
      <div className="sector-chart" style={{ ['--zero' as string]: `${zeroPct}%` }}>
        <div className="sector-axis" style={{ top: `${zeroPct}%` }} />
        {sectors.map((sector) => {
          const positive = sector.chg >= 0;
          const height = (Math.abs(sector.chg) / span) * 100;
          return (
            <div className="sector-col" key={sector.name}>
              <span className={`sector-chg mono-num ${positive ? 'is-up' : 'is-down'}`}>
                {positive ? '+' : ''}{sector.chg.toFixed(2)}%
              </span>
              <div className="sector-plot">
                <div
                  className={`sector-bar ${positive ? 'is-up' : 'is-down'}`}
                  style={positive
                    ? { bottom: `${100 - zeroPct}%`, height: `${height}%` }
                    : { top: `${zeroPct}%`, height: `${height}%` }}
                />
              </div>
              <span className="sector-name">{sector.name}</span>
            </div>
          );
        })}
      </div>
    </div>
  );
};

const FlowColumn: React.FC<{ label: string; rows: FlowPanel['buy']; side: 'buy' | 'sell' }> =
  ({ label, rows, side }) => (
    <div className="pm-flow-col">
      <span className={`pm-flow-col-label is-${side}`}>{label}</span>
      {rows.length > 0 ? rows.map((row) => (
        <div className="pm-flow-row" key={`${side}-${row.rank}`}>
          <span className={`pm-flow-rank mono-num ${row.rank === 1 ? 'is-first' : ''}`}>{row.rank}</span>
          <span className="pm-flow-name">{row.name}</span>
          <span className={`pm-flow-value mono-num is-${side}`}>
            {side === 'buy' ? '+' : ''}{row.value.toLocaleString()}
          </span>
        </div>
      )) : <div className="pm-flow-empty">—</div>}
    </div>
  );

const FlowBoard: React.FC<{ panels: FlowPanel[]; asOf: string | null }> = ({ panels, asOf }) => (
  <div className="pm-flow-board">
    {panels.map((panel) => (
      <div className="pm-flow-panel" key={panel.id}>
        <div className="pm-flow-panel-head">
          <strong>{panel.title}</strong>
          <span className="mono-num">{panel.unit}{asOf ? ` · ${asOf}` : ''}</span>
        </div>
        <div className="pm-flow-panel-body">
          <FlowColumn label="買超" rows={panel.buy} side="buy" />
          <FlowColumn label="賣超" rows={panel.sell} side="sell" />
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
  const hasPulse = (data.pulse?.length ?? 0) > 0;
  const hasSectors = data.sectors.length > 0;
  const hasFlows = data.flows.panels.some((panel) => panel.buy.length + panel.sell.length > 0);

  // Mobile collapses the three data boards into one switcher so a single
  // screen does not scroll past several full-width charts.
  const [board, setBoard] = useState<'pulse' | 'flows' | 'sectors'>('pulse');

  return (
    <section className="pre-market-section">
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
          <strong>目前無重大事件</strong>
          <span>近 72 小時國際消息面平靜，以下為次要留意事項與一般新聞。</span>
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

      {(hasPulse || hasSectors || hasFlows) ? (
        <div className="market-boards">
          <div className="board-tabs" role="tablist" aria-label="市場數據">
            {hasPulse ? (
              <button type="button" role="tab" aria-selected={board === 'pulse'}
                className={board === 'pulse' ? 'is-selected' : ''}
                onClick={() => setBoard('pulse')}>國際指數</button>
            ) : null}
            {hasFlows ? (
              <button type="button" role="tab" aria-selected={board === 'flows'}
                className={board === 'flows' ? 'is-selected' : ''}
                onClick={() => setBoard('flows')}>三大法人買賣超</button>
            ) : null}
            {hasSectors ? (
              <button type="button" role="tab" aria-selected={board === 'sectors'}
                className={board === 'sectors' ? 'is-selected' : ''}
                onClick={() => setBoard('sectors')}>類股表現</button>
            ) : null}
          </div>

          {hasPulse && board === 'pulse' ? <PulseCards pulse={data.pulse} /> : null}

          {hasFlows && board === 'flows' ? (
            <section className="board-section">
              <div className="section-heading">
                <h2>類股買賣超排行 · 依券商類型</h2>
                <span className="section-note">前一交易日</span>
              </div>
              <FlowBoard panels={data.flows.panels} asOf={data.flows.as_of} />
            </section>
          ) : null}

          {hasSectors && board === 'sectors' ? (
            <section className="board-section">
              <div className="section-heading">
                <h2>類股漲跌表現</h2><span className="section-note">依當日漲跌幅排序</span>
              </div>
              <SectorBoard sectors={data.sectors} />
            </section>
          ) : null}
        </div>
      ) : null}
    </section>
  );
};
