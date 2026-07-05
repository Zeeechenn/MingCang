// ============================================================
// 主应用 — 导航壳 / 路由 / 主题 / Tweaks
// 模块间依赖已走真正的 import/export(TS 迁移后),不再依赖求值顺序;
// boot/data 的 window 挂载仅为运行时兼容保留(见 global.d.ts)。
// ============================================================
import React from 'react';
import { createRoot } from 'react-dom/client';
import { FirstRunWizard, Tour } from './onboarding';
import { AdminPage } from './page-admin';
import { ChatPage } from './page-chat';
import { DailyPage } from './page-daily';
import { HealthPage } from './page-health';
import { HomePage } from './page-home';
import { MemoryEvolutionPage } from './page-memory-evolution';
import { PositionsPage } from './page-positions';
import { PulsePage } from './page-pulse';
import { ReportsPage } from './page-reports';
import { StockPage, StocksPage } from './page-stock';
import { MKT, McIcon, navigate, useRoute, useStockSuggest, useStore } from './shared';
import { TweakColor, TweakRadio, TweakSection, TweakSlider, TweakToggle, TweaksPanel, useTweaks } from './tweaks-panel';
import './boot';
import './glass.css';
import './data';
import './shared';
import './tweaks-panel';
import './onboarding';
import './page-reports';
import './page-pulse';
import './page-stock';
import './page-positions';
import './page-home';
import './page-chat';
import './page-daily';
import './page-health';
import './page-admin';
import './page-memory-evolution';
import { startLive } from './live';

const { useState: useMState, useEffect: useMEffect } = React;

const THEME_KEY = 'mc_proto_theme_v1';

const NAV = [
  ['/', '明仓终端', 'chat'],
  ['/daily', '日常', 'schedule'],
  ['/pulse', '今日裁决', 'pulse'],
  ['/stocks', '个股案卷', 'search'],
  ['/reports', '复盘案卷', 'reports'],
  ['/chat', '研究副驾驶', 'chat'],
  ['/positions', '持仓纪律', 'positions'],
  ['/memory-evolution', '记忆进化', 'memory'],
  ['/health', '来源健康', 'health'],
  ['/admin', '治理台', 'admin'],
];

const TWEAK_DEFAULTS = /*EDITMODE-BEGIN*/{
  "accent": "#0071e3",
  "glassBlur": 28,
  "colorConvention": "A股红涨",
  "reduceTransparency": false
}/*EDITMODE-END*/;

const ACCENT_DARK = { '#0071e3': '#0a84ff', '#7a5ae0': '#9b7bff', '#1f8a5b': '#34c77b' };

function applyTweaks(t, theme) {
  const root = document.body;
  const accent = theme === 'dark' ? (ACCENT_DARK[t.accent] || t.accent) : t.accent;
  root.style.setProperty('--accent', accent);
  root.style.setProperty('--accent-ink', accent);
  root.style.setProperty('--accent-soft', accent + '1f');
  root.style.setProperty('--glass-blur', `${t.glassBlur}px`);
  const intl = t.colorConvention !== 'A股红涨';
  const red = theme === 'dark' ? '#ff6961' : '#d70015';
  const green = theme === 'dark' ? '#4cd964' : '#1f8a3b';
  const redSoft = 'rgba(255,69,58,0.14)', greenSoft = 'rgba(48,209,88,0.14)';
  root.style.setProperty('--up', intl ? green : red);
  root.style.setProperty('--up-soft', intl ? greenSoft : redSoft);
  root.style.setProperty('--down', intl ? red : green);
  root.style.setProperty('--down-soft', intl ? redSoft : greenSoft);
  if (t.reduceTransparency) {
    root.style.setProperty('--glass', theme === 'dark' ? 'rgba(32,35,45,0.97)' : 'rgba(255,255,255,0.96)');
  } else {
    root.style.removeProperty('--glass');
  }
}

// 数据通道指示:live = 已连接后端,demo = 示例快照,offline = 后端断开
function LiveBadge() {
  const [state] = useStore();
  const mode = state.live || 'demo';
  const live = mode === 'live';
  const offline = mode === 'offline';
  const label = live ? '本地后端' : (offline ? '后端断开' : '示例快照');
  const title = live
    ? '已连接本地后端:数据来自 /api'
    : (offline ? '后端连接中断:保留当前页面数据' : '后端未连接:当前展示示例快照');
  return (
    <span className="nav-status" title={title}>
      <span className="pulse-dot" style={live ? undefined : { background: 'var(--warn)' }}></span>
      <span className="nav-local-label">{label}</span>
    </span>
  );
}

function Toast() {
  const [state] = useStore();
  if (!state.toast) return null;
  return (
    <div className="toast glass" style={{ background: 'var(--glass-strong)' }}>
      {state.toast.msg}
    </div>
  );
}

// 全局个股搜索 — 跳转任意个股
function GlobalSearch() {
  const [q, setQ] = useMState('');
  const [open, setOpen] = useMState(false);
  const sugg = useStockSuggest(q, 'all');
  function go(sym) { navigate(`/stock/${sym}`); setQ(''); setOpen(false); }
  function onKey(e) {
    if (e.key === 'Enter') {
      const hit = sugg[0] || window.MC_DATA.SEARCH_POOL.find((s) => s.symbol === q.trim());
      if (hit) go(hit.symbol);
      else if (/^[A-Za-z0-9]{4,6}$/.test(q.trim())) go(q.trim().toUpperCase());
    } else if (e.key === 'Escape') { setQ(''); setOpen(false); e.target.blur(); }
  }
  return (
    <div className="nav-search" data-open={open ? '1' : undefined}>
      <McIcon name="search" size={15} style={{ color: 'var(--ink-3)' }} />
      <input value={q} onChange={(e) => { setQ(e.target.value); setOpen(true); }} onFocus={() => setOpen(true)}
        onBlur={() => setTimeout(() => setOpen(false), 160)} onKeyDown={onKey}
        placeholder="搜索个股 代码 / 名称" aria-label="搜索个股" />
      {open && q.trim().length >= 1 && (
        <div className="nav-search-pop glass" style={{ background: 'var(--glass-strong)' }}>
          {sugg.length > 0 ? sugg.map((s) => (
            <button key={s.symbol} type="button" className="nav-search-item" onMouseDown={() => go(s.symbol)}>
              <span style={{ fontWeight: 600 }}>{s.name}</span>
              <span className="t-num t-faint" style={{ fontSize: 12 }}>{s.symbol} · {MKT[s.market]}</span>
            </button>
          )) : (
            <div className="t-faint" style={{ padding: '10px 12px', fontSize: 12.5 }}>
              {q.trim().length < 2 ? '继续输入代码或名称…' : '未找到。回车直接打开该代码。'}
            </div>
          )}
        </div>
      )}
    </div>
  );
}

function App() {
  const route = useRoute();
  const [theme, setTheme] = useMState(() => {
    try { return localStorage.getItem(THEME_KEY) || 'light'; } catch (e) { return 'light'; }
  });
  const [wizardOpen, setWizardOpen] = useMState(() => {
    try { return !localStorage.getItem(window.MC_WIZ_KEY); } catch (e) { return true; }
  });
  const [tourOpen, setTourOpen] = useMState(false);
  const [tweaks, setTweak] = useTweaks(TWEAK_DEFAULTS);

  useMEffect(() => {
    const t = setTimeout(() => { document.documentElement.classList.add('anims-done'); document.body.classList.add('anims-done'); }, 1000);
    return () => clearTimeout(t);
  }, []);

  useMEffect(() => {
    document.documentElement.dataset.theme = theme;
    document.body.dataset.theme = theme;
    try { localStorage.setItem(THEME_KEY, theme); } catch (e) { /* ignore */ }
    applyTweaks(tweaks, theme);
  }, [theme, tweaks]);

  let page;
  if (route.page === 'stock') page = <StockPage symbol={route.symbol} key={route.symbol} />;
  else if (route.page === 'home') page = <HomePage />;
  else if (route.page === 'stocks') page = <StocksPage />;
  else if (route.page === 'reports') page = <ReportsPage />;
  else if (route.page === 'daily') page = <DailyPage />;
  else if (route.page === 'memory' || route.page === 'reviews') page = <ReportsPage />;
  else if (route.page === 'positions') page = <PositionsPage />;
  else if (route.page === 'memory-evolution') page = <MemoryEvolutionPage />;
  else if (route.page === 'chat') page = <ChatPage />;
  else if (route.page === 'health') page = <HealthPage />;
  else if (route.page === 'admin') page = <AdminPage />;
  else if (route.page === 'pulse') page = <PulsePage />;
  else page = <HomePage />;

  const activeNav = route.page === 'home' ? '/' : route.page === 'stock' ? '/stocks' : (NAV.find(([to]) => to === `/${route.page}`) || ['/'])[0];

  return (
    <div>
      <div className="mc-backdrop"></div>
      <nav className="mc-nav glass" data-tour="nav" data-screen-label="导航">
        <a
          className="nav-brand"
          role="button"
          tabIndex={0}
          onClick={() => navigate('/')}
          onKeyDown={(e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); navigate('/'); } }}
        >
          <div className="nav-logo">仓</div>
          <span className="nav-wordmark">明仓</span>
        </a>
        <div className="navlinks">
          {NAV.map(([to, label, icon]) => (
            <a
              key={to}
              className={`navlink ${activeNav === to ? 'on' : ''}`}
              role="button"
              tabIndex={0}
              onClick={() => navigate(to)}
              onKeyDown={(e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); navigate(to); } }}
            >
              <McIcon name={icon} size={16} /><span>{label}</span>
            </a>
          ))}
        </div>
        <div className="nav-right">
          <LiveBadge />
          <button className="nav-icon-btn" title="功能导览" aria-label="功能导览" onClick={() => setTourOpen(true)}>
            <McIcon name="tour" size={17} />
          </button>
          <button className="nav-icon-btn" title="切换浅色 / 深色" aria-label="切换外观" onClick={() => setTheme(theme === 'dark' ? 'light' : 'dark')}>
            <McIcon name={theme === 'dark' ? 'sun' : 'moon'} size={17} />
          </button>
        </div>
      </nav>

      <main className="mc-main" data-screen-label={`页面:${route.page}`}>
        {page}
      </main>

      <footer style={{ textAlign: 'center', padding: '0 20px 36px', fontSize: 11.5, color: 'var(--ink-3)' }}>
        明仓 MingCang · 本地优先的 A股研究决策系统 · 证据门控 / 复盘案卷 / 本地记忆 · 输出为研究记录，不构成投资建议
      </footer>

      {wizardOpen && <FirstRunWizard onDone={() => setWizardOpen(false)} onStartTour={() => setTourOpen(true)} />}
      {tourOpen && <Tour onClose={() => setTourOpen(false)} />}
      <Toast />

      <TweaksPanel>
        <TweakSection label="外观" />
        <TweakColor label="强调色" value={tweaks.accent} options={['#0071e3', '#7a5ae0', '#1f8a5b']} onChange={(v) => setTweak('accent', v)} />
        <TweakSlider label="玻璃模糊度" value={tweaks.glassBlur} min={8} max={48} unit="px" onChange={(v) => setTweak('glassBlur', v)} />
        <TweakToggle label="降低透明度" value={tweaks.reduceTransparency} onChange={(v) => setTweak('reduceTransparency', v)} />
        <TweakSection label="行情" />
        <TweakRadio label="涨跌配色" value={tweaks.colorConvention} options={['A股红涨', '国际绿涨']} onChange={(v) => setTweak('colorConvention', v)} />
      </TweaksPanel>
    </div>
  );
}

createRoot(document.getElementById('root')!).render(<App />);
startLive();
