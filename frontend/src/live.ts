// ============================================================
// 后端接入层 — 把 /api 真实数据归一化成 MC_DATA 形状
// 原则:
//  1. 启动时并行预取核心数据,成功则覆写 MC_DATA + MCStore(live 模式)
//  2. 个股详情数据(K线/新闻/证据/归因/案卷)按需懒取,写回 MC_DATA 后 poke 重渲染
//  3. 后端不可达时静默保持示例快照,导航栏显示「示例快照」
//  4. 写操作统一走 window.MC_API,live 模式调后端,demo 模式由调用方落回本地示例行为
// ============================================================
import * as api from './api';

const HEALTH_POLL_MS = Number(import.meta.env.VITE_HEALTH_POLL_MS) || 30000;

let live = false;
let atlasOn = false; // 后端 atlas_enabled 开启时为 true(论题/记忆候选/case-view 账本可用)
let healthTimer: ReturnType<typeof setInterval> | null = null;
const fetchedSymbols = new Set();
const reviewContentLoaded = new Set();

const D = () => window.MC_DATA;
const store = () => window.MCStore;
const poke = () => store().set({});

export function isLive() { return live; }

function stopHealthMonitor() {
  if (healthTimer) clearInterval(healthTimer);
  healthTimer = null;
}

function startHealthMonitor() {
  stopHealthMonitor();
  healthTimer = setInterval(async () => {
    if (!live) return;
    try {
      await api.getSystemHealth();
      store().set({ live: 'live' });
    } catch (e) {
      live = false;
      atlasOn = false;
      stopHealthMonitor();
      store().set({ live: 'offline' });
    }
  }, HEALTH_POLL_MS);
}

// ---------- 归一化 ----------
function normSignal(s) {
  if (!s) return null;
  const arb = s.llm_arbitration || {};
  return {
    ...s,
    date: s.date ? String(s.date).slice(0, 10) : s.date,
    quant_score: s.quant_score ?? 0,
    technical_score: s.technical_score ?? 0,
    sentiment_score: s.sentiment_score ?? 0,
    llm_arbitration: {
      bull_points: arb.bull_points || [],
      bear_points: arb.bear_points || [],
      rationale: arb.rationale || '',
      action_bias: arb.action_bias || '',
    },
  };
}

function normWatchItem(w) {
  return { ...w, industry: w.industry || '—', latest_signal: normSignal(w.latest_signal), long_term_label: w.long_term_label || null };
}

function normPosition(p) {
  return { ...p, entry_date: p.entry_date || (p.opened_at ? String(p.opened_at).slice(0, 10) : '') };
}

function normPrices(bars) {
  return (bars || []).map((b) => ({
    date: b.time || b.date, open: b.open, high: b.high, low: b.low, close: b.close, volume: b.volume ?? 0,
  }));
}

function normNews(rows) {
  return (rows || []).map((n) => ({
    title: n.title, source: n.source || '—', url: n.url,
    published_at: n.published_at ? String(n.published_at).replace('T', ' ').slice(0, 16) : '',
    sentiment: n.sentiment ?? n.sentiment_score ?? null,
    audit: n.audit || 'pass',
  }));
}

function normEvidence(runs) {
  return (runs || []).map((r, i) => {
    const risk = r.risk_decision || {};
    const finalAct = r.final_action || {};
    const status = risk.blocked ? 'blocked' : (risk.downgraded || (r.notes || '').includes('warning') ? 'warning' : 'pass');
    const score = r.composite_score != null ? `综合分 ${r.composite_score > 0 ? '+' : ''}${Number(r.composite_score).toFixed(1)}` : '';
    return {
      id: r.run_id || `run-${i}`,
      kind: r.run_type || 'decision_run',
      date: r.as_of || (r.created_at ? String(r.created_at).slice(0, 10) : ''),
      title: `决策运行 ${r.run_id || ''}`.trim(),
      detail: [r.recommendation, score, finalAct.position ? `仓位 ${finalAct.position}` : '', r.notes].filter(Boolean).join(' · ') || '决策运行记录',
      status,
    };
  });
}

function normEval(e) {
  if (!e) return null;
  const recs = e.records || [];
  const rets = recs.filter((r) => r.next_day_return != null);
  const gains = rets.filter((r) => r.next_day_return > 0).map((r) => r.next_day_return);
  const losses = rets.filter((r) => r.next_day_return < 0).map((r) => r.next_day_return);
  const avg = (xs) => (xs.length ? xs.reduce((a, b) => a + b, 0) / xs.length : 0);
  const bestR = rets.length ? rets.reduce((a, b) => (a.next_day_return > b.next_day_return ? a : b)) : null;
  const worstR = rets.length ? rets.reduce((a, b) => (a.next_day_return < b.next_day_return ? a : b)) : null;
  const fmtR = (r) => (r ? `${r.next_day_return > 0 ? '+' : ''}${r.next_day_return.toFixed(1)}% (${String(r.date).slice(5)} ${r.recommendation})` : '—');
  const hit = recs.filter((r) => r.correct === true).length;
  return {
    days: e.days, total: e.total_signals ?? recs.length, hit,
    hit_rate: e.win_rate ?? (rets.length ? +(100 * hit / rets.length).toFixed(1) : 0),
    avg_gain: +avg(gains).toFixed(2), avg_loss: +avg(losses).toFixed(2),
    best: fmtR(bestR), worst: fmtR(worstR),
    note: `近 ${e.days} 日共 ${e.total_signals ?? recs.length} 条信号，可评估 ${e.evaluated ?? rets.length} 条。`,
  };
}

// ---------- 运行时配置双向映射 ----------
// 后端比例字段是 0~1 小数(weight_technical 0.6 / director_min_confidence 0.25 / max_position_per_stock 0.15),
// UI 滑条按 0~100 百分比设计;字段名也不同(regime_filter_enabled vs regime_filter)。
const pct = (v, fallback = 0) => (v == null ? fallback : Math.round(Number(v) * 100));

function runtimeFromBackend(rt) {
  const base = D().RUNTIME;
  const dd = rt.data_draft || {};
  const sch = rt.schedule || {};
  return {
    ...base,
    profile: rt.active_profile || rt.profile || base.profile,
    entry_threshold: rt.entry_threshold ?? base.entry_threshold,
    director_min_confidence: pct(rt.director_min_confidence, base.director_min_confidence),
    weights: rt.weights ? {
      quant: pct(rt.weights.quant), technical: pct(rt.weights.technical), sentiment: pct(rt.weights.sentiment),
    } : base.weights,
    regime_filter: rt.regime_filter_enabled ?? base.regime_filter,
    adx_filter: rt.adx_filter_enabled ?? base.adx_filter,
    multi_agent: rt.multi_agent_enabled ?? base.multi_agent,
    risk_manager: rt.risk_manager_enabled ?? base.risk_manager,
    long_term_team: rt.long_term_team_enabled ?? base.long_term_team,
    long_term_constraints: rt.long_term_constraints_enabled ?? base.long_term_constraints,
    trailing_stop: rt.trailing_stop_enabled ?? base.trailing_stop,
    max_stock_pct: pct(rt.max_position_per_stock, base.max_stock_pct),
    max_sector_pct: pct(rt.max_position_per_sector, base.max_sector_pct),
    max_total_pct: pct(rt.max_total_equity_pct, base.max_total_pct),
    financial_years: dd.financial_backfill_years ?? base.financial_years,
    tavily_threshold: dd.tavily_supplement_threshold ?? base.tavily_threshold,
    anspire_days: dd.anspire_news_days ?? base.anspire_days,
    anspire_max_results: dd.anspire_news_max_results ?? base.anspire_max_results,
    anspire_max_add: dd.anspire_news_max_add ?? base.anspire_max_add,
    anspire_min_score: dd.anspire_news_min_score ?? base.anspire_min_score,
    daily_review_time: sch.daily_review_time || base.daily_review_time,
    longterm_monday_time: sch.longterm_monday_time || base.longterm_monday_time,
    longterm_friday_time: sch.longterm_friday_time || base.longterm_friday_time,
    kill_switch: rt.kill_switch_active ?? base.kill_switch,
  };
}

function runtimeToBackend(cfg) {
  const frac = (v) => Number(v) / 100;
  const out: any = {
    new_framework_entry_threshold: Number(cfg.entry_threshold),
    weight_quant: frac(cfg.weights.quant),
    weight_technical: frac(cfg.weights.technical),
    weight_sentiment: frac(cfg.weights.sentiment),
    director_min_confidence: frac(cfg.director_min_confidence),
    regime_filter_enabled: !!cfg.regime_filter,
    adx_filter_enabled: !!cfg.adx_filter,
    multi_agent_enabled: !!cfg.multi_agent,
    risk_manager_enabled: !!cfg.risk_manager,
    long_term_team_enabled: !!cfg.long_term_team,
    long_term_constraints_enabled: !!cfg.long_term_constraints,
    trailing_stop_enabled: !!cfg.trailing_stop,
    max_position_per_stock: frac(cfg.max_stock_pct),
    max_position_per_sector: frac(cfg.max_sector_pct),
    max_total_equity_pct: frac(cfg.max_total_pct),
    financial_backfill_years: Number(cfg.financial_years),
    tavily_supplement_threshold: Number(cfg.tavily_threshold),
    anspire_news_days: Number(cfg.anspire_days),
    anspire_news_max_results: Number(cfg.anspire_max_results),
    anspire_news_max_add: Number(cfg.anspire_max_add),
    anspire_news_min_score: Number(cfg.anspire_min_score),
    schedule_daily_review_time: cfg.daily_review_time,
    schedule_longterm_monday_time: cfg.longterm_monday_time,
    schedule_longterm_friday_time: cfg.longterm_friday_time,
  };
  // profile 白名单只接受后端认识的取值;demo 的 legacy 不下发
  if (['auto', 'new_framework', 'test1'].includes(cfg.profile)) out.signal_profile = cfg.profile;
  return out;
}

function normReview(r) {
  const payload = r.payload || {};
  return {
    id: r.id, kind: r.kind, as_of: r.as_of,
    summary: r.summary || '',
    metrics: payload.metrics || [],
    highlights: payload.highlights || [],
    content: r.content || '',
    status: r.status, path: r.path,
  };
}

function normMemoryItem(r, i) {
  return {
    id: r.id != null ? String(r.id) : `mem-${i}`,
    scope: r.scope || 'global',
    category: r.category || '(未分类)',
    trust: r.trust || r.status || 'trusted',
    text: r.value || r.text || r.key || '',
    key: r.key,
    date: (r.updated_at || r.created_at || '').slice(0, 10),
  };
}

function normDossier(d) {
  if (!d) return null;
  const official = d.official_action || {};
  const conflicts = (d.conflicts || []).map((c) => ({ severity: c.severity || 'medium', summary: c.summary || c.detail || JSON.stringify(c) }));
  const rs = d.research_state || {};
  return {
    out: {
      final_position: official.position || official.final_position || '—',
      trader_position: official.trader_position || '—',
      constrained: official.constrained || (conflicts.length ? '存在约束/冲突' : '无约束'),
      constraint_count: official.constraint_count ?? 0,
      conflict_count: conflicts.length,
      conflicts,
    },
    research: rs,
    evidence: normEvidence(d.evidence || []),
    longTerm: d.long_term_label || null,
    signal: normSignal(d.latest_signal),
  };
}

const CHECK_LABEL = {
  price_coverage_ok: '价格覆盖', two_year_price_coverage_ok: '两年价格覆盖',
  financial_coverage_ok: '财务数据完整性', fresh_news_ok: '新闻新鲜度',
};

function normCoverage(c) {
  if (!c) return null;
  const checks: Record<string, boolean> = {};
  Object.entries(c.checks || {}).forEach(([k, v]: [string, any]) => {
    checks[CHECK_LABEL[k] || k] = typeof v === 'boolean' ? v : !!(v && v.ok !== false && v.pass !== false);
  });
  const allPass = Object.values(checks).every(Boolean);
  // 后端形状: provider_fallback_chains.chains_by_market[市场].daily = [{name,...}]
  // 页面期望: provider_chains[市场] = ['provider1', 'provider2', ...]
  const byMarket = (c.provider_fallback_chains && c.provider_fallback_chains.chains_by_market) || {};
  const provider_chains = { ...D().COVERAGE.provider_chains };
  ['CN', 'HK', 'US'].forEach((m) => {
    const daily = byMarket[m] && (byMarket[m].daily || byMarket[m].daily_price);
    if (Array.isArray(daily) && daily.length) provider_chains[m] = daily.map((p) => p.name || String(p));
  });
  return {
    status: allPass ? 'pass' : 'warning',
    provider_chains,
    policies: D().COVERAGE.policies,
    max_lag_days: D().COVERAGE.max_lag_days,
    checks: Object.keys(checks).length ? checks : D().COVERAGE.checks,
    warnings: (c.warnings || []).map((w) => ({ code: w.code || w.kind || 'WARN', message: w.message || w.detail || JSON.stringify(w) })),
    stocks: (c.stocks || []).map((s) => ({
      symbol: s.symbol, name: s.name || s.symbol, market: s.market || 'CN',
      latest_price_date: s.latest_price_date || '—',
      status: s.latest_price_date ? 'ok' : 'warning',
    })),
  };
}

// ---------- ATLAS 账本归一化 ----------
function stockName(symbol) {
  const w = D().WATCHLIST.find((x) => x.symbol === symbol);
  return (w && w.name) || symbol;
}

function normForwardThesis(t) {
  const stmt = t.statement || '';
  return {
    id: t.id, symbol: t.symbol || '—', name: t.symbol ? stockName(t.symbol) : '—',
    title: stmt.length > 24 ? `${stmt.slice(0, 24)}…` : (stmt || `论题 #${t.id}`),
    source_type: '论题账本', source_name: t.thesis_id ? `thesis#${t.thesis_id}` : 'ForwardThesis',
    as_of: (t.created_at || '').slice(0, 10), status: t.status || 'draft',
    review_cadence: t.review_cadence_days ? `每 ${t.review_cadence_days} 天` : '—',
    next_review: t.next_review_date || '—',
    summary: stmt,
    follow_metrics: t.follow_up_metrics || [],
    kill_conditions: t.invalidation_conditions || [],
    confidence_band: t.confidence_low != null ? `${t.confidence_low} ~ ${t.confidence_high}` : null,
  };
}

function normCandidate(c) {
  return {
    id: c.id, symbol: c.symbol, title: c.summary,
    source: c.source_ref || (c.review_case_id ? `review_case#${c.review_case_id}` : 'research'),
    trust: c.source_trust || 'pending',
    evidence: c.note || `importance ${c.importance} · confidence ${c.confidence}`,
    action: c.memory_type ? `建议写入 ${c.memory_type}` : '等待人工判定',
  };
}

async function refreshCandidates() {
  const res = await api.getMemoryCandidates();
  const items = (res.items || []).filter((c) => !c.promoted_at && !c.rejected_at).map(normCandidate);
  const MC = D().MEMORY_CENTER;
  D().MEMORY_CENTER = {
    ...MC,
    overview: {
      ...MC.overview,
      total: D().MEMORY.overview.total,
      trusted: D().MEMORY.overview.trusted,
      pending: items.length,
      refuted: (res.items || []).filter((c) => c.rejected_at).length,
    },
    queue: items,
    audit: [], // live 下不展示演示审计行
  };
  poke();
}

// ---------- 启动预取 ----------
export async function startLive() {
  let watchlist;
  try {
    watchlist = await api.getWatchlist();
  } catch (e) {
    live = false;
    atlasOn = false;
    stopHealthMonitor();
    store().set({ live: 'demo' });
    return; // 后端不可达,保持 demo
  }
  live = true;

  const results = await Promise.allSettled([
    api.getPositions('open'),
    api.getPositions('closed'),
    api.getReviews(),
    api.getRuntimeConfig(),
    api.getSystemStatus(),
    api.getSystemHealth(),
    api.getLLMUsage(7),
    api.getMemoryOverview(),
    api.getMemoryList({ limit: 200 }),
    Promise.resolve(null), // 审计日志是 FTS 搜索接口(q 必填),没有"全部列表"形式,live 下不预取
    api.getDataCoverage(),
    api.getChatSessions(),
  ]);
  const [posOpen, posClosed, reviews, runtime, sysStatus, sysHealth, llmUsage, memOverview, memList, memAudit, coverage, sessions] =
    results.map((r) => (r.status === 'fulfilled' ? r.value : null));

  const Dd = D();

  // 自选池 + 搜索池
  const wl = (watchlist || []).map(normWatchItem);
  Dd.WATCHLIST = wl;
  Dd.SEARCH_POOL = wl.map((w) => ({ symbol: w.symbol, name: w.name, market: w.market }));
  if (wl.length && wl[0].latest_signal?.date) Dd.SIG_DATE = wl[0].latest_signal.date;

  // 持仓
  const positions = [...(posOpen || []), ...(posClosed || [])].map(normPosition);

  // 复盘(取最近 8 条详情拿正文)
  let reviewItems = (Array.isArray(reviews) ? reviews : []).map(normReview);
  const detail = await Promise.allSettled(reviewItems.slice(0, 8).map((r) => api.getReview(r.id)));
  detail.forEach((res, i) => {
    if (res.status === 'fulfilled' && res.value) {
      reviewItems[i] = normReview(res.value);
      reviewContentLoaded.add(reviewItems[i].id);
    }
  });
  if (reviewItems.length) Dd.REVIEWS = reviewItems;

  // 配置 / 系统
  const rt = runtime ? runtimeFromBackend(runtime) : Dd.RUNTIME;
  Dd.RUNTIME = rt;
  if (llmUsage) {
    Dd.LLM_USAGE = {
      days: llmUsage.days ?? 7,
      total_cny: llmUsage.total_cny ?? llmUsage.total_cost_cny ?? 0,
      total_calls: llmUsage.total_calls ?? 0,
      buckets: llmUsage.buckets || Dd.LLM_USAGE.buckets,
      daily: llmUsage.daily || Dd.LLM_USAGE.daily,
    };
  }
  if (sysStatus || sysHealth) {
    const st = sysStatus || {};
    const hl = sysHealth || {};
    Dd.SYSTEM = {
      ...Dd.SYSTEM,
      version: st.version || Dd.SYSTEM.version,
      market_overview: st.market_overview || Dd.SYSTEM.market_overview,
      health: {
        db: hl.db ?? true,
        agent_mode: st.ai_provider || hl.agent_mode || rt.llm_provider || '—',
        watchlist: wl.length,
        positions: (posOpen || []).length,
        memory: memOverview ? (memOverview.total_active ?? 0) : Dd.SYSTEM.health.memory,
        scheduler: rt.scheduler_enabled ? '已启用' : '未启用(手动模式)',
      },
      model: Dd.SYSTEM.model,
    };
  }

  // 记忆
  if (memList && Array.isArray(memList.rows)) {
    const items = memList.rows.map(normMemoryItem);
    const trusted = items.filter((m) => m.trust === 'trusted').length;
    Dd.MEMORY = {
      overview: {
        total: memOverview ? (memOverview.total_active ?? items.length) : items.length,
        trusted,
        candidate: items.length - trusted,
        audit_events: '—',
      },
      items,
      audit: [], // live 模式不展示演示审计;后续可接 FTS 搜索
    };
  }

  // 数据健康
  const cov = normCoverage(coverage);
  if (cov) Dd.COVERAGE = cov;

  // 聊天会话(消息懒取)
  let chatSessions: any = null;
  if (Array.isArray(sessions) && sessions.length) {
    chatSessions = sessions.map((s) => ({
      id: s.id, title: s.title || `会话 ${s.id}`, mode: s.mode || 'general',
      last_message: s.last_message || '', messages: null, // null = 未加载
    }));
    Dd.CHAT_SESSIONS = chatSessions;
  }

  // ATLAS 账本仅在系统状态明确开启时预取;关闭时不打会 503 的业务探测路由。
  atlasOn = false;
  if (sysStatus?.atlas_enabled === true) {
    try {
      await refreshCandidates();
      atlasOn = true;
      // 外部论题:取持仓标的 + 前 10 只自选(账本为空时诚实展示空列表)
      const ftSymbols = Array.from(new Set([
        ...(posOpen || []).map((p) => p.symbol),
        ...wl.slice(0, 10).map((w) => w.symbol),
      ]));
      const lists = await Promise.allSettled(ftSymbols.map((s) => api.getForwardTheses(s)));
      Dd.FORWARD_THESES = lists
        .flatMap((r) => (r.status === 'fulfilled' ? (r.value.items || []) : []))
        .map(normForwardThesis);
    } catch (e) {
      atlasOn = false;
    }
  }

  // 预取自选股 K 线(首页 Spark / 详情主图)
  const pricePrefetch = wl.slice(0, 30).map((w) =>
    api.getPrices(w.symbol, 120).then((bars) => { Dd.PRICES[w.symbol] = normPrices(bars); }).catch(() => {})
  );
  await Promise.allSettled(pricePrefetch);

  store().set((s) => ({
    live: 'live',
    watchlist: wl,
    positions,
    reviews: Dd.REVIEWS.slice(),
    runtime: { ...rt },
    memoryItems: Dd.MEMORY.items.slice(),
    sessions: chatSessions || s.sessions,
  }));
  startHealthMonitor();
  window.toast && window.toast('已连接本地后端，数据为实时数据');
}

// ---------- 个股懒取 ----------
export async function ensureSymbol(symbol) {
  if (!live || fetchedSymbols.has(symbol)) return;
  fetchedSymbols.add(symbol);
  const Dd = D();
  const tasks = [
    api.getPrices(symbol, 120).then((bars) => { Dd.PRICES[symbol] = normPrices(bars); }),
    api.getNews(symbol, 72).then((rows) => { Dd.NEWS[symbol] = normNews(rows); }),
    api.getSignalEvidence(symbol, 8).then((runs) => { Dd.EVIDENCE[symbol] = normEvidence(runs); }),
    api.getSignalEval(symbol, 60).then((e) => { const v = normEval(e); if (v) Dd.EVAL[symbol] = v; }),
    (atlasOn ? api.getCaseView(symbol) : api.getResearchDossier(symbol)).then((resp) => {
      const d = atlasOn ? resp.dossier : resp;
      const v = normDossier(d);
      if (!v) return;
      Dd.DOSSIER[symbol] = { ...(Dd.DOSSIER._default || {}), ...v.out };
      if (v.evidence.length) Dd.EVIDENCE[symbol] = v.evidence;
      if (v.research && (v.research.copilot || v.research.thesis)) {
        const cp = v.research.copilot || {};
        Dd.COPILOT[symbol] = {
          ...(Dd.COPILOT._default || {}),
          ...cp,
          thesis: v.research.thesis || cp.thesis || (Dd.COPILOT._default || {}).thesis,
          risks: v.research.risks?.length ? v.research.risks : (cp.risks || []),
          questions: v.research.open_questions?.length ? v.research.open_questions : (cp.questions || []),
        };
      }
      // ATLAS:case_view 账本落到 CASE_LOOP / FORWARD_THESES(空账本时保留 _default 的诚实占位)
      if (atlasOn && resp.case_view) {
        const cv = resp.case_view;
        const fts = (cv.forward_theses || []).map(normForwardThesis);
        if (fts.length) {
          Dd.FORWARD_THESES = [...Dd.FORWARD_THESES.filter((t) => t.symbol !== symbol), ...fts];
        }
        const rs = (d && d.research_state) || {};
        const base = Dd.CASE_LOOP._default || {};
        const caseInfo = d && d.case;
        Dd.CASE_LOOP[symbol] = {
          ...base,
          thesis: rs.thesis || base.thesis,
          gate_status: caseInfo ? (caseInfo.quality_gate && caseInfo.quality_gate.gate_pass ? 'pass' : 'warning') : base.gate_status,
          status: ((cv.theses || []).length || fts.length) ? 'active' : base.status,
          questions: (rs.open_questions && rs.open_questions.length) ? rs.open_questions
            : ((d.pending_questions && d.pending_questions.length) ? d.pending_questions : base.questions),
          next_review: (fts[0] && fts[0].next_review !== '—' && fts[0].next_review) || base.next_review,
        };
      }
    }),
  ];
  await Promise.allSettled(tasks);
  poke();
}

// ---------- 写操作门面(live 调后端;demo 抛错由调用方落回演示行为) ----------
async function ensureLive() {
  if (!live) { const e: any = new Error('demo'); e.demo = true; throw e; }
}

async function refreshCore() {
  // 写操作后刷新受影响的核心数据
  try {
    const [wl, posOpen, posClosed] = await Promise.all([
      api.getWatchlist(), api.getPositions('open'), api.getPositions('closed'),
    ]);
    const watch = (wl || []).map(normWatchItem);
    D().WATCHLIST = watch;
    D().SEARCH_POOL = watch.map((w) => ({ symbol: w.symbol, name: w.name, market: w.market }));
    store().set({
      watchlist: watch,
      positions: [...(posOpen || []), ...(posClosed || [])].map(normPosition),
    });
  } catch (e) { /* 刷新失败保持现状 */ }
}

export const MC_API = {
  isLive,
  ensureSymbol,
  async addWatch(symbol, name, market) {
    await ensureLive();
    await api.addStock(symbol, name, market);
    await refreshCore();
  },
  async removeWatch(symbol) {
    await ensureLive();
    await api.removeStock(symbol);
    await refreshCore();
  },
  async createPosition(payload) {
    await ensureLive();
    await api.createPosition(payload);
    await refreshCore();
  },
  async updatePosition(id, payload) {
    await ensureLive();
    await api.updatePosition(id, payload);
    await refreshCore();
  },
  async closePosition(id, payload) {
    await ensureLive();
    await api.closePosition(id, payload);
    await refreshCore();
  },
  async deletePosition(id) {
    await ensureLive();
    await api.deleteClosedPosition(id);
    await refreshCore();
  },
  async ensureReview(kind) {
    await ensureLive();
    const run = kind === 'daily' ? api.ensureDailyReview : api.ensureLongTermReview;
    await run();
    const rows = await api.getReviews();
    let items = (Array.isArray(rows) ? rows : []).map(normReview);
    const detail = await Promise.allSettled(items.slice(0, 8).map((r) => api.getReview(r.id)));
    detail.forEach((res, i) => { if (res.status === 'fulfilled' && res.value) items[i] = normReview(res.value); });
    if (items.length) { D().REVIEWS = items; store().set({ reviews: items.slice() }); }
  },
  async loadReviewContent(id) {
    if (!live || reviewContentLoaded.has(id)) return null;
    const r = await api.getReview(id);
    reviewContentLoaded.add(id);
    const full = normReview(r);
    D().REVIEWS = D().REVIEWS.map((x) => (x.id === id ? full : x));
    store().set({ reviews: D().REVIEWS.slice() });
    return full;
  },
  async saveRuntime(cfg) {
    await ensureLive();
    const updated = await api.updateRuntimeConfig(runtimeToBackend(cfg));
    D().RUNTIME = runtimeFromBackend(updated);
    store().set({ runtime: { ...D().RUNTIME } });
  },
  async memoryDelete(id) {
    await ensureLive();
    await api.deleteMemory(id);
    const list = await api.getMemoryList({ limit: 200 });
    const items = (list.rows || []).map(normMemoryItem);
    D().MEMORY.items = items;
    store().set({ memoryItems: items.slice() });
  },
  async memoryConfirm(id) {
    await ensureLive();
    await api.patchMemory(id, { trust: 'trusted', status: 'trusted' });
    const list = await api.getMemoryList({ limit: 200 });
    const items = (list.rows || []).map(normMemoryItem);
    D().MEMORY.items = items;
    store().set({ memoryItems: items.slice() });
  },
  async loadChatMessages(sessionId) {
    await ensureLive();
    const rows = await api.getChatMessages(sessionId);
    return (rows || []).map((m) => ({
      role: m.role,
      content: m.role === 'user' ? (m.content || '') : undefined,
      answer: m.role === 'assistant' ? (m.answer || m.content || '') : undefined,
      used_resources: m.used_resources || [],
      action: m.action || m.pending_action || null,
    }));
  },
  async sendChat(payload, handlers) {
    await ensureLive();
    return api.chatWithAIStream(payload, handlers);
  },
  async confirmAction(id) {
    await ensureLive();
    const out = await api.confirmAIAction(id);
    await refreshCore(); // 动作可能写自选/持仓
    return out;
  },
  isAtlasOn() { return atlasOn; },
  async candidatePromote(id) {
    if (!live || !atlasOn) { const e: any = new Error('demo'); e.demo = true; throw e; }
    await api.promoteMemoryCandidate(id);
    await refreshCandidates();
  },
  async candidateReject(id) {
    if (!live || !atlasOn) { const e: any = new Error('demo'); e.demo = true; throw e; }
    await api.rejectMemoryCandidate(id);
    await refreshCandidates();
  },
  async createSession(payload) {
    await ensureLive();
    return api.createChatSession(payload);
  },
  async archiveSession(id) {
    await ensureLive();
    return api.archiveChatSession(id);
  },
};

window.MC_LIVE = MC_API;
