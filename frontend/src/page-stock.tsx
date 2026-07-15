// ============================================================
// 单股详情页 — 信号 / 研究 / 证据 / 新闻
// ============================================================
import React from 'react';
import { refreshResearchCopilot, reviewLatestSignal } from './services/api';
import { Badge, CCY, Card, MCStore, MKT, Markdown, McIcon, Metric, PageHead, PoolShell, PriceChart, RefreshButton, ScoreBar, Seg, SortSeg, Spark, applyPoolSort, assetKey, dailyChangePct, fmt, ltTone, navigate, pnlClass, recTone, scopedData, stockPath, toast, useSortCtl, useStockPoolFilter, useStore } from './shared';
const { useState: useSState, useEffect: useSEffect } = React;

function getStock(symbol, market) {
  const matches = (item) => item.symbol === symbol && (!market || item.market === market);
  return MCStore.get().watchlist.find(matches)
    || window.MC_DATA.SEARCH_POOL.find(matches)
    || { symbol, name: symbol, market: market || 'CN' };
}
function pick(map, symbol, market) { return scopedData(map, symbol, market); }

const MARKET_RULES = {
  CN: { scope: '正式信号', weights: '技术 60% · 情绪 40%', settlement: 'T+1 · 当日买入不可卖', lot: '100 股整手', limit: '涨跌停约束', timezone: 'Asia/Shanghai' },
  HK: { scope: '灰度影子 · 零仓位', weights: '技术 65% · 情绪 35%', settlement: 'T+2 · 可当日卖出', lot: '整手 + 碎股', limit: '无固定日涨跌停', timezone: 'Asia/Hong_Kong' },
  US: { scope: '灰度影子 · 零仓位', weights: '技术 75% · 情绪 25%', settlement: 'T+1 · 可当日卖出', lot: '1 股起 · 支持碎股能力', limit: 'LULD 波动保护', timezone: 'America/New_York' },
};

function StockHeader({ stock, signal }: any) {
  const px = scopedData(window.MC_DATA.PRICES, stock.symbol, stock.market);
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
            {stock.gray && <Badge tone="badge-accent">灰度影子 · 不下单</Badge>}
            {stock.observe && <Badge tone="badge-warn">仅观察</Badge>}
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
                <span className="t-num" style={{ fontSize: 17, fontWeight: 650 }}>{stock.currency || ({ CN: 'CNY', HK: 'HKD', US: 'USD' })[stock.market]} {lastPx.close.toFixed(2)}</span>
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

function MarketRuleStrip({ stock, signal }: any) {
  const rule = MARKET_RULES[stock.market] || MARKET_RULES.CN;
  const scope = stock.market === 'CN' ? rule.scope : (stock.gray ? rule.scope : '仅观察 · 非灰度白名单');
  return (
    <div className="glass-inset pop" style={{ padding: '11px 14px' }} data-testid="market-rule-strip">
      <div className="spread" style={{ gap: 10, flexWrap: 'wrap', alignItems: 'center' }}>
        <div className="row" style={{ gap: 6, flexWrap: 'wrap' }}>
          <Badge tone={stock.market === 'CN' ? 'badge-down' : (stock.gray ? 'badge-accent' : 'badge-warn')}>{scope}</Badge>
          <Badge tone="badge-dim">{MKT[stock.market]} · {stock.currency || CCY[stock.market]}</Badge>
          <Badge tone="badge-dim">{rule.weights}</Badge>
          <Badge tone="badge-dim">quant 0%</Badge>
        </div>
        <div className="t-faint" style={{ fontSize: 11.5 }}>
          {rule.settlement} · {rule.lot} · {rule.limit} · {stock.timezone || rule.timezone}
          {signal?.rule_version ? ` · ${signal.rule_version}` : ''}
        </div>
      </div>
    </div>
  );
}

function CaseLoopPanel({ stock, signal }: any) {
  const c = pick(window.MC_DATA.CASE_LOOP, stock.symbol, stock.market);
  const sourceTotal = c.source_mix.reduce((a, [, n]) => a + n, 0) || 1;
  const finalPosition = pick(window.MC_DATA.DOSSIER, stock.symbol, stock.market).final_position;
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
      right={stock.market === 'CN'
        ? <button className="btn btn-sm" disabled={busy} onClick={review}>{busy ? '复盘中…' : '复盘最新信号'}</button>
        : <Badge tone="badge-accent">灰度只读 · 不写学习记忆</Badge>}>
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

function GraySignalPanel({ stock, signal }: any) {
  const weights = stock.market === 'HK' ? '技术 65% / 情绪 35%' : '技术 75% / 情绪 25%';
  return (
    <Card eyebrow={stock.gray ? 'Gray Signal' : 'Observe Only'} title={stock.gray ? '灰度信号与准入边界' : '观察规则与灰度准入边界'} tour="analysis"
      right={<Badge tone={stock.gray ? 'badge-accent' : 'badge-warn'}>{stock.gray ? '影子 · 仓位 0' : '非白名单 · 无信号'}</Badge>}>
      {signal ? (
        <React.Fragment>
          <div className="grid" style={{ gridTemplateColumns: 'repeat(auto-fit, minmax(135px, 1fr))', gap: 8 }}>
            <Metric label="综合分" value={fmt.signed(signal.composite_score)} tone={pnlClass(signal.composite_score)} sub={signal.recommendation} />
            <Metric label="技术" value={fmt.signed(signal.technical_score)} tone={pnlClass(signal.technical_score)} sub={weights} />
            <Metric label="情绪" value={fmt.signed(signal.sentiment_score, 2)} tone={pnlClass(signal.sentiment_score)} sub="本市场独立提示词与缓存" />
            <Metric label="量化" value="0%" sub="不复用 A 股训练模型" />
          </div>
          <div className="glass-inset" style={{ padding: '10px 13px', marginTop: 10, fontSize: 12.5, lineHeight: 1.6, color: 'var(--ink-2)' }}>
            该信号仅用于港美股灰度研究和回放：不触发提醒、不创建订单、不写真实持仓、不进入 CN 官方信号。
            <div className="t-num t-faint" style={{ marginTop: 5 }}>
              {signal.rule_version || 'market gray rule'} · 数据截止 {signal.data_timestamp || signal.date || '—'}
            </div>
          </div>
        </React.Fragment>
      ) : (
        <div className="empty">该标的当前没有 close-confirmed 灰度信号，继续保持仅观察。</div>
      )}
    </Card>
  );
}

function DossierPanel({ symbol, market, signal }: any) {
  const d = pick(window.MC_DATA.DOSSIER, symbol, market);
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

function CopilotCard({ symbol, market }: any) {
  const [busy, setBusy] = useSState(false);
  const [refreshed, setRefreshed] = useSState(false);
  const c = pick(window.MC_DATA.COPILOT, symbol, market);
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

function EvidencePanel({ symbol, market }: any) {
  const items = pick(window.MC_DATA.EVIDENCE, symbol, market);
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

function EvalPanel({ symbol, market }: any) {
  const [days, setDays] = useSState(60);
  const ev = pick(window.MC_DATA.EVAL, symbol, market);
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

function NewsSidebar({ symbol, market }: any) {
  const news = pick(window.MC_DATA.NEWS, symbol, market);
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

function AnalysisPanel({ symbol, market }: any) {
  const text = pick(window.MC_DATA.ANALYSIS, symbol, market);
  return (
    <Card eyebrow="Analysis" title="裁决摘要" tour="analysis">
      <Markdown text={text} />
      <p className="t-faint" style={{ margin: '12px 0 0', fontSize: 11.5, lineHeight: 1.55 }}>
        分析为研究记录，综合官方信号、证据链与新闻情绪整理，不构成投资建议。
      </p>
    </Card>
  );
}

function ShortTermSignalPanel({ symbol, market, signal }: any) {
  const f = pick(window.MC_DATA.SIGNAL_FACTORS, symbol, market);
  const weights = market === 'HK' ? { technical: 0.65, sentiment: 0.35 } : market === 'US' ? { technical: 0.75, sentiment: 0.25 } : { technical: 0.6, sentiment: 0.4 };
  if (!signal) return null;
  return (
    <Card eyebrow="短期信号 · 因子分解" title="短线证据如何进入裁决"
      right={<Badge tone={pnlClass(signal.composite_score)}>综合 {fmt.signed(signal.composite_score)}</Badge>}>
      <div className="grid" style={{ gridTemplateColumns: 'repeat(auto-fit, minmax(260px, 1fr))', gap: 16 }}>
        <div>
          <div className="t-eyebrow">技术因子(权重 {weights.technical.toFixed(2)})</div>
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
          <div className="t-eyebrow">情感构成(权重 {weights.sentiment.toFixed(2)})</div>
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

function FinancialsPanel({ symbol, market }: any) {
  const fin = pick(window.MC_DATA.FINANCIALS, symbol, market);
  return (
    <Card eyebrow="公司财务状况" title="质量 · 成长 · 估值" tour="financials"
      right={<Badge tone={fin.quality === 'pass' ? 'badge-up' : 'badge-warn'}>{fin.quality === 'pass' ? `财务可用 ${fin.periods || fin.years} 期` : '证据不足'}</Badge>}>
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
                <th style={{ fontWeight: 550, padding: '6px 8px' }}>营收(亿 {CCY[market] || market})</th>
                <th style={{ fontWeight: 550, padding: '6px 8px' }}>净利(亿 {CCY[market] || market})</th>
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
        <div className="glass-inset" style={{ padding: '9px 13px', fontSize: 12.5, color: 'var(--ink-2)', lineHeight: 1.5 }}><b style={{ color: 'var(--ink)' }}>来源与 PIT</b> · {fin.provenance || fin.qfii}</div>
      </div>
    </Card>
  );
}

function StockTile({ s }: any) {
  const sig = s.latest_signal;
  return (
    <a className="glass-inset stock-tile" onClick={() => navigate(stockPath(s.symbol, s.market))}>
      <div className="spread" style={{ alignItems: 'flex-start' }}>
        <div style={{ minWidth: 0 }}>
          <div style={{ fontSize: 14, fontWeight: 650, whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>{s.name}</div>
          <div className="t-num t-faint" style={{ fontSize: 11.5, marginTop: 1 }}>{s.symbol} · {s.industry || MKT[s.market]}</div>
        </div>
        <div className="row" style={{ gap: 5, flexWrap: 'wrap', justifyContent: 'flex-end' }}>
          {s.gray && <Badge tone="badge-accent">影子 · 不下单</Badge>}
          {s.observe && <Badge tone="badge-warn">仅观察</Badge>}
          {sig ? <Badge tone={recTone(sig.recommendation)}>{sig.recommendation}</Badge> : <Badge tone="badge-dim">{MKT[s.market]}</Badge>}
        </div>
      </div>
      <div className="spread" style={{ marginTop: 12, alignItems: 'flex-end' }}>
        {sig ? <span className={`t-num ${pnlClass(sig.composite_score)}`} style={{ fontSize: 22, fontWeight: 700 }}>{fmt.signed(sig.composite_score)}</span>
          : <span className="t-faint" style={{ fontSize: 12 }}>observe-only</span>}
        <div style={{ textAlign: 'right' }}>
          <Spark symbol={s.symbol} market={s.market} />
          {dailyChangePct(s.symbol, s.market) != null && (
            <div className={`t-num ${pnlClass(dailyChangePct(s.symbol, s.market))}`} style={{ fontSize: 11.5, fontWeight: 650 }}>{fmt.signedPct(dailyChangePct(s.symbol, s.market))}</div>
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
  const chg = dailyChangePct(s.symbol, s.market);
  return (
    <a className="row" style={{ padding: '9px 14px', gap: 12, cursor: 'pointer', textDecoration: 'none', color: 'inherit' }} onClick={() => navigate(stockPath(s.symbol, s.market))}>
      <div style={{ width: 132, flex: 'none', minWidth: 0 }}>
        <div style={{ fontSize: 13, fontWeight: 600, whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>{s.name}</div>
        <div className="t-num t-faint" style={{ fontSize: 11 }}>{s.symbol}</div>
      </div>
      <span className="t-faint" style={{ width: 116, flex: 'none', fontSize: 11.5, whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>{s.industry || MKT[s.market]}</span>
      <span className="row" style={{ width: 132, flex: 'none', gap: 5, flexWrap: 'wrap' }}>
        {s.gray && <Badge tone="badge-accent">影子</Badge>}
        {s.observe && <Badge tone="badge-warn">观察</Badge>}
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
          renderCard={(s) => <StockTile key={s.asset_key || assetKey(s.symbol, s.market)} s={s} />}
          renderRow={(s) => <StockRow key={s.asset_key || assetKey(s.symbol, s.market)} s={s} />} />
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
    const w = watch.find((x) => (x.asset_key || assetKey(x.symbol, x.market)) === (s.asset_key || assetKey(s.symbol, s.market)));
    return w ? { ...s, ...w } : s;
  }), [watch]);
  const ql = q.trim().toLowerCase();
  const match = (s) => (market === 'all' || s.market === market) && (!ql || s.symbol.toLowerCase().includes(ql) || s.name.toLowerCase().includes(ql) || (s.industry || '').toLowerCase().includes(ql));
  const filtered = pool.filter(match);
  const watchKeys = new Set(watch.map((w) => w.asset_key || assetKey(w.symbol, w.market)));
  const watchFiltered = watch.filter(match);
  const otherFiltered = filtered.filter((s) => !watchKeys.has(s.asset_key || assetKey(s.symbol, s.market)));
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
              onKeyDown={(e) => { if (e.key === 'Enter' && filtered[0]) navigate(stockPath(filtered[0].symbol, filtered[0].market)); }} />
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

export function StockPage({ symbol, market }: any) {
  useStore();
  // live 模式下懒取该股的 K线/新闻/证据/归因/案卷,数据落地后 poke store 重渲染
  useSEffect(() => { if (window.MC_LIVE) window.MC_LIVE.ensureSymbol(symbol, market); }, [symbol, market]);
  const stock = getStock(symbol, market);
  const signal = stock.latest_signal;
  return (
    <div className="grid" style={{ gap: 14 }}>
      <StockHeader stock={stock} signal={signal} />
      <MarketRuleStrip stock={stock} signal={signal} />
      {stock.market === 'CN' && <CaseLoopPanel stock={stock} signal={signal} />}
      <Card eyebrow="主图 · 120 个交易日" title="价格与风险参考线" className="pop pop-1" tour="chart"
        right={signal && <span className="t-faint" style={{ fontSize: 12 }}>虚线为系统计算的 ATR 止损 / 盈亏比止盈参考</span>}>
        <PriceChart symbol={symbol} market={stock.market} signal={signal} />
      </Card>
      {!signal && (
        <div className="empty pop pop-1">
          <b>该标的暂无信号。</b>{stock.gray ? ' 已进入港美股灰度池，等待本市场收盘确认后的影子信号。' : (stock.market !== 'CN' ? ' 当前仅观察，需进入灰度白名单才会生成影子信号。' : ' 等待下次 A 股盘后决策运行。')}
        </div>
      )}
      <div className="grid" style={{ gridTemplateColumns: 'minmax(0, 1fr) 340px', gap: 14 }} data-grid="stock-cols">
        <div className="grid pop pop-2" style={{ gap: 14 }}>
          {stock.market === 'CN'
            ? <React.Fragment>
                <AnalysisPanel symbol={symbol} market={stock.market} />
                <ShortTermSignalPanel symbol={symbol} market={stock.market} signal={signal} />
              </React.Fragment>
            : <GraySignalPanel stock={stock} signal={signal} />}
          <LongTermPanel stock={stock} />
          {stock.market === 'CN' && <DossierPanel symbol={symbol} market={stock.market} signal={signal} />}
          <FinancialsPanel symbol={symbol} market={stock.market} />
          {stock.market === 'CN' && <CopilotCard symbol={symbol} market={stock.market} />}
          {stock.market === 'CN' && <EvidencePanel symbol={symbol} market={stock.market} />}
          <EvalPanel symbol={symbol} market={stock.market} />
          {stock.market === 'CN' && <HistoryPanel symbol={symbol} score={signal?.composite_score ?? 0} />}
        </div>
        <div className="pop pop-2"><NewsSidebar symbol={symbol} market={stock.market} /></div>
      </div>
    </div>
  );
}

window.StockPage = StockPage;
window.StocksPage = StocksPage;
