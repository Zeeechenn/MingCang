// ============================================================
// MingCang — 共享组件:store / 路由 / 格式化 / 图表 / Markdown
// ============================================================
import React from 'react';
import { createPortal } from 'react-dom';
import { MC_DATA } from './data';
const { useState, useEffect, useMemo, useRef, useCallback, createContext, useContext } = React;

// ---------- 极简全局 store ----------
export const MCStore = (() => {
  const D = MC_DATA;
  let state = {
    watchlist: D.WATCHLIST.map((w) => ({ ...w })),
    positions: D.POSITIONS.map((p) => ({ ...p })),
    reviews: D.REVIEWS.slice(),
    sessions: D.CHAT_SESSIONS.map((s) => ({ ...s, messages: s.messages.slice() })),
    runtime: { ...D.RUNTIME },
    memoryItems: D.MEMORY.items.slice(),
    live: 'demo',
    liveSources: {},
    snapshotAsOf: D.DEMO_META.snapshot_as_of,
    toast: null,
  };
  const subs = new Set<() => void>();
  return {
    get: () => state,
    set(patch) {
      state = { ...state, ...(typeof patch === 'function' ? patch(state) : patch) };
      subs.forEach((fn) => fn());
    },
    subscribe(fn: () => void) { subs.add(fn); return () => { subs.delete(fn); }; },
  };
})();

export function useStore(): [any, (patch: any) => void] {
  const [, force] = useState(0);
  useEffect(() => MCStore.subscribe(() => force((n) => n + 1)), []);
  return [MCStore.get(), MCStore.set];
}

let toastTimer: any = null;
export function toast(msg, tone = 'accent') {
  MCStore.set({ toast: { msg, tone } });
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => MCStore.set({ toast: null }), 2600);
}

// ---------- hash 路由 ----------
function parseHash() {
  const h = (location.hash || '#/').replace(/^#/, '');
  const seg = h.split('/').filter(Boolean);
  if (seg[0] === 'stock' && seg[1]) return { page: 'stock', symbol: decodeURIComponent(seg[1]) };
  if (!seg[0]) return { page: 'home' };
  return { page: seg[0] };
}
export function useRoute() {
  const [route, setRoute] = useState(parseHash);
  useEffect(() => {
    const fn = () => { setRoute(parseHash()); window.scrollTo(0, 0); };
    window.addEventListener('hashchange', fn);
    return () => window.removeEventListener('hashchange', fn);
  }, []);
  return route;
}
export function navigate(to) { location.hash = to; }

// ---------- 格式化 ----------
export const fmt = {
  price: (v, d = 2) => (v === null || v === undefined || isNaN(v) ? '–' : Number(v).toFixed(d)),
  money: (v) => (v === null || v === undefined || isNaN(v) ? '–' : Number(v).toLocaleString('zh-CN', { maximumFractionDigits: 0 })),
  signed: (v, d = 1) => (v === null || v === undefined || isNaN(v) ? '–' : `${v > 0 ? '+' : ''}${Number(v).toFixed(d)}`),
  signedPct: (v, d = 2) => (v === null || v === undefined || isNaN(v) ? '–' : `${v > 0 ? '+' : ''}${Number(v).toFixed(d)}%`),
  signedMoney: (v) => (v === null || v === undefined || isNaN(v) ? '–' : `${v > 0 ? '+' : ''}${Number(v).toLocaleString('zh-CN', { maximumFractionDigits: 0 })}`),
};
export const CCY = { CN: 'CNY', HK: 'HKD', US: 'USD' };
export const MKT = { CN: 'A股', HK: '港股', US: '美股' };

export function recTone(rec) {
  if (!rec) return 'badge-dim';
  if (/试错|买|关注/.test(rec)) return 'badge-up';
  if (/观望/.test(rec)) return 'badge-warn';
  if (/规避|卖/.test(rec)) return 'badge-down';
  return 'badge-dim';
}
export function ltTone(label) {
  if (label === '值得持有') return 'badge-up';
  if (label === '估值偏高') return 'badge-warn';
  if (label === '规避') return 'badge-down';
  return 'badge-accent';
}
export function pnlClass(v) { return (v || 0) >= 0 ? 'up' : 'down'; }

// ---------- 基础组件 ----------
export function Card({ title, eyebrow, right, children, className = '', pad = true, tour }: any) {
  return (
    <section className={`glass ${className}`} data-tour={tour}>
      {(title || eyebrow || right) && (
        <div className="card-head">
          <div>
            {eyebrow && <div className="t-eyebrow">{eyebrow}</div>}
            {title && <h2 className="t-title" style={{ margin: '2px 0 0' }}>{title}</h2>}
          </div>
          {right && <div className="row">{right}</div>}
        </div>
      )}
      {pad ? <div className="card-body">{children}</div> : children}
    </section>
  );
}

export function Metric({ label, value, tone = '', sub }: any) {
  return (
    <div className="glass-inset" style={{ padding: '10px 12px', minWidth: 0 }}>
      <div className="t-eyebrow">{label}</div>
      <div className={`t-num ${tone}`} style={{ marginTop: 4, fontSize: 17, fontWeight: 650, letterSpacing: '-0.01em', whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>{value}</div>
      {sub && <div className="t-faint" style={{ fontSize: 11, marginTop: 2 }}>{sub}</div>}
    </div>
  );
}

export function Badge({ tone = 'badge-dim', children }: any) {
  return <span className={`badge ${tone}`}>{children}</span>;
}

export function Toggle({ on, onChange, label }: any) {
  return (
    <button type="button" className={`toggle ${on ? 'on' : ''}`} role="switch" aria-checked={on} aria-label={label} onClick={() => onChange(!on)}></button>
  );
}

export function Seg({ value, options, onChange }: any) {
  return (
    <div className="seg">
      {options.map(([id, label]) => (
        <button key={id} type="button" className={value === id ? 'on' : ''} onClick={() => onChange(id)}>{label}</button>
      ))}
    </div>
  );
}

export function ScoreBar({ score, height = 6 }: any) {
  const c = Math.max(-100, Math.min(100, Number(score || 0)));
  const color = c > 20 ? 'var(--up)' : c < -20 ? 'var(--down)' : 'var(--warn)';
  return (
    <div className="score-track" style={{ height }}>
      <div className="score-fill" style={{ left: c < 0 ? `${50 - Math.abs(c) / 2}%` : '50%', width: `${Math.abs(c) / 2}%`, background: color }}></div>
      <div className="score-zero"></div>
    </div>
  );
}

export function Spark({ symbol, width = 88, height = 30 }: any) {
  const prices = (window.MC_DATA.PRICES[symbol] || []).slice(-30);
  if (!prices.length) return <svg width={width} height={height}></svg>;
  const vals = prices.map((p) => p.close);
  const min = Math.min(...vals), max = Math.max(...vals);
  const up = vals[vals.length - 1] >= vals[0];
  const pts = vals.map((v, i) => `${(i / (vals.length - 1)) * width},${height - 2 - ((v - min) / (max - min || 1)) * (height - 4)}`).join(' ');
  return (
    <svg width={width} height={height} aria-hidden="true">
      <polyline points={pts} fill="none" stroke={up ? 'var(--up)' : 'var(--down)'} strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" opacity="0.9"></polyline>
    </svg>
  );
}

// ---------- 主价格图 ----------
export function PriceChart({ symbol, signal }: any) {
  const ref = useRef<any>(null);
  const [w, setW] = useState(800);
  const [hover, setHover] = useState<any>(null);
  const prices = window.MC_DATA.PRICES[symbol] || [];
  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    const ro = new ResizeObserver(() => setW(el.clientWidth));
    ro.observe(el);
    setW(el.clientWidth);
    return () => ro.disconnect();
  }, []);
  if (!prices.length) {
    return <div className="empty">暂无价格数据。盘前同步任务运行后，这里会显示 120 日主图。</div>;
  }
  const H = 300, padL = 8, padR = 56, padT = 16, padB = 54, volH = 38;
  const iw = Math.max(100, w - padL - padR);
  const lows = prices.map((p) => p.low), highs = prices.map((p) => p.high);
  let min = Math.min(...lows), max = Math.max(...highs);
  if (signal?.stop_loss) min = Math.min(min, signal.stop_loss);
  if (signal?.take_profit) max = Math.max(max, signal.take_profit);
  const span = max - min || 1;
  min -= span * 0.04; max += span * 0.04;
  const x = (i) => padL + (i / (prices.length - 1)) * iw;
  const y = (v) => padT + (1 - (v - min) / (max - min)) * (H - padT - padB);
  const maxVol = Math.max(...prices.map((p) => p.volume));
  const closePath = prices.map((p, i) => `${i ? 'L' : 'M'}${x(i).toFixed(1)},${y(p.close).toFixed(1)}`).join('');
  const area = `${closePath}L${x(prices.length - 1).toFixed(1)},${H - padB}L${padL},${H - padB}Z`;
  const lastP = prices[prices.length - 1];
  const up = lastP.close >= prices[0].close;
  const lineColor = up ? 'var(--up)' : 'var(--down)';
  const gridVals = [0.25, 0.5, 0.75].map((f) => min + (max - min) * f);

  function onMove(e) {
    const rect = ref.current.getBoundingClientRect();
    const px = e.clientX - rect.left;
    const i = Math.round(((px - padL) / iw) * (prices.length - 1));
    if (i >= 0 && i < prices.length) setHover(i);
  }
  const hv = hover !== null ? prices[hover] : null;

  return (
    <div ref={ref} style={{ position: 'relative' }} onMouseMove={onMove} onMouseLeave={() => setHover(null)}>
      <svg width="100%" height={H} viewBox={`0 0 ${w} ${H}`} preserveAspectRatio="none" style={{ display: 'block' }}>
        <defs>
          <linearGradient id={`g-${symbol}`} x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor={up ? '#ff3b30' : '#34c759'} stopOpacity="0.18"></stop>
            <stop offset="100%" stopColor={up ? '#ff3b30' : '#34c759'} stopOpacity="0"></stop>
          </linearGradient>
        </defs>
        {gridVals.map((v, i) => (
          <g key={i}>
            <line x1={padL} x2={w - padR} y1={y(v)} y2={y(v)} stroke="var(--hairline-soft)" strokeDasharray="3 5"></line>
            <text x={w - padR + 8} y={y(v) + 4} fontSize="10.5" fill="var(--ink-3)" fontFamily="var(--font-mono)">{v.toFixed(v > 100 ? 0 : 2)}</text>
          </g>
        ))}
        <path d={area} fill={`url(#g-${symbol})`}></path>
        <path d={closePath} fill="none" stroke={lineColor} strokeWidth="2" strokeLinejoin="round"></path>
        {prices.map((p, i) => (
          <rect key={i} x={x(i) - iw / prices.length / 2.6} y={H - padB + 8 + (1 - p.volume / maxVol) * volH}
            width={Math.max(1, iw / prices.length / 1.3)} height={(p.volume / maxVol) * volH}
            fill={p.close >= p.open ? 'var(--up)' : 'var(--down)'} opacity="0.32"></rect>
        ))}
        {signal?.stop_loss && (
          <g>
            <line x1={padL} x2={w - padR} y1={y(signal.stop_loss)} y2={y(signal.stop_loss)} stroke="var(--down)" strokeWidth="1.2" strokeDasharray="6 4"></line>
            <text x={padL + 4} y={y(signal.stop_loss) - 5} fontSize="10.5" fill="var(--down)" fontWeight="600">止损 {signal.stop_loss}</text>
          </g>
        )}
        {signal?.take_profit && (
          <g>
            <line x1={padL} x2={w - padR} y1={y(signal.take_profit)} y2={y(signal.take_profit)} stroke="var(--up)" strokeWidth="1.2" strokeDasharray="6 4"></line>
            <text x={padL + 4} y={y(signal.take_profit) - 5} fontSize="10.5" fill="var(--up)" fontWeight="600">止盈 {signal.take_profit}</text>
          </g>
        )}
        {hv && (
          <g>
            <line x1={x(hover)} x2={x(hover)} y1={padT} y2={H - padB + 8 + volH} stroke="var(--ink-3)" strokeWidth="1" strokeDasharray="2 3"></line>
            <circle cx={x(hover)} cy={y(hv.close)} r="4" fill={lineColor} stroke="var(--glass-strong)" strokeWidth="2"></circle>
          </g>
        )}
        <text x={padL} y={H - 6} fontSize="10.5" fill="var(--ink-3)" fontFamily="var(--font-mono)">{prices[0].date}</text>
        <text x={w - padR} y={H - 6} fontSize="10.5" fill="var(--ink-3)" fontFamily="var(--font-mono)" textAnchor="end">{lastP.date}</text>
      </svg>
      {hv && (
        <div className="glass" style={{ position: 'absolute', top: 10, left: Math.min(Math.max(x(hover) - 70, 4), w - 170), padding: '8px 12px', borderRadius: 12, pointerEvents: 'none', fontSize: 12 }}>
          <div className="t-num t-faint">{hv.date}</div>
          <div className="row" style={{ gap: 10, marginTop: 2 }}>
            <span className="t-num" style={{ fontWeight: 650 }}>{hv.close.toFixed(2)}</span>
            <span className={`t-num ${hv.close >= hv.open ? 'up' : 'down'}`}>{fmt.signedPct(((hv.close - hv.open) / hv.open) * 100)}</span>
          </div>
        </div>
      )}
    </div>
  );
}

// ---------- Markdown ----------
export function inline(text: any, key?: any) {
  const parts = String(text).split(/(\*\*[^*]+\*\*|`[^`]+`)/g);
  return parts.map((p, i) => {
    if (p.startsWith('**') && p.endsWith('**')) return <strong key={i} style={{ color: 'var(--ink)', fontWeight: 650 }}>{p.slice(2, -2)}</strong>;
    if (p.startsWith('`') && p.endsWith('`')) return <code key={i}>{p.slice(1, -1)}</code>;
    return <span key={i}>{p}</span>;
  });
}

export function Markdown({ text }: any) {
  const blocks = useMemo(() => {
    const lines = String(text || '').split(/\r?\n/);
    const out: any[] = [];
    let i = 0;
    while (i < lines.length) {
      const line = lines[i];
      if (!line.trim()) { i++; continue; }
      if (line.startsWith('```')) {
        const buf: string[] = []; i++;
        while (i < lines.length && !lines[i].startsWith('```')) buf.push(lines[i++]);
        i++; out.push({ t: 'code', text: buf.join('\n') }); continue;
      }
      const h = line.match(/^(#{1,3})\s+(.*)/);
      if (h) { out.push({ t: `h${h[1].length}`, text: h[2] }); i++; continue; }
      if (/^\|/.test(line)) {
        const rows: string[][] = [];
        while (i < lines.length && /^\|/.test(lines[i])) { rows.push(lines[i].split('|').slice(1, -1).map((c) => c.trim())); i++; }
        const headers = rows[0] || [];
        const body = rows.filter((r, idx) => idx > 0 && !r.every((c) => /^:?-+:?$/.test(c)));
        out.push({ t: 'table', headers, rows: body }); continue;
      }
      const ul = line.match(/^[-·*]\s+(.*)/);
      if (ul) {
        const items: string[] = [];
        while (i < lines.length && /^[-·*]\s+/.test(lines[i])) items.push(lines[i++].replace(/^[-·*]\s+/, ''));
        out.push({ t: 'ul', items }); continue;
      }
      const ol = line.match(/^\d+[.、]\s+(.*)/);
      if (ol) {
        const items: string[] = [];
        while (i < lines.length && /^\d+[.、]\s+/.test(lines[i])) items.push(lines[i++].replace(/^\d+[.、]\s+/, ''));
        out.push({ t: 'ol', items }); continue;
      }
      out.push({ t: 'p', text: line }); i++;
    }
    return out;
  }, [text]);

  return (
    <div className="md">
      {blocks.map((b, i) => {
        if (b.t === 'h1') return <h1 key={i}>{inline(b.text)}</h1>;
        if (b.t === 'h2') return <h2 key={i}>{inline(b.text)}</h2>;
        if (b.t === 'h3') return <h3 key={i}>{inline(b.text)}</h3>;
        if (b.t === 'code') return <pre key={i}>{b.text}</pre>;
        if (b.t === 'ul') return <ul key={i}>{b.items.map((it, j) => <li key={j}>{inline(it)}</li>)}</ul>;
        if (b.t === 'ol') return <ol key={i}>{b.items.map((it, j) => <li key={j}>{inline(it)}</li>)}</ol>;
        if (b.t === 'table') return (
          <table key={i}>
            <thead><tr>{b.headers.map((h, j) => <th key={j}>{inline(h)}</th>)}</tr></thead>
            <tbody>{b.rows.map((r, j) => <tr key={j}>{r.map((c, k) => <td key={k}>{inline(c)}</td>)}</tr>)}</tbody>
          </table>
        );
        return <p key={i}>{inline(b.text)}</p>;
      })}
    </div>
  );
}

// ---------- 页头 ----------
export function PageHead({ eyebrow, title, desc, right }: any) {
  return (
    <div className="spread pop" style={{ alignItems: 'flex-end', flexWrap: 'wrap', marginBottom: 16 }}>
      <div style={{ minWidth: 0 }}>
        <div className="t-eyebrow">{eyebrow}</div>
        <h1 className="t-hero" style={{ margin: '4px 0 0' }}>{title}</h1>
        {desc && <p className="t-dim" style={{ margin: '6px 0 0', fontSize: 13.5, maxWidth: 620 }}>{desc}</p>}
      </div>
      {right}
    </div>
  );
}

// ---------- 股票搜索建议 ----------
export function useStockSuggest(query, market) {
  return useMemo(() => {
    const q = query.trim().toLowerCase();
    if (q.length < 2) return [];
    return window.MC_DATA.SEARCH_POOL
      .filter((s) => (market === 'all' || s.market === market) && (s.symbol.toLowerCase().includes(q) || s.name.toLowerCase().includes(q)))
      .slice(0, 6);
  }, [query, market]);
}

// ---------- 弹层 Modal（portal 到 body,确保悬浮全屏,不被 glass 卡的 backdrop-filter/overflow 裁剪）----------
export function Modal({ title, eyebrow, onClose, children, maxWidth = 560, right }: any) {
  useEffect(() => {
    const onKey = (e) => { if (e.key === 'Escape') onClose(); };
    window.addEventListener('keydown', onKey);
    document.body.style.overflow = 'hidden';
    return () => { window.removeEventListener('keydown', onKey); document.body.style.overflow = ''; };
  }, [onClose]);
  const node = (
    <div className="scrim" onClick={onClose}>
      <div className="modal glass" role="dialog" aria-modal="true" style={{ background: 'var(--glass-strong)', maxWidth }} onClick={(e) => e.stopPropagation()}>
        <div className="spread" style={{ position: 'sticky', top: 0, zIndex: 2, padding: '16px 20px', background: 'var(--glass-strong)', borderBottom: '1px solid var(--hairline-soft)', backdropFilter: 'blur(12px)', WebkitBackdropFilter: 'blur(12px)' }}>
          <div style={{ minWidth: 0 }}>
            {eyebrow && <div className="t-eyebrow">{eyebrow}</div>}
            <h2 className="t-title" style={{ margin: '2px 0 0', fontSize: 16.5 }}>{title}</h2>
          </div>
          <div className="row" style={{ gap: 8, flex: 'none' }}>
            {right}
            <button type="button" className="release-close" onClick={onClose} aria-label="关闭">×</button>
          </div>
        </div>
        <div style={{ padding: '18px 20px 22px' }}>{children}</div>
      </div>
    </div>
  );
  return createPortal(node, document.body);
}

// ---------- 线性图标(SF Symbol 风格,stroke currentColor) ----------
export function McIcon({ name, size = 17, style }: any) {
  const P = {
    pulse: 'M3 12h3.5l2-6 3 12 2-7H20',
    reviews: 'M8 4h8v3H8zM6 5H5a1 1 0 00-1 1v13a1 1 0 001 1h14a1 1 0 001-1V6a1 1 0 00-1-1h-1M8.5 13l2 2 4-4',
    reports: 'M7 3h7l4 4v13a1 1 0 01-1 1H7a1 1 0 01-1-1V4a1 1 0 011-1zM14 3v4h4M9.5 12.5h5M9.5 15.5h5',
    positions: 'M3 8a1 1 0 011-1h16a1 1 0 011 1v11a1 1 0 01-1 1H4a1 1 0 01-1-1zM8 7V5a2 2 0 012-2h4a2 2 0 012 2v2M3 12.5h18',
    chat: 'M5 4h14a1 1 0 011 1v9a1 1 0 01-1 1H10l-4 3.5V15H5a1 1 0 01-1-1V5a1 1 0 011-1z',
    health: 'M4 13h3l1.5-3 2.5 6 2-9 2 6h5',
    admin: 'M4 7h8M17 7h3M4 17h3M12 17h8M16 7a2 2 0 11-4 0 2 2 0 014 0zM10 17a2 2 0 11-4 0 2 2 0 014 0z',
    search: 'M11 18a7 7 0 100-14 7 7 0 000 14zM20 20l-3.6-3.6',
    tour: 'M12 21a9 9 0 100-18 9 9 0 000 18zM15.5 8.5l-2.2 4.8-4.8 2.2 2.2-4.8z',
    sun: 'M12 8a4 4 0 100 8 4 4 0 000-8zM12 2v2M12 20v2M4 12H2M22 12h-2M5.6 5.6L4.2 4.2M19.8 19.8l-1.4-1.4M18.4 5.6l1.4-1.4M4.2 19.8l1.4-1.4',
    moon: 'M20.5 14.5A8 8 0 019 3.5a8 8 0 1011.5 11z',
    decision: 'M4 8h6M14 8h6M4 16h10M18 16h2M12 8a2 2 0 11-4 0 2 2 0 014 0zM18 16a2 2 0 11-4 0 2 2 0 014 0z',
    portfolio: 'M12 3v9l7 3M12 3a9 9 0 109 9h-9',
    agents: 'M6 6h12a1 1 0 011 1v9a1 1 0 01-1 1H6a1 1 0 01-1-1V7a1 1 0 011-1zM9.5 11v1.5M14.5 11v1.5M12 3v3M9 20h6',
    data: 'M12 4c4 0 7 1.1 7 2.5S16 9 12 9 5 7.9 5 6.5 8 4 12 4zM5 6.5v11C5 18.9 8 20 12 20s7-1.1 7-2.5v-11M5 12c0 1.4 3 2.5 7 2.5s7-1.1 7-2.5',
    schedule: 'M5 5h14a1 1 0 011 1v13a1 1 0 01-1 1H5a1 1 0 01-1-1V6a1 1 0 011-1zM4 9.5h16M8.5 3v4M15.5 3v4',
    risk: 'M12 3l7 2.5v6.5c0 4.2-3 7-7 9-4-2-7-4.8-7-9V5.5z',
    memory: 'M7 3h10a1 1 0 011 1v17l-6-4-6 4V4a1 1 0 011-1z',
    llmcost: 'M9 4.5c2.8 0 5 1 5 2.2S11.8 9 9 9 4 8 4 6.7 6.2 4.5 9 4.5zM4 6.7v4c0 1.2 2.2 2.2 5 2.2M15 12c2.8 0 5 1 5 2.2s-2.2 2.3-5 2.3-5-1-5-2.3M10 14.2v4c0 1.2 2.2 2.3 5 2.3s5-1 5-2.3v-4',
    apikey: 'M14 7a4 4 0 100 8 4 4 0 000-8zM14 13.5L21 13.5M18 13.5V16M21 13.5V17',
    plus: 'M12 5v14M5 12h14',
    arrowLeft: 'M19 12H5M12 19l-7-7 7-7',
    refresh: 'M20.5 12a8.5 8.5 0 1 1-2.9-6.4M20.5 4.2v3.9h-3.9',
    external: 'M14 4h6v6M20 4l-9 9M18 13v6a1 1 0 0 1-1 1H5a1 1 0 0 1-1-1V7a1 1 0 0 1 1-1h6',
  };
  const d = P[name] || P.pulse;
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor"
      strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"
      style={{ flex: 'none', ...style }}>
      <path d={d}></path>
    </svg>
  );
}

// ---------- 数据刷新按钮(带旋转动效 + 演示同步) ----------
export function RefreshButton({ label = '刷新', busyLabel = '同步中…', toastMsg, onRefresh, onDone, className = 'btn btn-sm', title }: any) {
  const [busy, setBusy] = useState(false);
  async function run() {
    if (busy) return;
    setBusy(true);
    try {
      if (onRefresh) await onRefresh();
      else await new Promise((resolve) => setTimeout(resolve, 850));
      if (toastMsg) toast(toastMsg);
      if (onDone) onDone();
    } catch (error) {
      toast(error instanceof Error ? `检查失败：${error.message}` : '检查失败', 'warn');
    } finally {
      setBusy(false);
    }
  }
  return (
    <button type="button" className={className} disabled={busy} onClick={run} title={title || label}>
      <McIcon name="refresh" size={14} style={{ animation: busy ? 'mc-spin 0.7s linear infinite' : 'none' }} />
      {busy ? busyLabel : label}
    </button>
  );
}

// ---------- 池排序:默认 / 按分数 / 按当日涨跌(点同一项切换升降序) ----------
export function dailyChangePct(symbol) {
  const px = window.MC_DATA.PRICES[symbol];
  if (!px || px.length < 2) return null;
  const a = px[px.length - 1].close, b = px[px.length - 2].close;
  return ((a - b) / b) * 100;
}

export function useSortCtl() {
  const [sort, setSort] = useState({ key: 'default', dir: 'desc' });
  const onSort = useCallback((key) => {
    setSort((s) => {
      if (key === 'default') return { key: 'default', dir: 'desc' };
      if (s.key === key) return { key, dir: s.dir === 'desc' ? 'asc' : 'desc' };
      return { key, dir: 'desc' };
    });
  }, []);
  return [sort, onSort];
}

export function SortSeg({ sort, onSort }: any) {
  const arrow = (k) => (sort.key === k ? (sort.dir === 'desc' ? ' ↓' : ' ↑') : '');
  return (
    <Seg value={sort.key} onChange={onSort}
      options={[['default', '默认'], ['score', `分数${arrow('score')}`], ['change', `涨跌${arrow('change')}`]]} />
  );
}

export function applyPoolSort(items, sort) {
  if (!sort || sort.key === 'default') return items;
  const val = (w) => (sort.key === 'score'
    ? (w.latest_signal ? w.latest_signal.composite_score : null)
    : dailyChangePct(w.symbol));
  const mul = sort.dir === 'desc' ? -1 : 1;
  return items.slice().sort((a, b) => {
    const va = val(a), vb = val(b);
    if (va == null && vb == null) return 0;
    if (va == null) return 1; // 缺数据沉底,不受方向影响
    if (vb == null) return -1;
    return (va - vb) * mul;
  });
}

// ---------- 股票池筛选:筛选按钮 + 可收起的筛选条(搜索/市场/信号/长期标签) ----------
export function useStockPoolFilter(items) {
  const [open, setOpen] = useState(false);
  const [q, setQ] = useState('');
  const [mkt, setMkt] = useState('all');
  const [rec, setRec] = useState('all');
  const [lt, setLt] = useState('all');
  const recs = useMemo<any[]>(() => {
    const rs = Array.from(new Set(items.filter((w) => w.latest_signal).map((w) => w.latest_signal.recommendation))).sort();
    if (items.some((w) => !w.latest_signal)) rs.push('无信号');
    return rs;
  }, [items]);
  const lts = useMemo<any[]>(() => Array.from(new Set(items.filter((w) => w.long_term_label).map((w) => w.long_term_label.label))).sort(), [items]);
  const ql = q.trim().toLowerCase();
  const filtered = items.filter((w) =>
    (mkt === 'all' || w.market === mkt)
    && (rec === 'all' || (rec === '无信号' ? !w.latest_signal : (w.latest_signal && w.latest_signal.recommendation === rec)))
    && (lt === 'all' || (w.long_term_label && w.long_term_label.label === lt))
    && (!ql || w.symbol.toLowerCase().includes(ql) || w.name.toLowerCase().includes(ql) || (w.industry || '').toLowerCase().includes(ql)));
  const active = !!ql || mkt !== 'all' || rec !== 'all' || lt !== 'all';
  const clear = () => { setQ(''); setMkt('all'); setRec('all'); setLt('all'); };
  const button = (
    <button className={`btn btn-sm ${active ? 'btn-primary' : ''}`} onClick={() => setOpen(!open)}>
      筛选{active ? ` · ${filtered.length}` : ''} {open ? '▴' : '▾'}
    </button>
  );
  const bar = open ? (
    <div className="row" style={{ flexWrap: 'wrap', gap: 8, marginBottom: 12 }}>
      <input className="field" style={{ flex: 1, minWidth: 150 }} value={q} onChange={(e) => setQ(e.target.value)} placeholder="搜索代码、名称、行业" />
      <select className="field" style={{ width: 100 }} value={mkt} onChange={(e) => setMkt(e.target.value)}>
        <option value="all">全部市场</option><option value="CN">A股</option><option value="HK">港股</option><option value="US">美股</option>
      </select>
      <select className="field" style={{ width: 116 }} value={rec} onChange={(e) => setRec(e.target.value)}>
        <option value="all">全部信号</option>
        {recs.map((r) => <option key={r} value={r}>{r}</option>)}
      </select>
      <select className="field" style={{ width: 124 }} value={lt} onChange={(e) => setLt(e.target.value)}>
        <option value="all">全部长期标签</option>
        {lts.map((l) => <option key={l} value={l}>{l}</option>)}
      </select>
      {active && <button className="btn btn-sm btn-quiet" onClick={clear}>清除</button>}
    </div>
  ) : null;
  return { filtered, button, bar, active };
}

// ---------- 信息池外壳:默认收起 + 展开按钮 + 卡片/列表双视图 ----------
// items 由宿主先筛选好;PoolShell 只负责截断、展开和视图切换。
export function PoolShell({ items, defaultCount = 8, renderCard, renderRow, cardMin = 218, unit = '条', empty = null }: any) {
  const [expanded, setExpanded] = useState(false);
  const [view, setView] = useState('cards');
  if (!items.length) return empty || <div className="empty">暂无内容。</div>;
  const shown = expanded ? items : items.slice(0, defaultCount);
  const overflow = items.length > defaultCount;
  return (
    <div>
      <div className="spread" style={{ marginBottom: 10, gap: 8 }}>
        <span className="t-num t-faint" style={{ fontSize: 12 }}>显示 {shown.length} / {items.length} {unit}</span>
        {renderRow && <Seg value={view} options={[['cards', '卡片'], ['rows', '列表']]} onChange={setView} />}
      </div>
      {view === 'cards' || !renderRow ? (
        <div className="grid" style={{ gridTemplateColumns: `repeat(auto-fill, minmax(${cardMin}px, 1fr))`, gap: 10 }}>
          {shown.map(renderCard)}
        </div>
      ) : (
        <div className="glass-inset" style={{ padding: '2px 0' }}>
          {shown.map((it, i) => (
            <div key={i} style={{ borderBottom: i < shown.length - 1 ? '1px solid var(--hairline-soft)' : 'none' }}>
              {renderRow(it)}
            </div>
          ))}
        </div>
      )}
      {overflow && (
        <button className="btn btn-sm" style={{ width: '100%', marginTop: 10 }} onClick={() => setExpanded(!expanded)}>
          {expanded ? '收起' : `展开全部 ${items.length} ${unit} ↓`}
        </button>
      )}
    </div>
  );
}

Object.assign(window, {
  MCStore, useStore, toast, useRoute, navigate, fmt, CCY, MKT,
  recTone, ltTone, pnlClass,
  Card, Metric, Badge, Toggle, Seg, ScoreBar, Spark, PriceChart, Markdown, PageHead, Modal, McIcon, RefreshButton,
  PoolShell, SortSeg, useSortCtl, applyPoolSort, dailyChangePct, useStockPoolFilter,
  useStockSuggest, mcInline: inline,
});
