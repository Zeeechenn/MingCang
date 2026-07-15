// ============================================================
// 脉冲页 — 自选与候选池首页
// ============================================================
import React from 'react';
import { DebateReport } from './page-reports';
import { Badge, CCY, Card, DataSourceNotice, MCStore, MKT, Metric, Modal, PageHead, PoolShell, RefreshButton, ScoreBar, SortSeg, Spark, applyPoolSort, assetKey, currencyAmount, dailyChangePct, fmt, ltTone, navigate, pnlClass, recTone, stockPath, toast, useSortCtl, useStockPoolFilter, useStockSuggest, useStore } from './shared';
const { useState: usePState, useMemo: usePMemo } = React;

const RELEASE_DISMISS_KEY = 'mc_release_dismissed_v1';

function ReleaseStrip() {
  const SYS = window.MC_DATA.SYSTEM;
  // 关闭后记住当前版本号;只有发布新版本(version 变化)时才会再次出现
  const [dismissed, setDismissed] = usePState(() => {
    try { return localStorage.getItem(RELEASE_DISMISS_KEY) === SYS.version; } catch { return false; }
  });
  if (dismissed) return null;
  function close() {
    try { localStorage.setItem(RELEASE_DISMISS_KEY, SYS.version); } catch { /* ignore */ }
    setDismissed(true);
  }
  return (
    <div className="glass pop pop-1" style={{ padding: '14px 46px 14px 18px', position: 'relative' }} data-tour="release">
      <div className="spread" style={{ flexWrap: 'wrap', gap: 14 }}>
        <div style={{ minWidth: 240, flex: 1 }}>
          <div className="t-eyebrow">当前发布</div>
          <div style={{ marginTop: 3, fontSize: 13.5, fontWeight: 550 }}>
            v{SYS.version} 正式面保持稳定；M67 港美股小池已接入独立规则灰度影子轨，量化生产、提醒与下单仍保持关闭。
          </div>
        </div>
        <div className="row" style={{ flexWrap: 'wrap', gap: 8 }}>
          {SYS.release.map(([k, v]) => (
            <div key={k} className="glass-inset" style={{ padding: '6px 12px' }}>
              <span className="t-num" style={{ fontSize: 11.5, fontWeight: 650, color: 'var(--accent-ink)' }}>{k}</span>
              <span className="t-dim" style={{ fontSize: 11.5, marginLeft: 8 }}>{v}</span>
            </div>
          ))}
        </div>
      </div>
      <button type="button" className="release-close" onClick={close} aria-label="关闭本次发布提示"
        title="关闭本次发布提示 · 发布新版本后会再次显示"
        style={{ position: 'absolute', top: 11, right: 11 }}>×</button>
    </div>
  );
}

function TodayCall({ watchlist }: any) {
  const top = watchlist.filter((w) => w.latest_signal).sort((a, b) => b.latest_signal.composite_score - a.latest_signal.composite_score)[0];
  const sig = top?.latest_signal;
  const arb = sig?.llm_arbitration || {};
  const score = sig?.composite_score ?? 0;
  const [debateOpen, setDebateOpen] = usePState(false);
  if (!top) {
    return (
      <Card eyebrow="今日裁决案卷" title="暂无信号" className="pop pop-1">
        <div className="empty"><b>自选池还没有信号。</b> 添加自选标的后，系统会在下次收盘后自动生成信号。</div>
      </Card>
    );
  }
  const debate = window.MC_DATA.DEBATE[top.symbol] || window.MC_DATA.DEBATE._default;
  const r1 = (debate.rounds || []).find((r) => r.speaker === 'bull');
  const r2 = (debate.rounds || []).find((r) => r.speaker === 'bear');
  const r3 = (debate.rounds || []).find((r) => r.speaker === 'adjudicator');
  const bullItems = r1 ? r1.points : (arb.bull_points || []);
  const bearItems = r2 ? [...r2.rebuttals.map((rb) => rb.counter), ...(r2.additional || [])] : (arb.bear_points || []);
  return (
    <section className="glass pop pop-1" data-tour="today-call" style={{ overflow: 'hidden' }}>
      <div className="today-grid">
      <div className="today-cell">
        <div className="card-body" style={{ paddingBottom: 10 }}>
          <div className="spread" style={{ alignItems: 'flex-start' }}>
            <div>
              <div className="t-eyebrow">今日裁决案卷</div>
              <div className="row" style={{ marginTop: 8, flexWrap: 'wrap', alignItems: 'baseline' }}>
                <h1 className="t-hero" style={{ margin: 0, cursor: 'pointer' }} onClick={() => navigate(stockPath(top.symbol, top.market))}>{top.name}</h1>
                <span className="t-num t-faint" style={{ fontSize: 13 }}>{top.symbol}</span>
                <Badge tone={recTone(sig.recommendation)}>{sig.recommendation}</Badge>
                {top.long_term_label && <Badge tone={ltTone(top.long_term_label.label)}>长期 {top.long_term_label.label}</Badge>}
              </div>
              <div className="t-dim" style={{ marginTop: 6, fontSize: 13 }}>{top.industry} · 信号日期 {sig.date}</div>
            </div>
            <button className="btn btn-sm" onClick={() => navigate(stockPath(top.symbol, top.market))}>查看详情</button>
          </div>

          <div className="grid" style={{ gridTemplateColumns: 'repeat(auto-fit, minmax(240px, 1fr))', marginTop: 18, gap: 18, alignItems: 'end' }}>
            <div>
              <div className="t-eyebrow">裁决强度 <span style={{ textTransform: 'none', letterSpacing: 0 }}>(-100 / +100)</span></div>
              <div className={`t-num ${score >= 0 ? 'up' : 'down'}`} style={{ fontSize: 52, fontWeight: 700, lineHeight: 1.1, letterSpacing: '-0.03em' }}>
                {fmt.signed(score)}
              </div>
              <div style={{ marginTop: 10 }}><ScoreBar score={score} height={7} /></div>
            </div>
            <div className="grid" style={{ gridTemplateColumns: 'repeat(auto-fit, minmax(96px, 1fr))', gap: 8 }}>
              <Metric label="技术" value={fmt.signed(sig.technical_score)} tone={pnlClass(sig.technical_score)} />
              <Metric label="情感" value={fmt.signed(sig.sentiment_score, 2)} tone={pnlClass(sig.sentiment_score)} />
              <Metric label="置信度" value={sig.confidence} />
              <Metric label="止损" value={fmt.price(sig.stop_loss)} tone="down" />
              <Metric label="止盈" value={fmt.price(sig.take_profit)} tone="up" />
              <Metric label="量化" value="休眠" sub="权重 0" />
            </div>
          </div>
        </div>
        <div style={{ borderTop: '1px solid var(--hairline-soft)', padding: '13px 18px' }}>
          <p className="t-dim" style={{ margin: 0, fontSize: 13.5, lineHeight: 1.65 }}>
            <span style={{ color: 'var(--accent-ink)', fontWeight: 650, marginRight: 8 }}>裁决</span>
            {arb.rationale}
          </p>
        </div>
      </div>

      <div className="today-cell today-cell-debate" data-tour="debate" style={{ display: 'flex', flexDirection: 'column' }}>
        <div className="card-head">
          <div style={{ minWidth: 0 }}>
            <div className="t-eyebrow">反方先行 · 今日裁决标的</div>
            <h2 className="t-title" style={{ margin: '2px 0 0' }}>{top.name} <span className="t-num t-faint" style={{ fontSize: 13, fontWeight: 500 }}>{top.symbol}</span></h2>
          </div>
          <Badge tone="badge-accent">研究总监</Badge>
        </div>
        <div className="row" style={{ padding: '12px 18px 2px', gap: 7, flexWrap: 'wrap' }}>
          <Badge tone={recTone(arb.action_bias)}>裁决 {arb.action_bias || '中性'}</Badge>
          {r3 && <Badge tone={r3.winning_side === 'bull' ? 'badge-up' : r3.winning_side === 'bear' ? 'badge-down' : 'badge-dim'}>{r3.winning_side === 'bull' ? '多方胜' : r3.winning_side === 'bear' ? '空方胜' : '平局'}</Badge>}
          {debate.director?.diverged && <Badge tone="badge-warn">分歧 σ {debate.director.score_stdev}</Badge>}
          <Badge tone={debate.used_llm ? 'badge-up' : 'badge-dim'}>{debate.used_llm ? `${debate.round_count} 轮辩论` : '快速共识'}</Badge>
        </div>
        <div className="grid" style={{ gridTemplateColumns: '1fr 1fr', gap: 0, flex: 1 }}>
          {[['多方开场', bullItems, 'up', '▲'], ['空方反驳', bearItems, 'down', '▼']].map(([title, items, cls, mark], col) => (
            <div key={title} style={{ padding: '12px 18px', borderLeft: col ? '1px solid var(--hairline-soft)' : 'none' }}>
              <div className={cls} style={{ fontSize: 12.5, fontWeight: 650, marginBottom: 10 }}>{title}</div>
              <ul style={{ margin: 0, padding: 0, listStyle: 'none', display: 'grid', gap: 9 }}>
                {items.slice(0, 4).map((item, i) => (
                  <li key={i} className="row" style={{ alignItems: 'flex-start', gap: 7, fontSize: 12.5, lineHeight: 1.5, color: 'var(--ink-2)' }}>
                    <span className={cls} style={{ fontSize: 10, marginTop: 3 }}>{mark}</span>
                    <span>{item}</span>
                  </li>
                ))}
              </ul>
            </div>
          ))}
        </div>
        <div style={{ borderTop: '1px solid var(--hairline-soft)', padding: '11px 18px' }}>
          <button className="btn btn-sm btn-primary" style={{ width: '100%' }} onClick={() => setDebateOpen(true)}>
            查看完整裁决案卷 · 四路分析师 / 三轮辩论 / 风控裁定 →
          </button>
        </div>
      </div>
      </div>

      {debateOpen && (
        <Modal eyebrow="多空辩论 · 完整报告" title={`${top.name} ${top.symbol} · ${debate.date}`} maxWidth={680}
          onClose={() => setDebateOpen(false)}
          right={<button className="btn btn-sm" onClick={() => { toast('已导出辩论报告 HTML(演示)'); }}>导出</button>}>
          <DebateReport debate={debate} />
        </Modal>
      )}
    </section>
  );
}

function PositionsOverview({ positions }: any) {
  const open = positions.filter((p) => p.status !== 'closed');
  const totals = open.reduce((acc, p) => {
    const market = p.market || 'CN';
    const row = acc[market] || { mv: 0, cost: 0, count: 0 };
    row.mv += p.latest_price * p.quantity;
    row.cost += p.avg_cost * p.quantity;
    row.count += 1;
    acc[market] = row;
    return acc;
  }, {});
  return (
    <Card eyebrow="Portfolio" title="持仓情况" className="pop pop-2" tour="positions-overview"
      right={<button className="btn btn-sm" onClick={() => navigate('/positions')}>管理持仓</button>}>
      <div className="grid" style={{ gridTemplateColumns: 'repeat(auto-fit, minmax(150px, 1fr))', gap: 8 }}>
        <Metric label="持仓数" value={open.length} sub="市值按币种分列" />
        {Object.keys(totals).sort().map((market) => {
          const total = totals[market];
          const pnl = total.mv - total.cost;
          return <Metric key={market} label={`${MKT[market]}市值`} value={currencyAmount(total.mv, market)} tone={pnlClass(pnl)} sub={`${CCY[market]} 盈亏 ${fmt.signedPct(total.cost ? pnl / total.cost * 100 : 0)}`} />;
        })}
      </div>
      {open.length === 0 ? (
        <div className="empty" style={{ marginTop: 10 }}>
          暂无持仓数据。可以进入<a className="link" onClick={() => navigate('/positions')}>持仓页</a>，或在 <a className="link" onClick={() => navigate('/chat')}>AI 对话</a>里说「添加持仓 300308 100股 成本150」。
        </div>
      ) : (
        <div className="grid" style={{ gridTemplateColumns: 'repeat(auto-fill, minmax(190px, 1fr))', gap: 8, marginTop: 10 }}>
          {open.slice(0, 4).map((p) => {
            const ppnl = (p.latest_price - p.avg_cost) / p.avg_cost * 100;
            return (
              <a key={p.id} className="glass-inset" style={{ padding: '10px 13px', textDecoration: 'none', color: 'inherit', cursor: 'pointer' }} onClick={() => navigate(stockPath(p.symbol, p.market))}>
                <div className="spread">
                  <div>
                    <div style={{ fontSize: 13.5, fontWeight: 600 }}>{p.name}</div>
                    <div className="t-num t-faint" style={{ fontSize: 11.5 }}>{p.symbol} · {CCY[p.market || 'CN']}</div>
                  </div>
                  <span className={`t-num ${pnlClass(ppnl)}`} style={{ fontSize: 13.5, fontWeight: 650 }}>{fmt.signedPct(ppnl)}</span>
                </div>
              </a>
            );
          })}
        </div>
      )}
    </Card>
  );
}

function MarketHeaderWidget() {
  const idx = window.MC_DATA.SYSTEM.market_overview.indices;
  return (
    <div className="row" style={{ gap: 8, flexWrap: 'wrap', justifyContent: 'flex-end' }}>
      {idx.map((x) => (
        <div key={x.name} className="glass-inset" style={{ padding: '8px 14px' }}>
          <div className="t-eyebrow">{x.name}</div>
          <div className="row" style={{ gap: 8, marginTop: 3, alignItems: 'baseline' }}>
            <span className="t-num" style={{ fontSize: 16, fontWeight: 700 }}>{fmt.money(x.close)}</span>
            <span className={`t-num ${pnlClass(x.change_pct)}`} style={{ fontSize: 13, fontWeight: 650 }}>{fmt.signedPct(x.change_pct)}</span>
          </div>
        </div>
      ))}
    </div>
  );
}

function SignalCardTile({ w }: any) {
  const s = w.latest_signal;
  const chg = dailyChangePct(w.symbol, w.market);
  return (
    <a className="glass-inset" style={{ padding: 13, cursor: 'pointer', textDecoration: 'none', color: 'inherit', display: 'block' }} onClick={() => navigate(stockPath(w.symbol, w.market))}>
      <div className="spread" style={{ alignItems: 'flex-start' }}>
        <div>
          <div style={{ fontSize: 13.5, fontWeight: 600 }}>{w.name}</div>
          <div className="t-num t-faint" style={{ fontSize: 11.5, marginTop: 1 }}>{w.symbol}</div>
        </div>
        <div className="row" style={{ gap: 5, flexWrap: 'wrap', justifyContent: 'flex-end' }}>
          {w.gray && <Badge tone="badge-accent">影子</Badge>}
          <Badge tone={recTone(s.recommendation)}>{s.recommendation}</Badge>
        </div>
      </div>
      <div className="spread" style={{ marginTop: 14, alignItems: 'flex-end' }}>
        <span className={`t-num ${pnlClass(s.composite_score)}`} style={{ fontSize: 23, fontWeight: 700 }}>{fmt.signed(s.composite_score)}</span>
        <div style={{ textAlign: 'right' }}>
          <Spark symbol={w.symbol} market={w.market} />
          {chg != null && <div className={`t-num ${pnlClass(chg)}`} style={{ fontSize: 11.5, fontWeight: 650 }}>{fmt.signedPct(chg)}</div>}
        </div>
      </div>
      {w.long_term_label && (
        <div className="spread" style={{ marginTop: 10, paddingTop: 8, borderTop: '1px solid var(--hairline-soft)' }}>
          <span className="t-faint" style={{ fontSize: 11.5 }}>长期标签</span>
          <Badge tone={ltTone(w.long_term_label.label)}>{w.long_term_label.label}</Badge>
        </div>
      )}
    </a>
  );
}

// 列表行:一行一条,用涨跌、技术/情感分、止损止盈、长期标签填满信息密度
function SignalRowTile({ w }: any) {
  const s = w.latest_signal;
  const chg = dailyChangePct(w.symbol, w.market);
  return (
    <a className="row" style={{ padding: '9px 14px', gap: 12, cursor: 'pointer', textDecoration: 'none', color: 'inherit' }} onClick={() => navigate(stockPath(w.symbol, w.market))}>
      <div style={{ width: 130, flex: 'none', minWidth: 0 }}>
        <div style={{ fontSize: 13, fontWeight: 600, whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>{w.name}</div>
        <div className="t-num t-faint" style={{ fontSize: 11 }}>{w.symbol}</div>
      </div>
      <span className="row" style={{ width: 116, flex: 'none', gap: 4, flexWrap: 'wrap' }}>{w.gray && <Badge tone="badge-accent">影子</Badge>}<Badge tone={recTone(s.recommendation)}>{s.recommendation}</Badge></span>
      <span className={`t-num ${pnlClass(s.composite_score)}`} style={{ width: 52, flex: 'none', fontSize: 14.5, fontWeight: 700, textAlign: 'right' }}>{fmt.signed(s.composite_score)}</span>
      <span className={`t-num ${chg != null ? pnlClass(chg) : 't-faint'}`} style={{ width: 62, flex: 'none', fontSize: 12.5, fontWeight: 650, textAlign: 'right' }}>{chg != null ? fmt.signedPct(chg) : '–'}</span>
      <div style={{ flex: 1, minWidth: 60 }}><ScoreBar score={s.composite_score} height={4} /></div>
      <span className="t-num t-faint" style={{ fontSize: 11.5, width: 150, flex: 'none', textAlign: 'right' }}>
        技 {fmt.signed(s.technical_score)} · 情 {fmt.signed(s.sentiment_score)}
      </span>
      <span className="t-num t-faint" style={{ fontSize: 11.5, width: 132, flex: 'none', textAlign: 'right' }}>
        损 {fmt.price(s.stop_loss)} / 盈 {fmt.price(s.take_profit)}
      </span>
      <span style={{ width: 86, flex: 'none', textAlign: 'right' }}>
        {w.long_term_label ? <Badge tone={ltTone(w.long_term_label.label)}>{w.long_term_label.label}</Badge> : <span className="t-faint" style={{ fontSize: 11 }}>无长期标签</span>}
      </span>
    </a>
  );
}

function SignalGrid({ watchlist }: any) {
  const [filterOpen, setFilterOpen] = usePState(false);
  const [fq, setFq] = usePState('');
  const [fRec, setFRec] = usePState('all');
  const [fMkt, setFMkt] = usePState('all');
  const [fLt, setFLt] = usePState('all');
  const [sort, onSort] = useSortCtl();
  const signals = watchlist.filter((w) => w.latest_signal);
  const recs = usePMemo<any[]>(() => Array.from(new Set(signals.map((w) => w.latest_signal.recommendation))).sort(), [watchlist]);
  const lts = usePMemo<any[]>(() => Array.from(new Set(signals.filter((w) => w.long_term_label).map((w) => w.long_term_label.label))).sort(), [watchlist]);
  const ql = fq.trim().toLowerCase();
  const filtered = signals.filter((w) =>
    (fRec === 'all' || w.latest_signal.recommendation === fRec)
    && (fMkt === 'all' || w.market === fMkt)
    && (fLt === 'all' || (w.long_term_label && w.long_term_label.label === fLt))
    && (!ql || w.symbol.toLowerCase().includes(ql) || w.name.toLowerCase().includes(ql)));
  const filterActive = fRec !== 'all' || fMkt !== 'all' || fLt !== 'all' || !!ql;
  const sorted = applyPoolSort(filtered, sort);
  return (
    <Card eyebrow="最新横览" title="候选裁决横览" className="pop pop-3" tour="signal-grid"
      right={
        <div className="row" style={{ gap: 8, flexWrap: 'wrap', justifyContent: 'flex-end' }}>
          <SortSeg sort={sort} onSort={onSort} />
          <button className={`btn btn-sm ${filterActive ? 'btn-primary' : ''}`} onClick={() => setFilterOpen(!filterOpen)}>
            筛选{filterActive ? ` · ${filtered.length}` : ''} {filterOpen ? '▴' : '▾'}
          </button>
        </div>
      }>
      {filterOpen && (
        <div className="row" style={{ flexWrap: 'wrap', gap: 8, marginBottom: 12 }}>
          <input className="field" style={{ flex: 1, minWidth: 150 }} value={fq} onChange={(e) => setFq(e.target.value)} placeholder="搜索代码、名称" />
          <select className="field" style={{ width: 116 }} value={fRec} onChange={(e) => setFRec(e.target.value)}>
            <option value="all">全部信号</option>
            {recs.map((r) => <option key={r} value={r}>{r}</option>)}
          </select>
          <select className="field" style={{ width: 100 }} value={fMkt} onChange={(e) => setFMkt(e.target.value)}>
            <option value="all">全部市场</option><option value="CN">A股</option><option value="HK">港股</option><option value="US">美股</option>
          </select>
          <select className="field" style={{ width: 120 }} value={fLt} onChange={(e) => setFLt(e.target.value)}>
            <option value="all">全部长期标签</option>
            {lts.map((l) => <option key={l} value={l}>{l}</option>)}
          </select>
          {filterActive && <button className="btn btn-sm btn-quiet" onClick={() => { setFq(''); setFRec('all'); setFMkt('all'); setFLt('all'); }}>清除</button>}
        </div>
      )}
      {signals.length === 0 ? (
        <div className="empty">
          <b>暂无信号数据。</b>盘后信号由调度器在收盘后自动生成。你可以:<br />
          · 确认自选池已添加标的(见下方自选股管理)<br />
          · 前往<a className="link" onClick={() => navigate('/admin')}>配置页</a>检查调度器状态 · 前往<a className="link" onClick={() => navigate('/health')}>数据健康页</a>确认数据源正常
        </div>
      ) : (
        <PoolShell items={sorted} defaultCount={8} unit="只" cardMin={218}
          empty={<div className="empty">没有匹配的信号，试试清除筛选条件。</div>}
          renderCard={(w) => <SignalCardTile key={w.asset_key || assetKey(w.symbol, w.market)} w={w} />}
          renderRow={(w) => <SignalRowTile key={w.asset_key || assetKey(w.symbol, w.market)} w={w} />} />
      )}
    </Card>
  );
}

function AddStockForm({ onAdd }: any) {
  const [open, setOpen] = usePState(false);
  const [q, setQ] = usePState('');
  const [market, setMarket] = usePState('CN');
  const sugg = useStockSuggest(q, market);
  if (!open) return <button className="btn btn-sm btn-primary" onClick={() => setOpen(true)} data-tour="add-stock">＋ 添加标的</button>;
  return (
    <div className="row" style={{ position: 'relative', flexWrap: 'wrap', justifyContent: 'flex-end', gap: 6 }}>
      <input className="field" autoFocus style={{ width: 168 }} value={q} onChange={(e) => setQ(e.target.value)} placeholder="代码或名称，如 002475" />
      <select className="field" style={{ width: 76 }} value={market} onChange={(e) => setMarket(e.target.value)}>
        <option value="CN">A股</option><option value="HK">港股</option><option value="US">美股</option>
      </select>
      <button className="btn btn-sm btn-quiet" onClick={() => setOpen(false)}>取消</button>
      {sugg.length > 0 && (
        <div className="glass" style={{ position: 'absolute', top: 40, right: 0, width: 250, zIndex: 30, borderRadius: 14, padding: 5, background: 'var(--glass-strong)' }}>
          {sugg.map((s) => (
            <button key={s.asset_key || assetKey(s.symbol, s.market)} className="navlink" style={{ display: 'flex', width: '100%', justifyContent: 'space-between' }}
              onClick={() => { onAdd(s); setQ(''); setOpen(false); }}>
              <span>{s.name}</span>
              <span className="t-num t-faint">{s.symbol} · {s.market}</span>
            </button>
          ))}
        </div>
      )}
    </div>
  );
}

function WatchlistManage({ watchlist }: any) {
  const [removing, setRemoving] = usePState<any>(null);
  const [sort, onSort] = useSortCtl();
  const f = useStockPoolFilter(watchlist);
  const filtered = f.filtered;

  function add(s) {
    if (MCStore.get().watchlist.some((w) => (w.asset_key || assetKey(w.symbol, w.market)) === assetKey(s.symbol, s.market))) { toast('该标的已在自选池'); return; }
    window.MC_LIVE.addWatch(s.symbol, s.name, s.market)
      .then(() => toast(`已添加 ${s.name}，下次收盘后生成信号`))
      .catch((e) => {
        if (!e || !e.demo) { toast(`添加失败:${e?.message || '后端错误'}`); return; }
        MCStore.set((st) => ({ watchlist: [...st.watchlist, { ...s, industry: '待标注', latest_signal: null, observe: s.market !== 'CN' }] }));
        toast(`已加入演示自选:${s.name}`);
      });
  }
  function remove(symbol, market) {
    window.MC_LIVE.removeWatch(symbol, market)
      .then(() => { setRemoving(null); toast(`已从自选池移除 ${symbol}`); })
      .catch((e) => {
        if (!e || !e.demo) { toast(`移除失败:${e?.message || '后端错误'}`); setRemoving(null); return; }
        MCStore.set((st) => ({ watchlist: st.watchlist.filter((w) => (w.asset_key || assetKey(w.symbol, w.market)) !== assetKey(symbol, market)) }));
        setRemoving(null);
        toast(`已从演示自选移除 ${symbol}`);
      });
  }

  return (
    <Card eyebrow="研究池" title="研究池管理" className="pop pop-3" right={<AddStockForm onAdd={add} />} tour="watchlist">
      <div className="spread" style={{ flexWrap: 'wrap', gap: 8, marginBottom: 12 }}>
        <span className="t-num t-faint" style={{ fontSize: 12 }}>{filtered.length}/{watchlist.length} 只</span>
        <div className="row" style={{ gap: 8, flexWrap: 'wrap', justifyContent: 'flex-end' }}>
          <SortSeg sort={sort} onSort={onSort} />
          {f.button}
        </div>
      </div>
      {f.bar}
      {watchlist.length === 0 ? (
        <div className="empty">
          <b>自选股池为空，先添加几只标的。</b><br />
          · 点击右上角「添加标的」，输入股票代码或名称(支持 A股 / 港股 / 美股)<br />
          · 或前往 <a className="link" onClick={() => navigate('/chat')}>AI 对话</a>，说「添加自选 300308」快速导入<br />
          · 添加后系统会在下次收盘后自动生成信号
        </div>
      ) : (
        <PoolShell items={applyPoolSort(filtered, sort)} defaultCount={9} unit="只" cardMin={225}
          empty={<div className="empty">没有匹配的自选股，尝试清除筛选条件。</div>}
          renderCard={(w) => (
            <div key={w.asset_key || assetKey(w.symbol, w.market)} className="glass-inset spread" style={{ padding: '10px 13px' }}>
              <a style={{ minWidth: 0, cursor: 'pointer', textDecoration: 'none', color: 'inherit' }} onClick={() => navigate(stockPath(w.symbol, w.market))}>
                <div style={{ fontSize: 13.5, fontWeight: 600, whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>{w.name}</div>
                <div className="t-num t-faint" style={{ fontSize: 11.5 }}>{w.symbol} · {w.industry || MKT[w.market]}</div>
                <div className="row" style={{ gap: 5, marginTop: 5, flexWrap: 'wrap' }}>
                  {w.long_term_label && <Badge tone={ltTone(w.long_term_label.label)}>长期 {w.long_term_label.label}</Badge>}
                  {w.gray && <Badge tone="badge-accent">灰度影子</Badge>}
                  {w.observe && !w.latest_signal && <Badge tone="badge-warn">观察</Badge>}
                </div>
              </a>
              {removing === (w.asset_key || assetKey(w.symbol, w.market)) ? (
                <div className="row" style={{ gap: 4 }}>
                  <button className="btn btn-sm btn-danger" onClick={() => remove(w.symbol, w.market)}>确认</button>
                  <button className="btn btn-sm btn-quiet" onClick={() => setRemoving(null)}>取消</button>
                </div>
              ) : (
                <button className="btn btn-sm btn-quiet btn-danger" title="移除" onClick={() => setRemoving(w.asset_key || assetKey(w.symbol, w.market))} style={{ padding: '2px 9px' }}>×</button>
              )}
            </div>
          )}
          renderRow={(w) => (
            <div key={w.asset_key || assetKey(w.symbol, w.market)} className="row" style={{ padding: '8px 14px', gap: 12 }}>
              <a className="row" style={{ flex: 1, minWidth: 0, gap: 12, cursor: 'pointer', textDecoration: 'none', color: 'inherit' }} onClick={() => navigate(stockPath(w.symbol, w.market))}>
                <div style={{ width: 130, flex: 'none', minWidth: 0 }}>
                  <div style={{ fontSize: 13, fontWeight: 600, whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>{w.name}</div>
                  <div className="t-num t-faint" style={{ fontSize: 11 }}>{w.symbol}</div>
                </div>
                <span className="t-faint" style={{ width: 120, flex: 'none', fontSize: 11.5, whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>{w.industry || MKT[w.market]}</span>
                <span style={{ width: 80, flex: 'none' }}>
                  {w.latest_signal ? <Badge tone={recTone(w.latest_signal.recommendation)}>{w.latest_signal.recommendation}</Badge> : <Badge tone="badge-dim">无信号</Badge>}
                </span>
                <span className={`t-num ${w.latest_signal ? pnlClass(w.latest_signal.composite_score) : 't-faint'}`} style={{ width: 50, flex: 'none', fontSize: 13, fontWeight: 650, textAlign: 'right' }}>
                  {w.latest_signal ? fmt.signed(w.latest_signal.composite_score) : '–'}
                </span>
                <span style={{ flex: 1, textAlign: 'right' }}>
                  {w.long_term_label ? <Badge tone={ltTone(w.long_term_label.label)}>长期 {w.long_term_label.label}</Badge> : <span className="t-faint" style={{ fontSize: 11 }}>{MKT[w.market]}{w.gray ? ' · 灰度影子' : (w.observe ? ' · 观察' : '')}</span>}
                </span>
              </a>
              {removing === (w.asset_key || assetKey(w.symbol, w.market)) ? (
                <span className="row" style={{ gap: 4, flex: 'none' }}>
                  <button className="btn btn-sm btn-danger" onClick={() => remove(w.symbol, w.market)}>确认</button>
                  <button className="btn btn-sm btn-quiet" onClick={() => setRemoving(null)}>取消</button>
                </span>
              ) : (
                <button className="btn btn-sm btn-quiet btn-danger" title="移除" onClick={() => setRemoving(w.asset_key || assetKey(w.symbol, w.market))} style={{ padding: '2px 9px', flex: 'none' }}>×</button>
              )}
            </div>
          )} />
      )}
    </Card>
  );
}

function ActivityLedger({ watchlist, positions }: any) {
  const items = [
    ...watchlist.filter((w) => w.latest_signal).slice(0, 5).map((w) => ({
      time: w.latest_signal.date.slice(5), kind: '信号',
      head: `${w.name} ${w.latest_signal.recommendation}`,
      detail: `综合 ${fmt.signed(w.latest_signal.composite_score)} · 技术 ${fmt.signed(w.latest_signal.technical_score)} · 情感 ${fmt.signed(w.latest_signal.sentiment_score, 2)}`,
    })),
    ...positions.filter((p) => p.status !== 'closed').slice(0, 3).map((p) => ({
      time: (p.entry_date || '').slice(5), kind: '持仓',
      head: `${p.name} ${fmt.signedPct((p.latest_price - p.avg_cost) / p.avg_cost * 100)}`,
      detail: `止损 ${fmt.price(p.stop_loss)} · 止盈 ${fmt.price(p.take_profit)}`,
    })),
  ];
  return (
    <Card eyebrow="事件时间线" title="证据与动作流水" className="pop pop-3">
      <div className="grid" style={{ gap: 0 }}>
        {items.map((it, i) => (
          <div key={i} className="row" style={{ alignItems: 'flex-start', gap: 12, padding: '10px 0', borderBottom: i < items.length - 1 ? '1px solid var(--hairline-soft)' : 'none' }}>
            <span className="t-num t-faint" style={{ fontSize: 11.5, width: 38, flex: 'none', marginTop: 2 }}>{it.time}</span>
            <Badge tone={it.kind === '信号' ? 'badge-accent' : 'badge-dim'}>{it.kind}</Badge>
            <div style={{ minWidth: 0 }}>
              <div style={{ fontSize: 13, fontWeight: 600 }}>{it.head}</div>
              <div className="t-faint" style={{ fontSize: 11.5, marginTop: 1 }}>{it.detail}</div>
            </div>
          </div>
        ))}
      </div>
    </Card>
  );
}

export function PulsePage() {
  const [state] = useStore();
  const { watchlist, positions } = state;
  return (
    <div className="grid" style={{ gap: 14 }}>
      <PageHead eyebrow="今日态势" title="今日持仓裁决"
        desc="从信号、反方、长期标签、风险经理到最终仓位，一屏看清为什么是这只、为什么只能这个仓位。"
        right={<div className="row" style={{ gap: 10, flexWrap: 'wrap', justifyContent: 'flex-end' }}>
          <RefreshButton toastMsg="已同步盘后快照 · 行情与信号已刷新" />
          <MarketHeaderWidget />
        </div>} />
      <DataSourceNotice />
      <ReleaseStrip />
      <TodayCall watchlist={watchlist} />
      <div className="grid" style={{ gridTemplateColumns: 'minmax(0, 1fr) 330px', gap: 14 }} data-grid="pulse-cols">
        <div className="grid" style={{ gap: 14 }}>
          <PositionsOverview positions={positions} />
          <SignalGrid watchlist={watchlist} />
          <WatchlistManage watchlist={watchlist} />
        </div>
        <ActivityLedger watchlist={watchlist} positions={positions} />
      </div>
    </div>
  );
}

window.PulsePage = PulsePage;
