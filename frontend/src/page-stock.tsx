// ============================================================
// 单股详情页 — 信号 / 研究 / 证据 / 新闻
// ============================================================
import React from 'react';
import { refreshResearchCopilot, reviewLatestSignal } from './services/api';
import { Badge, Card, MCStore, MKT, Markdown, McIcon, Metric, PageHead, PoolShell, PriceChart, RefreshButton, ScoreBar, Seg, SortSeg, Spark, applyPoolSort, dailyChangePct, fmt, ltTone, navigate, pnlClass, recTone, toast, useSortCtl, useStockPoolFilter, useStore } from './shared';
const { useState: useSState, useEffect: useSEffect } = React;

function getStock(symbol) {
  return MCStore.get().watchlist.find((w) => w.symbol === symbol)
    || window.MC_DATA.SEARCH_POOL.find((s) => s.symbol === symbol)
    || { symbol, name: symbol, market: 'CN' };
}
function pick(map, symbol) { return map[symbol] || map._default; }

function StockHeader({ stock, signal }: any) {
  const px = window.MC_DATA.PRICES[stock.symbol];
  const lastPx = px && px[px.length - 1];
  const chg = lastPx && px[px.length - 2] ? (lastPx.close - px[px.length - 2].close) / px[px.length - 2].close * 100 : null;
  return (
    <div className="glass pop" style={{ padding: '18px 20px' }}>
      <div className="spread" style={{ alignItems: 'center', gap: 10 }}>
        <div className="row" style={{ gap: 10, alignItems: 'center' }}>
          <button className="btn btn-sm" onClick={() => navigate('/stocks')}>
            <McIcon name="arrowLeft" size={15} /> 个股
          </button>
          <span className="t-faint" style={{ fontSize: 12.5 }}>个股研究 / {stock.name}</span>
        </div>
        <RefreshButton label="刷新数据" toastMsg={`已刷新 ${stock.name} 行情与新闻`} />
      </div>
      <div className="spread" style={{ marginTop: 10, flexWrap: 'wrap', gap: 14, alignItems: 'flex-end' }}>
        <div>
          <div className="row" style={{ flexWrap: 'wrap', alignItems: 'baseline' }}>
            <h1 className="t-hero" style={{ margin: 0 }}>{stock.name}</h1>
            <span className="t-num t-dim" style={{ fontSize: 15 }}>{stock.symbol}</span>
            {signal && <Badge tone={recTone(signal.recommendation)}>{signal.recommendation}</Badge>}
            <Badge tone="badge-dim">{MKT[stock.market]}</Badge>
          </div>
          <div className="t-dim" style={{ marginTop: 5, fontSize: 13 }}>
            {stock.industry || '未标注行业'} · 裁决证据 · 来源门控 · 复盘记忆
          </div>
        </div>
        <div className="row" style={{ gap: 8, flexWrap: 'wrap' }}>
          {lastPx && (
            <div className="glass-inset" style={{ padding: '8px 14px', textAlign: 'right' }}>
              <div className="t-eyebrow">最新收盘</div>
              <div className="row" style={{ gap: 8, justifyContent: 'flex-end' }}>
                <span className="t-num" style={{ fontSize: 17, fontWeight: 650 }}>{lastPx.close.toFixed(2)}</span>
                {chg !== null && <span className={`t-num ${pnlClass(chg)}`} style={{ fontSize: 13, fontWeight: 600 }}>{fmt.signedPct(chg)}</span>}
              </div>
            </div>
          )}
          <div className="glass-inset" style={{ padding: '8px 14px', textAlign: 'right' }}>
            <div className="t-eyebrow">综合分</div>
            <div className={`t-num ${signal ? pnlClass(signal.composite_score) : ''}`} style={{ fontSize: 17, fontWeight: 650 }}>{signal ? fmt.signed(signal.composite_score) : '–'}</div>
          </div>
          <div className="glass-inset" style={{ padding: '8px 14px', textAlign: 'right' }}>
            <div className="t-eyebrow">止损 / 止盈</div>
            <div className="t-num" style={{ fontSize: 14, fontWeight: 600, marginTop: 3 }}>
              <span className="down">{signal ? fmt.price(signal.stop_loss) : '–'}</span>
              <span className="t-faint"> / </span>
              <span className="up">{signal ? fmt.price(signal.take_profit) : '–'}</span>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}

function CaseLoopPanel({ stock, signal }: any) {
  const c = pick(window.MC_DATA.CASE_LOOP, stock.symbol);
  const sourceTotal = c.source_mix.reduce((a, [, n]) => a + n, 0) || 1;
  const finalPosition = pick(window.MC_DATA.DOSSIER, stock.symbol).final_position;
  return (
    <section className="glass pop pop-1" style={{ overflow: 'hidden' }}>
      <div className="card-head">
        <div>
          <div className="t-eyebrow">Case Loop</div>
          <h2 className="t-title" style={{ margin: '2px 0 0' }}>从进口判断到复盘记忆</h2>
        </div>
        <div className="row" style={{ gap: 6, flexWrap: 'wrap' }}>
          <Badge tone={c.gate_status === 'pass' ? 'badge-down' : 'badge-warn'}>Gate {c.gate_status}</Badge>
          <Badge tone="badge-accent">{c.research_priority}</Badge>
          <Badge tone="badge-dim">{c.status}</Badge>
        </div>
      </div>
      <div className="card-body">
        <div className="grid" style={{ gridTemplateColumns: 'minmax(0, 1.2fr) minmax(260px, 0.8fr)', gap: 14 }}>
          <div>
            <p style={{ margin: 0, fontSize: 16, lineHeight: 1.6, fontWeight: 620 }}>{c.thesis}</p>
            <div className="grid" style={{ gridTemplateColumns: 'repeat(auto-fit, minmax(128px, 1fr))', gap: 8, marginTop: 14 }}>
              <Metric label="官方动作" value={signal?.recommendation || '暂无'} tone={signal ? pnlClass(signal.composite_score) : ''} />
              <Metric label="最终仓位" value={finalPosition || '-'} />
              <Metric label="下一次复盘" value={c.next_review} />
              <Metric label="记忆候选" value={c.artifacts.filter((a) => /memory/.test(a)).length} tone="warn" />
            </div>
            <div className="grid" style={{ gridTemplateColumns: 'repeat(auto-fit, minmax(150px, 1fr))', gap: 8, marginTop: 14 }}>
              {c.loop.map(([label, text], i) => (
                <div key={label} className="glass-inset" style={{ padding: '11px 13px' }}>
                  <div className="row" style={{ gap: 7 }}>
                    <span className="badge badge-accent t-num" style={{ padding: '1px 7px' }}>{i + 1}</span>
                    <span style={{ fontSize: 13, fontWeight: 650 }}>{label}</span>
                  </div>
                  <div className="t-dim" style={{ marginTop: 7, fontSize: 12.5, lineHeight: 1.5 }}>{text}</div>
                </div>
              ))}
            </div>
          </div>
          <div className="grid" style={{ gap: 10, alignContent: 'start' }}>
            <div className="glass-inset" style={{ padding: 13 }}>
              <div className="t-eyebrow">来源结构</div>
              <div className="grid" style={{ gap: 7, marginTop: 10 }}>
                {c.source_mix.map(([tier, n]) => (
                  <div key={tier} className="row" style={{ gap: 8 }}>
                    <span className="t-num t-faint" style={{ width: 74, fontSize: 11.5 }}>{tier}</span>
                    <div style={{ flex: 1, height: 7, borderRadius: 999, background: 'var(--chip-bg)' }}>
                      <div style={{ width: `${(n / sourceTotal) * 100}%`, height: '100%', borderRadius: 999, background: tier === 'social_lead' ? 'var(--warn)' : 'var(--accent)' }}></div>
                    </div>
                    <span className="t-num" style={{ fontSize: 11.5 }}>{n}</span>
                  </div>
                ))}
              </div>
            </div>
            <div className="glass-inset" style={{ padding: 13 }}>
              <div className="t-eyebrow">反方问题</div>
              <ul style={{ margin: '8px 0 0', padding: 0, listStyle: 'none', display: 'grid', gap: 7 }}>
                {c.questions.map((q) => (
                  <li key={q} className="row" style={{ alignItems: 'flex-start', gap: 7, fontSize: 12.5, lineHeight: 1.5, color: 'var(--ink-2)' }}>
                    <span className="down" style={{ fontSize: 10, marginTop: 3 }}>✕</span><span>{q}</span>
                  </li>
                ))}
              </ul>
            </div>
            <div className="row" style={{ flexWrap: 'wrap', gap: 6 }}>
              {c.artifacts.map((a) => <Badge key={a} tone="badge-dim">{a}</Badge>)}
            </div>
          </div>
        </div>
      </div>
    </section>
  );
}

function LongTermPanel({ stock }: any) {
  const [busy, setBusy] = useSState(false);
  const [notice, setNotice] = useSState('');
  const label = stock.long_term_label;
  async function review() {
    setBusy(true);
    setNotice('');
    try {
      await reviewLatestSignal(stock.symbol);
      setNotice('最新信号复盘已完成，研究状态已由后端更新。');
      toast('复盘完成，结果已写入研究状态');
    } catch (error: any) {
      toast(`复盘失败:${error?.message || '后端错误'}`);
    } finally {
      setBusy(false);
    }
  }
  return (
    <Card eyebrow="长期标签 / 信号复盘" title="长期标签如何约束短线动作" tour="long-term"
      right={<button className="btn btn-sm" disabled={busy} onClick={review}>{busy ? '复盘中…' : '复盘最新信号'}</button>}>
      <div className="grid" style={{ gridTemplateColumns: 'repeat(auto-fit, minmax(240px, 1fr))', gap: 10 }}>
        <div className="glass-inset" style={{ padding: 13 }}>
          <div className="t-eyebrow">长期观点</div>
          {label ? (
            <div>
              <div className="row" style={{ marginTop: 9, flexWrap: 'wrap', gap: 6 }}>
                <Badge tone={ltTone(label.label)}>{label.label}</Badge>
                <Badge tone={label.constraint_eligible ? 'badge-accent' : 'badge-warn'}>
                  {label.constraint_eligible ? '已通过质量门，可约束官方动作' : '证据不足，仅展示不约束'}
                </Badge>
                <span className={`t-num ${pnlClass(label.score)}`} style={{ fontSize: 14, fontWeight: 650 }}>{fmt.signed(label.score)}</span>
              </div>
              <div className="t-num t-faint" style={{ fontSize: 11.5, marginTop: 9 }}>{label.date} · 有效至 {label.expires_at}</div>
              {label.quality_notes && <div className="t-faint" style={{ fontSize: 11.5, marginTop: 4 }}>{label.quality_notes.join(' / ')}</div>}
            </div>
          ) : (
            <div className="t-dim" style={{ marginTop: 9, fontSize: 13 }}>暂无有效长期标签。在 AI 对话中运行「长期研究团队」可生成。</div>
          )}
        </div>
        <div className="glass-inset" style={{ padding: 13 }}>
          <div className="t-eyebrow">关键发现</div>
          <div className="grid" style={{ gap: 7, marginTop: 8 }}>
            {(label?.key_findings || ['等待长期分析师团队生成后补充。']).slice(0, 3).map((k, i) => (
              <div key={i} style={{ fontSize: 13, lineHeight: 1.55, color: 'var(--ink-2)', paddingLeft: 10, borderLeft: '2px solid var(--accent)' }}>{k}</div>
            ))}
          </div>
        </div>
      </div>
      {notice && <div className="badge badge-accent" style={{ marginTop: 12, padding: '6px 12px', whiteSpace: 'normal' }}>{notice}</div>}
    </Card>
  );
}

function DossierPanel({ symbol, signal }: any) {
  const d = pick(window.MC_DATA.DOSSIER, symbol);
  return (
    <Card eyebrow="研究档案" title="仓位裁决案卷" right={signal && <Badge tone={recTone(signal.recommendation)}>{signal.recommendation}</Badge>}>
      <div className="grid" style={{ gridTemplateColumns: 'repeat(auto-fit, minmax(170px, 1fr))', gap: 10 }}>
        <div className="glass-inset" style={{ padding: 13 }}>
          <div className="t-eyebrow">最终仓位</div>
          <div className="t-num" style={{ marginTop: 5, fontSize: 21, fontWeight: 700 }}>{d.final_position}</div>
          {d.trader_position !== '-' && <div className="t-faint" style={{ fontSize: 11.5, marginTop: 2 }}>单股原始 {d.trader_position}</div>}
        </div>
        <div className="glass-inset" style={{ padding: 13 }}>
          <div className="t-eyebrow">约束状态</div>
          <div style={{ marginTop: 6, fontSize: 13, fontWeight: 550 }}>{d.constrained}</div>
          <div className="t-faint" style={{ fontSize: 11.5, marginTop: 2 }}>约束 {d.constraint_count} · 冲突 {d.conflict_count}</div>
        </div>
        <div className="glass-inset" style={{ padding: 13 }}>
          <div className="t-eyebrow">深度研究</div>
          <div style={{ marginTop: 6, fontSize: 13, fontWeight: 550 }}>{d.deep_research_count ? `${d.deep_research_count} 条研究索引` : '暂无深度研究索引'}</div>
          {d.first_deep_research && <div className="t-faint" style={{ fontSize: 11.5, marginTop: 2, display: '-webkit-box', WebkitLineClamp: 2, WebkitBoxOrient: 'vertical', overflow: 'hidden' }}>{d.first_deep_research}</div>}
        </div>
      </div>
      {(d.conflicts.length > 0 || d.constraints.length > 0) && (
        <div className="grid" style={{ gap: 7, marginTop: 12 }}>
          {d.conflicts.map((c, i) => (
            <div key={`c${i}`} className="badge badge-warn" style={{ padding: '8px 13px', whiteSpace: 'normal', borderRadius: 11, fontSize: 12.5 }}>⚠ {c.summary}</div>
          ))}
          {d.constraints.map((c, i) => (
            <div key={`k${i}`} className="glass-inset" style={{ padding: '8px 13px', fontSize: 12.5, color: 'var(--ink-2)' }}>{c.summary}</div>
          ))}
        </div>
      )}
    </Card>
  );
}

function CopilotCard({ symbol }: any) {
  const [busy, setBusy] = useSState(false);
  const [refreshed, setRefreshed] = useSState(false);
  const c = pick(window.MC_DATA.COPILOT, symbol);
  const toneMap = { support: 'badge-up', caution: 'badge-warn', oppose: 'badge-down', neutral: 'badge-dim' };
  async function refresh() {
    setBusy(true);
    try {
      await refreshResearchCopilot(symbol);
      setRefreshed(true);
      toast('副驾驶影子意见已由后端刷新');
    } catch (error: any) {
      toast(`副驾驶刷新失败:${error?.message || '后端错误'}`);
    } finally {
      setBusy(false);
    }
  }
  return (
    <Card eyebrow="LLM 副驾驶 · 影子轨" title="副驾驶影子意见，不覆盖官方" tour="copilot"
      right={<button className="btn btn-sm" disabled={busy} onClick={refresh}>{busy ? '生成中…' : refreshed ? '重新生成' : '刷新副驾驶'}</button>}>
      <div className="row" style={{ flexWrap: 'wrap', gap: 6 }}>
        <Badge tone={toneMap[c.stanceTone]}>影子立场:{c.stance}</Badge>
        {c.conflict && <Badge tone="badge-warn">{c.conflict}</Badge>}
        <Badge tone="badge-dim">不覆盖官方信号</Badge>
      </div>
      <p style={{ margin: '12px 0 0', fontSize: 13.5, lineHeight: 1.65, color: 'var(--ink-2)' }}>{c.summary}</p>
      <div className="grid" style={{ gridTemplateColumns: 'repeat(auto-fit, minmax(220px, 1fr))', gap: 10, marginTop: 14 }}>
        <div className="glass-inset" style={{ padding: 13 }}>
          <div className="t-eyebrow">影子仓位</div>
          <div className="t-num" style={{ marginTop: 4, fontSize: 15, fontWeight: 650 }}>{c.shadow_position}</div>
          <div className="t-faint" style={{ fontSize: 11.5, marginTop: 2 }}>{c.position_note}</div>
        </div>
        <div className="glass-inset" style={{ padding: 13 }}>
          <div className="t-eyebrow">事件与技术解读</div>
          <div style={{ fontSize: 12.5, lineHeight: 1.55, marginTop: 5, color: 'var(--ink-2)' }}>{c.event_read}</div>
          <div className="t-faint" style={{ fontSize: 12, marginTop: 4 }}>{c.technical_read}</div>
        </div>
      </div>
      <div className="grid" style={{ gridTemplateColumns: 'repeat(auto-fit, minmax(220px, 1fr))', gap: 10, marginTop: 10 }}>
        <div className="glass-inset" style={{ padding: 13 }}>
          <div className="t-eyebrow">风险 / 证伪条件</div>
          <ul style={{ margin: '6px 0 0', paddingLeft: 16, fontSize: 12.5, lineHeight: 1.6, color: 'var(--ink-2)' }}>
            {c.risks.map((r, i) => <li key={i}>{r}</li>)}
          </ul>
        </div>
        <div className="glass-inset" style={{ padding: 13 }}>
          <div className="t-eyebrow">下一步研究</div>
          <ul style={{ margin: '6px 0 0', paddingLeft: 16, fontSize: 12.5, lineHeight: 1.6, color: 'var(--ink-2)' }}>
            {c.next_steps.map((r, i) => <li key={i}>{r}</li>)}
          </ul>
        </div>
      </div>
    </Card>
  );
}

function EvidencePanel({ symbol }: any) {
  const items = pick(window.MC_DATA.EVIDENCE, symbol);
  const KIND = { decision_run: '决策运行', news_audit: '新闻审计', risk_check: '风控检查', lookahead: '反穿越' };
  return (
    <Card eyebrow="Evidence" title="证据链与反穿越检查" tour="evidence" right={<Badge tone="badge-dim">{items.length} 条</Badge>}>
      <div className="grid" style={{ gap: 0 }}>
        {items.map((e, i) => (
          <div key={e.id} className="row" style={{ alignItems: 'flex-start', gap: 12, padding: '11px 0', borderBottom: i < items.length - 1 ? '1px solid var(--hairline-soft)' : 'none' }}>
            <span className="t-num t-faint" style={{ fontSize: 11.5, width: 74, flex: 'none', marginTop: 3 }}>{e.date}</span>
            <Badge tone={e.status === 'pass' ? 'badge-down' : 'badge-warn'}>{e.status === 'pass' ? '通过' : '需复核'}</Badge>
            <div style={{ minWidth: 0 }}>
              <div style={{ fontSize: 13, fontWeight: 600 }}>{KIND[e.kind] || e.kind} · {e.title}</div>
              <div className="t-dim" style={{ fontSize: 12.5, marginTop: 2, lineHeight: 1.55 }}>{e.detail}</div>
            </div>
          </div>
        ))}
      </div>
    </Card>
  );
}

function EvalPanel({ symbol }: any) {
  const [days, setDays] = useSState(60);
  const ev = pick(window.MC_DATA.EVAL, symbol);
  const scale = days / 60;
  const total = Math.max(2, Math.round(ev.total * scale));
  const hit = Math.max(1, Math.round(ev.hit * scale));
  return (
    <Card eyebrow="Signal Eval" title="历史信号归因"
      right={<Seg value={days} options={[[30, '30天'], [60, '60天'], [90, '90天']]} onChange={setDays} />}>
      <div className="grid" style={{ gridTemplateColumns: 'repeat(auto-fit, minmax(120px, 1fr))', gap: 8 }}>
        <Metric label="信号数" value={total} />
        <Metric label="命中" value={hit} />
        <Metric label="胜率" value={`${(hit / total * 100).toFixed(1)}%`} tone={hit / total >= 0.5 ? 'up' : 'down'} />
        <Metric label="平均盈利" value={fmt.signedPct(ev.avg_gain)} tone="up" />
        <Metric label="平均亏损" value={fmt.signedPct(ev.avg_loss)} tone="down" />
      </div>
      <div className="grid" style={{ gridTemplateColumns: '1fr 1fr', gap: 8, marginTop: 10 }}>
        <div className="glass-inset" style={{ padding: '9px 13px', fontSize: 12.5 }}>
          <span className="t-faint">最佳:</span> <span className="up t-num">{ev.best}</span>
        </div>
        <div className="glass-inset" style={{ padding: '9px 13px', fontSize: 12.5 }}>
          <span className="t-faint">最差:</span> <span className="down t-num">{ev.worst}</span>
        </div>
      </div>
      <p className="t-faint" style={{ margin: '10px 0 0', fontSize: 12 }}>{ev.note} 历史表现不代表未来，仅用于理解信号偏差。</p>
    </Card>
  );
}

function HistoryPanel({ symbol, score }: any) {
  const items = window.MC_DATA.mkHistory(symbol, score);
  return (
    <Card eyebrow="History" title="历史信号" pad={false}>
      <div>
        {items.map((it, i) => (
          <div key={i} className="row" style={{ padding: '10px 18px', gap: 14, borderBottom: i < items.length - 1 ? '1px solid var(--hairline-soft)' : 'none' }}>
            <span className="t-num t-faint" style={{ fontSize: 12, width: 78, flex: 'none' }}>{it.date}</span>
            <Badge tone={recTone(it.recommendation)}>{it.recommendation}</Badge>
            <div style={{ flex: 1 }}><ScoreBar score={it.composite_score} height={4} /></div>
            <span className={`t-num ${pnlClass(it.composite_score)}`} style={{ fontSize: 13, fontWeight: 650, width: 52, textAlign: 'right' }}>{fmt.signed(it.composite_score)}</span>
          </div>
        ))}
      </div>
    </Card>
  );
}

function NewsSidebar({ symbol }: any) {
  const news = window.MC_DATA.NEWS[symbol] || window.MC_DATA.NEWS._default;
  return (
    <Card eyebrow="News · 48h" title="来源审计后的新闻情绪" pad={false} tour="news"
      right={<RefreshButton toastMsg={`新闻已刷新`} />}>
      <div>
        {news.map((n, i) => (
          <div key={i} style={{ padding: '13px 18px', borderBottom: i < news.length - 1 ? '1px solid var(--hairline-soft)' : 'none' }}>
            <div style={{ fontSize: 13, fontWeight: 570, lineHeight: 1.5 }}>{n.title}</div>
            <div className="row" style={{ marginTop: 7, gap: 8, flexWrap: 'wrap' }}>
              <span className="t-faint" style={{ fontSize: 11.5 }}>{n.source} · {n.published_at.slice(5)}</span>
              <Badge tone={n.sentiment > 0.2 ? 'badge-up' : n.sentiment < -0.2 ? 'badge-down' : 'badge-dim'}>
                情绪 {fmt.signed(n.sentiment, 2)}
              </Badge>
              {n.audit === 'warning' && <Badge tone="badge-warn">传闻待证</Badge>}
            </div>
          </div>
        ))}
        <div style={{ padding: '11px 18px' }} className="t-faint">
          <span style={{ fontSize: 11.5 }}>新闻经来源审计后才参与情绪分;传闻类不加分。DB 新闻不足时由 Tavily 补充(需 Key)。</span>
        </div>
      </div>
    </Card>
  );
}

function AnalysisPanel({ symbol }: any) {
  const text = window.MC_DATA.ANALYSIS[symbol] || window.MC_DATA.ANALYSIS._default;
  return (
    <Card eyebrow="Analysis" title="裁决摘要" tour="analysis">
      <Markdown text={text} />
      <p className="t-faint" style={{ margin: '12px 0 0', fontSize: 11.5, lineHeight: 1.55 }}>
        分析为研究记录，综合官方信号、证据链与新闻情绪整理，不构成投资建议。
      </p>
    </Card>
  );
}

function ShortTermSignalPanel({ symbol, signal }: any) {
  const f = pick(window.MC_DATA.SIGNAL_FACTORS, symbol);
  if (!signal) return null;
  return (
    <Card eyebrow="短期信号 · 因子分解" title="短线证据如何进入裁决"
      right={<Badge tone={pnlClass(signal.composite_score)}>综合 {fmt.signed(signal.composite_score)}</Badge>}>
      <div className="grid" style={{ gridTemplateColumns: 'repeat(auto-fit, minmax(260px, 1fr))', gap: 16 }}>
        <div>
          <div className="t-eyebrow">技术因子(权重 0.6)</div>
          <div className="grid" style={{ gap: 0, marginTop: 4 }}>
            {f.technical.map((t, i) => (
              <div key={i} className="row" style={{ justifyContent: 'space-between', gap: 10, padding: '9px 0', borderBottom: i < f.technical.length - 1 ? '1px solid var(--hairline-soft)' : 'none' }}>
                <div style={{ minWidth: 0 }}>
                  <div style={{ fontSize: 13, fontWeight: 550 }}>{t.name}</div>
                  <div className="t-faint" style={{ fontSize: 11.5, marginTop: 1 }}>{t.note}</div>
                </div>
                <div className="row" style={{ gap: 10, flex: 'none' }}>
                  <span className="t-num t-faint" style={{ fontSize: 12.5 }}>{t.value}</span>
                  <span className={`t-num ${pnlClass(t.score)}`} style={{ fontSize: 13, fontWeight: 650, width: 34, textAlign: 'right' }}>{fmt.signed(t.score)}</span>
                </div>
              </div>
            ))}
          </div>
        </div>
        <div>
          <div className="t-eyebrow">情感构成(权重 0.4)</div>
          <div className="glass-inset" style={{ padding: 13, marginTop: 4 }}>
            <div className="spread"><span style={{ fontSize: 13, fontWeight: 550 }}>情感分(−1 / +1)</span><span className={`t-num ${pnlClass(f.sentiment.score)}`} style={{ fontSize: 17, fontWeight: 700 }}>{fmt.signed(f.sentiment.score, 2)}</span></div>
            <div className="row" style={{ gap: 6, marginTop: 11, flexWrap: 'wrap' }}>
              <Badge tone="badge-up">利好 {f.sentiment.positive}</Badge>
              <Badge tone="badge-dim">中性 {f.sentiment.neutral}</Badge>
              {f.sentiment.warning > 0 && <Badge tone="badge-warn">传闻 {f.sentiment.warning}</Badge>}
              <Badge tone="badge-dim">影响 {f.sentiment.impact}</Badge>
            </div>
            <div className="t-dim" style={{ fontSize: 12, marginTop: 11, lineHeight: 1.5 }}>{f.sentiment.note}</div>
          </div>
        </div>
      </div>
      <div className="glass-inset" style={{ padding: '10px 13px', marginTop: 12, fontSize: 12, fontFamily: 'var(--font-mono)', color: 'var(--ink-2)', lineHeight: 1.5 }}>{f.formula}</div>
    </Card>
  );
}

function FinancialsPanel({ symbol }: any) {
  const fin = pick(window.MC_DATA.FINANCIALS, symbol);
  return (
    <Card eyebrow="公司财务状况" title="质量 · 成长 · 估值" tour="financials"
      right={<Badge tone={fin.quality === 'pass' ? 'badge-up' : 'badge-warn'}>{fin.quality === 'pass' ? `财务完整 ${fin.years} 年` : '证据不足'}</Badge>}>
      <div className="grid" style={{ gridTemplateColumns: 'repeat(auto-fit, minmax(148px, 1fr))', gap: 8 }}>
        {fin.metrics.map(([l, v, sub, tone], i) => (
          <div key={i} className="glass-inset" style={{ padding: '10px 13px' }}>
            <div className="t-eyebrow">{l}</div>
            <div className={`t-num ${tone}`} style={{ fontSize: 17, fontWeight: 700, marginTop: 3 }}>{v}</div>
            <div className="t-faint" style={{ fontSize: 11, marginTop: 1 }}>{sub}</div>
          </div>
        ))}
      </div>
      {fin.rows.length > 0 && (
        <div style={{ marginTop: 14, overflowX: 'auto' }}>
          <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 12.5 }}>
            <thead>
              <tr style={{ color: 'var(--ink-3)', textAlign: 'right' }}>
                <th style={{ textAlign: 'left', fontWeight: 550, padding: '6px 8px' }}>年度</th>
                <th style={{ fontWeight: 550, padding: '6px 8px' }}>营收(亿)</th>
                <th style={{ fontWeight: 550, padding: '6px 8px' }}>净利(亿)</th>
                <th style={{ fontWeight: 550, padding: '6px 8px' }}>ROE</th>
                <th style={{ fontWeight: 550, padding: '6px 8px' }}>毛利率</th>
              </tr>
            </thead>
            <tbody>
              {fin.rows.map((r, i) => (
                <tr key={i} style={{ borderTop: '1px solid var(--hairline-soft)', textAlign: 'right' }}>
                  <td className="t-num" style={{ textAlign: 'left', fontWeight: 600, padding: '8px' }}>{r.year}</td>
                  <td className="t-num" style={{ padding: '8px' }}>{r.revenue}</td>
                  <td className="t-num" style={{ padding: '8px' }}>{r.profit}</td>
                  <td className="t-num up" style={{ padding: '8px' }}>{r.roe}%</td>
                  <td className="t-num" style={{ padding: '8px' }}>{r.margin}%</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      <div className="grid" style={{ gap: 7, marginTop: 12 }}>
        <div className="glass-inset" style={{ padding: '9px 13px', fontSize: 12.5, color: 'var(--ink-2)', lineHeight: 1.5 }}><b style={{ color: 'var(--ink)' }}>现金流</b> · {fin.cash_flow}</div>
        <div className="glass-inset" style={{ padding: '9px 13px', fontSize: 12.5, color: 'var(--ink-2)', lineHeight: 1.5 }}><b style={{ color: 'var(--ink)' }}>QFII</b> · {fin.qfii}</div>
      </div>
    </Card>
  );
}

function StockTile({ s }: any) {
  const sig = s.latest_signal;
  return (
    <a className="glass-inset stock-tile" onClick={() => navigate(`/stock/${s.symbol}`)}>
      <div className="spread" style={{ alignItems: 'flex-start' }}>
        <div style={{ minWidth: 0 }}>
          <div style={{ fontSize: 14, fontWeight: 650, whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>{s.name}</div>
          <div className="t-num t-faint" style={{ fontSize: 11.5, marginTop: 1 }}>{s.symbol} · {s.industry || MKT[s.market]}</div>
        </div>
        {sig ? <Badge tone={recTone(sig.recommendation)}>{sig.recommendation}</Badge> : <Badge tone="badge-dim">{MKT[s.market]}</Badge>}
      </div>
      <div className="spread" style={{ marginTop: 12, alignItems: 'flex-end' }}>
        {sig ? <span className={`t-num ${pnlClass(sig.composite_score)}`} style={{ fontSize: 22, fontWeight: 700 }}>{fmt.signed(sig.composite_score)}</span>
          : <span className="t-faint" style={{ fontSize: 12 }}>observe-only</span>}
        <div style={{ textAlign: 'right' }}>
          <Spark symbol={s.symbol} />
          {dailyChangePct(s.symbol) != null && (
            <div className={`t-num ${pnlClass(dailyChangePct(s.symbol))}`} style={{ fontSize: 11.5, fontWeight: 650 }}>{fmt.signedPct(dailyChangePct(s.symbol))}</div>
          )}
        </div>
      </div>
      {s.long_term_label && (
        <div className="spread" style={{ marginTop: 10, paddingTop: 8, borderTop: '1px solid var(--hairline-soft)' }}>
          <span className="t-faint" style={{ fontSize: 11.5 }}>长期标签</span>
          <Badge tone={ltTone(s.long_term_label.label)}>{s.long_term_label.label}</Badge>
        </div>
      )}
    </a>
  );
}

// 列表行视图:一行一条,补上涨跌、止损止盈与长期标签信息
function StockRow({ s }: any) {
  const sig = s.latest_signal;
  const chg = dailyChangePct(s.symbol);
  return (
    <a className="row" style={{ padding: '9px 14px', gap: 12, cursor: 'pointer', textDecoration: 'none', color: 'inherit' }} onClick={() => navigate(`/stock/${s.symbol}`)}>
      <div style={{ width: 132, flex: 'none', minWidth: 0 }}>
        <div style={{ fontSize: 13, fontWeight: 600, whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>{s.name}</div>
        <div className="t-num t-faint" style={{ fontSize: 11 }}>{s.symbol}</div>
      </div>
      <span className="t-faint" style={{ width: 116, flex: 'none', fontSize: 11.5, whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>{s.industry || MKT[s.market]}</span>
      <span style={{ width: 84, flex: 'none' }}>
        {sig ? <Badge tone={recTone(sig.recommendation)}>{sig.recommendation}</Badge> : <Badge tone="badge-dim">{MKT[s.market]}</Badge>}
      </span>
      <span className={`t-num ${sig ? pnlClass(sig.composite_score) : 't-faint'}`} style={{ width: 52, flex: 'none', fontSize: 14, fontWeight: 700, textAlign: 'right' }}>
        {sig ? fmt.signed(sig.composite_score) : '–'}
      </span>
      <span className={`t-num ${chg != null ? pnlClass(chg) : 't-faint'}`} style={{ width: 62, flex: 'none', fontSize: 12.5, fontWeight: 650, textAlign: 'right' }}>{chg != null ? fmt.signedPct(chg) : '–'}</span>
      <div style={{ flex: 1, minWidth: 50 }}>{sig ? <ScoreBar score={sig.composite_score} height={4} /> : null}</div>
      <span className="t-num t-faint" style={{ fontSize: 11.5, width: 138, flex: 'none', textAlign: 'right' }}>
        {sig ? `损 ${fmt.price(sig.stop_loss)} / 盈 ${fmt.price(sig.take_profit)}` : 'observe-only'}
      </span>
      <span style={{ width: 86, flex: 'none', textAlign: 'right' }}>
        {s.long_term_label ? <Badge tone={ltTone(s.long_term_label.label)}>{s.long_term_label.label}</Badge> : <span className="t-faint" style={{ fontSize: 11 }}>无长期标签</span>}
      </span>
    </a>
  );
}

// 股票池卡片:卡片头部自带排序标签 + 筛选按钮,内容用 PoolShell 收起/展开
function StockPoolCard({ eyebrow, title, items, defaultCount = 8, extraRight = null, empty = null, className = '' }: any) {
  const [sort, onSort] = useSortCtl();
  const f = useStockPoolFilter(items);
  return (
    <Card eyebrow={eyebrow} title={title} className={className}
      right={
        <div className="row" style={{ gap: 8, flexWrap: 'wrap', justifyContent: 'flex-end' }}>
          <SortSeg sort={sort} onSort={onSort} />
          {f.button}
          {extraRight}
        </div>
      }>
      {f.bar}
      {items.length === 0 ? (empty || <div className="empty">暂无标的。</div>) : (
        <PoolShell items={applyPoolSort(f.filtered, sort)} defaultCount={defaultCount} unit="只" cardMin={220}
          empty={<div className="empty">没有匹配的标的，试试清除筛选条件。</div>}
          renderCard={(s) => <StockTile key={s.symbol} s={s} />}
          renderRow={(s) => <StockRow key={s.symbol} s={s} />} />
      )}
    </Card>
  );
}

export function StocksPage() {
  const [state] = useStore();
  const [q, setQ] = useSState('');
  const [market, setMarket] = useSState('all');
  const watch = state.watchlist;
  const pool = React.useMemo(() => window.MC_DATA.SEARCH_POOL.map((s) => {
    const w = watch.find((x) => x.symbol === s.symbol);
    return w ? { ...s, ...w } : s;
  }), [watch]);
  const ql = q.trim().toLowerCase();
  const match = (s) => (market === 'all' || s.market === market) && (!ql || s.symbol.toLowerCase().includes(ql) || s.name.toLowerCase().includes(ql) || (s.industry || '').toLowerCase().includes(ql));
  const filtered = pool.filter(match);
  const watchSyms = new Set(watch.map((w) => w.symbol));
  const watchFiltered = watch.filter(match);
  const otherFiltered = filtered.filter((s) => !watchSyms.has(s.symbol));
  return (
    <div className="grid" style={{ gap: 14 }}>
      <PageHead eyebrow="Stocks" title="个股案卷"
        desc="搜索任意 A股 / 港股 / 美股，进入个股案卷查看裁决、证据链、来源审计、复盘记忆与 observe-only 边界。"
        right={<RefreshButton label="刷新行情" toastMsg="自选与候选池行情已刷新" />} />
      <Card className="pop pop-1">
        <div className="row" style={{ gap: 10, flexWrap: 'wrap' }}>
          <div className="stocks-search">
            <McIcon name="search" size={18} style={{ color: 'var(--ink-3)' }} />
            <input value={q} onChange={(e) => setQ(e.target.value)} autoFocus
              placeholder="搜索代码或名称，如 300308 / 中际旭创 / 立讯精密"
              onKeyDown={(e) => { if (e.key === 'Enter' && filtered[0]) navigate(`/stock/${filtered[0].symbol}`); }} />
          </div>
          <Seg value={market} options={[['all', '全部'], ['CN', 'A股'], ['HK', '港股'], ['US', '美股']]} onChange={setMarket} />
        </div>
      </Card>

      {ql ? (
        <StockPoolCard eyebrow="搜索结果" title={`${filtered.length} 个匹配`} className="pop pop-1"
          items={filtered} defaultCount={12}
          empty={<div className="empty">没有匹配的标的。试试股票代码(如 300308)或公司名称;回车可直接打开输入的代码。</div>} />
      ) : (
        <React.Fragment>
          <StockPoolCard eyebrow="关注池" title="自选股" className="pop pop-1"
            items={watchFiltered} defaultCount={8}
            extraRight={<button className="btn btn-sm" onClick={() => navigate('/pulse')}>在今日裁决页管理</button>}
            empty={<div className="empty">研究池为空。前往今日裁决页添加，或直接搜索标的研究。</div>} />
          {otherFiltered.length > 0 && (
            <StockPoolCard eyebrow="候选" title="可研究标的" className="pop pop-2"
              items={otherFiltered} defaultCount={8} />
          )}
        </React.Fragment>
      )}
    </div>
  );
}

export function StockPage({ symbol }: any) {
  useStore();
  // live 模式下懒取该股的 K线/新闻/证据/归因/案卷,数据落地后 poke store 重渲染
  useSEffect(() => { if (window.MC_LIVE) window.MC_LIVE.ensureSymbol(symbol); }, [symbol]);
  const stock = getStock(symbol);
  const signal = stock.latest_signal;
  return (
    <div className="grid" style={{ gap: 14 }}>
      <StockHeader stock={stock} signal={signal} />
      <CaseLoopPanel stock={stock} signal={signal} />
      <Card eyebrow="主图 · 120 个交易日" title="价格与风险参考线" className="pop pop-1" tour="chart"
        right={signal && <span className="t-faint" style={{ fontSize: 12 }}>虚线为系统计算的 ATR 止损 / 盈亏比止盈参考</span>}>
        <PriceChart symbol={symbol} signal={signal} />
      </Card>
      {!signal && (
        <div className="empty pop pop-1">
          <b>该标的暂无正式信号。</b>{stock.market !== 'CN' ? ' 港股 / 美股为 observe-only，数据仅用于观察，不进入 CN 官方信号。' : ' 等待下次盘后决策运行。'}
        </div>
      )}
      <div className="grid" style={{ gridTemplateColumns: 'minmax(0, 1fr) 340px', gap: 14 }} data-grid="stock-cols">
        <div className="grid pop pop-2" style={{ gap: 14 }}>
          <AnalysisPanel symbol={symbol} />
          <ShortTermSignalPanel symbol={symbol} signal={signal} />
          <LongTermPanel stock={stock} />
          <DossierPanel symbol={symbol} signal={signal} />
          <FinancialsPanel symbol={symbol} />
          <CopilotCard symbol={symbol} />
          <EvidencePanel symbol={symbol} />
          <EvalPanel symbol={symbol} />
          <HistoryPanel symbol={symbol} score={signal?.composite_score ?? 0} />
        </div>
        <div className="pop pop-2"><NewsSidebar symbol={symbol} /></div>
      </div>
    </div>
  );
}

window.StockPage = StockPage;
window.StocksPage = StocksPage;
