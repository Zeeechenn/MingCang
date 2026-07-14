// ============================================================
// 持仓页 — 记录 / 平仓 / 已实现盈亏(不接券商,不自动交易)
// ============================================================
import React from 'react';
import { Badge, CCY, Card, MKT, PageHead, RefreshButton, fmt, navigate, pnlClass, toast, useStockSuggest, useStore } from './shared';
const { useState: usePoState, useMemo: usePoMemo } = React;

function PositionForm() {
  const [q, setQ] = usePoState('');
  const [name, setName] = usePoState('');
  const [market, setMarket] = usePoState('CN');
  const [qty, setQty] = usePoState('');
  const [cost, setCost] = usePoState('');
  const sugg = useStockSuggest(q, market);
  const [picked, setPicked] = usePoState(false);
  const [pending, setPending] = usePoState<any>(null);

  function pickStock(s) {
    setQ(s.symbol); setName(s.name); setMarket(s.market); setPicked(true);
  }
  function submit(e) {
    e.preventDefault();
    if (!q.trim() || !qty || !cost) return;
    setPending({ symbol: q.trim(), name: name.trim() || q.trim(), market, quantity: Number(qty), avg_cost: Number(cost) });
  }
  function confirm() {
    if (!pending) return;
    const payload = pending;
    const done = () => { toast(`已记录持仓 ${payload.name}(仅记录，不会真实下单)`); setQ(''); setName(''); setQty(''); setCost(''); setPicked(false); setPending(null); };
    window.MC_LIVE.createPosition(payload)
      .then(done)
      .catch((err) => {
        if (!err || !err.demo) { toast(`添加失败:${err?.message || '后端错误'}`); return; }
        toast('示例模式不会写入持仓；连接本地后端后再试');
      });
  }

  return (
    <form className="glass pop pop-1" style={{ padding: '15px 18px' }} onSubmit={submit} data-tour="position-form">
      <div className="spread" style={{ flexWrap: 'wrap', gap: 8 }}>
        <div>
          <div className="t-eyebrow">添加持仓</div>
          <div className="t-faint" style={{ fontSize: 12, marginTop: 2 }}>记录你的真实或模拟持仓 · 明仓不接券商，确认后只写数据库</div>
        </div>
      </div>
      <div className="grid" style={{ gridTemplateColumns: 'minmax(150px, 1.2fr) minmax(120px, 1fr) 88px 100px 110px auto', gap: 8, marginTop: 12, alignItems: 'start' }} data-grid="pos-form">
        <div style={{ position: 'relative' }}>
          <input className="field" value={q} onChange={(e) => { setQ(e.target.value); setPicked(false); }} placeholder="代码或名称" />
          {!picked && sugg.length > 0 && (
            <div className="glass" style={{ position: 'absolute', top: 40, left: 0, width: '100%', minWidth: 230, zIndex: 30, borderRadius: 14, padding: 5, background: 'var(--glass-strong)' }}>
              {sugg.map((s) => (
                <button key={s.symbol} type="button" className="navlink" style={{ display: 'flex', width: '100%', justifyContent: 'space-between' }} onClick={() => pickStock(s)}>
                  <span>{s.name}</span><span className="t-num t-faint">{s.symbol}</span>
                </button>
              ))}
            </div>
          )}
        </div>
        <input className="field" value={name} onChange={(e) => setName(e.target.value)} placeholder="名称自动补全" />
        <select className="field" value={market} onChange={(e) => setMarket(e.target.value)}>
          <option value="CN">A股</option><option value="HK">港股</option><option value="US">美股</option>
        </select>
        <input className="field" value={qty} onChange={(e) => setQty(e.target.value.replace(/[^\d.]/g, ''))} placeholder="数量" inputMode="decimal" />
        <input className="field" value={cost} onChange={(e) => setCost(e.target.value.replace(/[^\d.]/g, ''))} placeholder="成本价" inputMode="decimal" />
        <button className="btn btn-primary" disabled={!q || !qty || !cost} type="submit">添加</button>
      </div>
      {pending && (
        <div className="glass-inset" style={{ padding: '12px 14px', marginTop: 10 }} role="status">
          <div style={{ fontSize: 13.5, fontWeight: 650 }}>{pending.name} · {pending.symbol}</div>
          <div className="t-dim" style={{ fontSize: 12.5, marginTop: 4 }}>
            {MKT[pending.market]} · {fmt.money(pending.quantity)} 股 · 成本 {fmt.price(pending.avg_cost)}。确认后仅写入明仓持仓账本，不会真实下单。
          </div>
          <div className="row" style={{ gap: 6, marginTop: 10 }}>
            <button className="btn btn-sm btn-primary" type="button" onClick={confirm}>确认写入持仓</button>
            <button className="btn btn-sm btn-quiet" type="button" onClick={() => setPending(null)}>返回修改</button>
          </div>
        </div>
      )}
    </form>
  );
}

function CloseButton({ item }: any) {
  const [open, setOpen] = usePoState(false);
  const [price, setPrice] = usePoState('');
  function submit(e) {
    e.preventDefault();
    const p = Number(price);
    if (!p) return;
    window.MC_LIVE.closePosition(item.id, { close_price: p })
      .then(() => toast(`已平仓 ${item.name}，盈亏记入已实现`))
      .catch((err) => {
        if (!err || !err.demo) { toast(`平仓失败:${err?.message || '后端错误'}`); return; }
        toast('示例模式不会平仓；连接本地后端后再试');
      });
  }
  if (!open) return <button className="btn btn-sm" onClick={() => { setOpen(true); setPrice(String(item.latest_price)); }}>平仓</button>;
  return (
    <form className="row" style={{ gap: 6, justifyContent: 'flex-end' }} onSubmit={submit}>
      <input className="field" style={{ width: 88, padding: '5px 10px' }} autoFocus value={price} onChange={(e) => setPrice(e.target.value.replace(/[^\d.]/g, ''))} placeholder="平仓价" />
      <button className="btn btn-sm btn-primary" disabled={!price} type="submit">确认</button>
      <button className="btn btn-sm btn-quiet" type="button" onClick={() => setOpen(false)}>取消</button>
    </form>
  );
}

export function PositionsPage() {
  const [state] = useStore();
  const { positions } = state;
  const R = window.MC_DATA.RUNTIME;
  const [confirmDel, setConfirmDel] = usePoState<any>(null);
  const open = positions.filter((p) => p.status !== 'closed');
  const closed = positions.filter((p) => p.status === 'closed');
  const totals = usePoMemo(() => open.reduce((acc, p) => {
    const m = p.market || 'CN';
    const cur = acc[m] || { mv: 0, cost: 0, count: 0 };
    cur.mv += p.latest_price * p.quantity;
    cur.cost += p.avg_cost * p.quantity;
    cur.count += 1;
    acc[m] = cur;
    return acc;
  }, {}), [positions]);
  const realized = closed.reduce((a, p) => a + (p.realized_pnl || 0), 0);

  return (
    <div className="grid" style={{ gap: 14 }}>
      <PageHead eyebrow="Portfolio Discipline" title="持仓纪律"
        desc="记录持仓、成本、浮动盈亏与规则上限。明仓只做纪律提醒和案卷留痕，不接券商、不自动交易。"
        right={<RefreshButton label="刷新行情" toastMsg="持仓最新价已刷新 · 浮动盈亏已更新" />} />
      <div className="grid pop" style={{ gridTemplateColumns: 'repeat(auto-fit, minmax(220px, 1fr))', gap: 10 }}>
        {Object.keys(totals).sort().map((m) => {
          const t = totals[m];
          const pnl = t.mv - t.cost;
          return (
            <div key={m} className="glass" style={{ padding: '14px 18px' }}>
              <div className="spread">
                <span className="t-eyebrow">{MKT[m]} · {CCY[m]}</span>
                <Badge tone="badge-dim">{t.count} 笔</Badge>
              </div>
              <div className="t-num" style={{ fontSize: 21, fontWeight: 700, marginTop: 6 }}>{fmt.money(t.mv)}</div>
              <div className={`t-num ${pnlClass(pnl)}`} style={{ fontSize: 13, fontWeight: 600, marginTop: 2 }}>
                {fmt.signedMoney(pnl)} / {fmt.signedPct(t.cost ? pnl / t.cost * 100 : 0)}
              </div>
            </div>
          );
        })}
        <div className="glass" style={{ padding: '14px 18px' }}>
          <span className="t-eyebrow">已实现盈亏</span>
          <div className={`t-num ${pnlClass(realized)}`} style={{ fontSize: 21, fontWeight: 700, marginTop: 6 }}>{fmt.signedMoney(realized)}</div>
          <div className="t-faint" style={{ fontSize: 12, marginTop: 2 }}>{closed.length} 笔平仓记录</div>
        </div>
      </div>

      <div className="grid pop pop-1" style={{ gridTemplateColumns: 'repeat(auto-fit, minmax(180px, 1fr))', gap: 10 }}>
        {[
          ['单股上限', `${R.max_stock_pct}%`, '任何单一标的不突破纪律线'],
          ['行业上限', `${R.max_sector_pct}%`, '同板块持仓合并计算'],
          ['总权益上限', `${R.max_total_pct}%`, '保留现金缓冲'],
          ['新信号试错', `${R.new_signal_trial_pct}%`, '只允许规则内小仓'],
        ].map(([label, value, sub]) => (
          <div key={label} className="glass" style={{ padding: '12px 16px' }}>
            <div className="spread">
              <span className="t-eyebrow">{label}</span>
              <Badge tone="badge-dim">规则</Badge>
            </div>
            <div className="t-num" style={{ fontSize: 20, fontWeight: 750, marginTop: 5 }}>{value}</div>
            <div className="t-faint" style={{ fontSize: 12, marginTop: 3 }}>{sub}</div>
          </div>
        ))}
      </div>

      <PositionForm />

      <Card eyebrow="Open Positions" title="当前持仓与纪律线" className="pop pop-2" pad={false} tour="open-positions">
        {open.length === 0 ? (
          <div className="card-body">
            <div className="empty"><b>暂无持仓。</b>可通过上方表单记录，或在 <a className="link" onClick={() => navigate('/chat')}>AI 对话</a>里说「添加持仓 300308 100股 成本150」。</div>
          </div>
        ) : (
          <div style={{ overflowX: 'auto' }} className="scroll-thin">
            <table className="mc-table" style={{ minWidth: 720 }}>
              <thead><tr><th>股票</th><th>数量</th><th>成本</th><th>最新价</th><th>止损 / 止盈</th><th>盈亏</th><th></th></tr></thead>
              <tbody>
                {open.map((p) => {
                  const pnl = (p.latest_price - p.avg_cost) * p.quantity;
                  const pct = (p.latest_price - p.avg_cost) / p.avg_cost * 100;
                  return (
                    <tr key={p.id}>
                      <td>
                        <a className="link" style={{ fontWeight: 600 }} onClick={() => navigate(`/stock/${p.symbol}`)}>{p.name}</a>
                        <div className="t-num t-faint" style={{ fontSize: 11.5 }}>{p.symbol} · {MKT[p.market]} · {CCY[p.market]}</div>
                      </td>
                      <td className="t-num">{fmt.money(p.quantity)}</td>
                      <td className="t-num">{fmt.price(p.avg_cost)}</td>
                      <td className="t-num">{fmt.price(p.latest_price)}</td>
                      <td className="t-num" style={{ fontSize: 12.5 }}>
                        <span className="down">{fmt.price(p.stop_loss)}</span><span className="t-faint"> / </span><span className="up">{fmt.price(p.take_profit)}</span>
                      </td>
                      <td><span className={`t-num ${pnlClass(pnl)}`} style={{ fontWeight: 650 }}>{fmt.signedMoney(pnl)}<span style={{ opacity: 0.75 }}> / {fmt.signedPct(pct)}</span></span></td>
                      <td style={{ textAlign: 'right' }}><CloseButton item={p} /></td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </Card>

      <Card eyebrow="Closed Positions" title="平仓记录" className="pop pop-3" pad={false}
        right={<span className={`t-num ${pnlClass(realized)}`} style={{ fontSize: 13, fontWeight: 650 }}>已实现 {fmt.signedMoney(realized)}</span>}>
        {closed.length === 0 ? (
          <div className="card-body"><div className="empty">暂无平仓记录。</div></div>
        ) : (
          <div style={{ overflowX: 'auto' }} className="scroll-thin">
            <table className="mc-table" style={{ minWidth: 680 }}>
              <thead><tr><th>股票</th><th>区间</th><th>数量</th><th>成本 → 平仓</th><th>已实现</th><th></th></tr></thead>
              <tbody>
                {closed.map((p) => (
                  <tr key={p.id}>
                    <td>
                      <span style={{ fontWeight: 600 }}>{p.name}</span>
                      <div className="t-num t-faint" style={{ fontSize: 11.5 }}>{p.symbol}</div>
                    </td>
                    <td className="t-num t-faint" style={{ fontSize: 12 }}>{p.opened_at} → {p.closed_at}</td>
                    <td className="t-num">{fmt.money(p.quantity)}</td>
                    <td className="t-num">{fmt.price(p.avg_cost)} → {fmt.price(p.close_price)}</td>
                    <td><span className={`t-num ${pnlClass(p.realized_pnl)}`} style={{ fontWeight: 650 }}>{fmt.signedMoney(p.realized_pnl)} / {fmt.signedPct(p.realized_pnl_pct)}</span></td>
                    <td style={{ textAlign: 'right' }}>
                      {confirmDel === p.id ? (
                        <span className="row" style={{ gap: 6, justifyContent: 'flex-end' }}>
                          <button className="btn btn-sm btn-danger" onClick={() => {
                            window.MC_LIVE.deletePosition(p.id)
                              .then(() => toast('平仓记录已删除'))
                              .catch((err) => {
                                if (!err || !err.demo) { toast(`删除失败:${err?.message || '后端错误'}`); return; }
                                toast('示例模式不会删除平仓记录；连接本地后端后再试');
                              });
                          }}>确认删除</button>
                          <button className="btn btn-sm btn-quiet" onClick={() => setConfirmDel(null)}>取消</button>
                        </span>
                      ) : (
                        <button className="btn btn-sm btn-quiet btn-danger" onClick={() => setConfirmDel(p.id)}>删除</button>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>
    </div>
  );
}

window.PositionsPage = PositionsPage;
