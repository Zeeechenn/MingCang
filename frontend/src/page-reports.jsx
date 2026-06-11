// ============================================================
// 证据案卷库 — 汇总跑过的所有案卷:裁决 / 深研闸门 / 复盘 / 盘后导出 / 外部论题
// ============================================================
const { useState: useRepState, useMemo: useRepMemo, useEffect: useRepEffect } = React;

const ROLE_TONE = (score) => (score > 10 ? 'up' : score < -10 ? 'down' : '');
const TIER_LABEL = {
  primary: '一手', official: '官方', filing: '定报', ir: '互动', industry: '行业', social_lead: '传闻',
};
const TIER_TONE = {
  primary: 'badge-down', official: 'badge-down', filing: 'badge-accent', ir: 'badge-warn', industry: 'badge-dim', social_lead: 'badge-warn',
};
const WIN_LABEL = { bull: '多方胜', bear: '空方胜', tie: '平局' };
const WIN_TONE = { bull: 'badge-up', bear: 'badge-down', tie: 'badge-dim' };

// ---------- 多空辩论 · 完整报告(共享:脉冲弹层 + 报告中心) ----------
function DebateReport({ debate }) {
  if (!debate) return <div className="empty">暂无辩论记录。</div>;
  const quick = !debate.rounds || debate.rounds.length === 0;
  const r1 = (debate.rounds || []).find((r) => r.speaker === 'bull');
  const r2 = (debate.rounds || []).find((r) => r.speaker === 'bear');
  const r3 = (debate.rounds || []).find((r) => r.speaker === 'adjudicator');

  return (
    <div className="grid" style={{ gap: 16 }}>
      <div className="row" style={{ flexWrap: 'wrap', gap: 8 }}>
        <Badge tone="badge-accent">研究总监</Badge>
        <Badge tone={debate.used_llm ? 'badge-up' : 'badge-dim'}>{debate.used_llm ? `${debate.round_count} 轮辩论 · 用 LLM` : '快速共识 · 零 LLM'}</Badge>
        <span className="t-faint" style={{ fontSize: 12 }}>标的 {debate.name} {debate.symbol} · {debate.date}</span>
      </div>

      {/* 四路分析师 */}
      <div>
        <div className="t-eyebrow" style={{ marginBottom: 8 }}>四路分析师并行打分</div>
        <div className="grid" style={{ gridTemplateColumns: 'repeat(auto-fit, minmax(150px, 1fr))', gap: 8 }}>
          {debate.analysts.map((a) => (
            <div key={a.key} className="glass-inset" style={{ padding: '11px 13px' }}>
              <div className="spread">
                <span style={{ fontSize: 13, fontWeight: 650 }}>{a.role}</span>
                <span className={`t-num ${ROLE_TONE(a.score)}`} style={{ fontSize: 15, fontWeight: 700 }}>{fmt.signed(a.score)}</span>
              </div>
              <div className="t-faint" style={{ fontSize: 11, marginTop: 2 }}>置信 {a.confidence.toFixed(2)}</div>
              <div style={{ marginTop: 7 }}><ScoreBar score={a.score} height={4} /></div>
              <ul style={{ margin: '9px 0 0', padding: 0, listStyle: 'none', display: 'grid', gap: 4 }}>
                {a.findings.map((f, i) => (
                  <li key={i} className="t-dim" style={{ fontSize: 11.5, lineHeight: 1.45, paddingLeft: 9, position: 'relative' }}>
                    <span style={{ position: 'absolute', left: 0, opacity: 0.5 }}>·</span>{f}
                  </li>
                ))}
              </ul>
            </div>
          ))}
        </div>
      </div>

      {/* 研究总监议题 */}
      <div className="glass-inset" style={{ padding: '13px 15px' }}>
        <div className="spread" style={{ flexWrap: 'wrap', gap: 8 }}>
          <div className="t-eyebrow">研究总监 · 质量评估与议题</div>
          <div className="row" style={{ gap: 6 }}>
            <Badge tone="badge-dim">分歧 σ {debate.director.score_stdev}</Badge>
            <Badge tone={debate.director.diverged ? 'badge-warn' : 'badge-dim'}>{debate.director.diverged ? '达辩论阈值' : '方向一致'}</Badge>
          </div>
        </div>
        {debate.director.debate_topic ? (
          <p style={{ margin: '9px 0 0', fontSize: 13, lineHeight: 1.6, color: 'var(--ink-2)' }}>
            <span style={{ color: 'var(--accent-ink)', fontWeight: 650, marginRight: 6 }}>议题</span>{debate.director.debate_topic}
          </p>
        ) : (
          <p className="t-dim" style={{ margin: '9px 0 0', fontSize: 13 }}>未达辩论阈值,研究员快速达成共识,不下达议题。</p>
        )}
        {debate.director.quality_notes && debate.director.quality_notes.length > 0 && (
          <div className="row" style={{ gap: 6, marginTop: 9, flexWrap: 'wrap' }}>
            {debate.director.quality_notes.map((n, i) => <span key={i} className="t-faint" style={{ fontSize: 11.5 }}>· {n}</span>)}
          </div>
        )}
      </div>

      {/* 三轮辩论 */}
      {quick ? (
        <div className="empty">{debate.fallback_reason || '四路方向一致,跳过辩论。'}</div>
      ) : (
        <div className="grid" style={{ gap: 10 }}>
          <div className="t-eyebrow">三轮辩论记录</div>

          {/* Round 1 Bull */}
          {r1 && (
            <div className="glass-inset" style={{ padding: '13px 15px', borderLeft: '3px solid var(--up)' }}>
              <div className="spread">
                <span className="up" style={{ fontSize: 12.5, fontWeight: 700 }}>第 1 轮 · 看多开场</span>
                <span className="t-faint" style={{ fontSize: 11 }}>引用 {r1.key_signal}</span>
              </div>
              <ul style={{ margin: '9px 0 0', padding: 0, listStyle: 'none', display: 'grid', gap: 7 }}>
                {r1.points.map((p, i) => (
                  <li key={i} className="row" style={{ alignItems: 'flex-start', gap: 7, fontSize: 13, lineHeight: 1.55, color: 'var(--ink-2)' }}>
                    <span className="up" style={{ fontSize: 10, marginTop: 3 }}>▲</span><span>{p}</span>
                  </li>
                ))}
              </ul>
            </div>
          )}

          {/* Round 2 Bear */}
          {r2 && (
            <div className="glass-inset" style={{ padding: '13px 15px', borderLeft: '3px solid var(--down)' }}>
              <span className="down" style={{ fontSize: 12.5, fontWeight: 700 }}>第 2 轮 · 看空逐条反驳</span>
              <div className="grid" style={{ gap: 8, marginTop: 9 }}>
                {r2.rebuttals.map((rb, i) => (
                  <div key={i} style={{ fontSize: 12.5, lineHeight: 1.55 }}>
                    <span className="t-faint">针对「{rb.target}」</span>
                    <div className="row" style={{ alignItems: 'flex-start', gap: 7, marginTop: 2, color: 'var(--ink-2)' }}>
                      <span className="down" style={{ fontSize: 10, marginTop: 3 }}>▼</span><span>{rb.counter}</span>
                    </div>
                  </div>
                ))}
              </div>
              {r2.additional && r2.additional.length > 0 && (
                <div style={{ marginTop: 9, paddingTop: 9, borderTop: '1px solid var(--hairline-soft)' }}>
                  <span className="t-faint" style={{ fontSize: 11.5 }}>独立看空理由</span>
                  <ul style={{ margin: '5px 0 0', padding: 0, listStyle: 'none', display: 'grid', gap: 5 }}>
                    {r2.additional.map((a, i) => (
                      <li key={i} className="row" style={{ alignItems: 'flex-start', gap: 7, fontSize: 12.5, lineHeight: 1.5, color: 'var(--ink-2)' }}>
                        <span className="down" style={{ fontSize: 10, marginTop: 3 }}>▼</span><span>{a}</span>
                      </li>
                    ))}
                  </ul>
                </div>
              )}
            </div>
          )}

          {/* Round 3 Adjudication */}
          {r3 && (
            <div className="glass-inset" style={{ padding: '13px 15px', borderLeft: '3px solid var(--accent)' }}>
              <div className="spread" style={{ flexWrap: 'wrap', gap: 8 }}>
                <span style={{ fontSize: 12.5, fontWeight: 700, color: 'var(--accent-ink)' }}>第 3 轮 · 看多回应 + 裁定</span>
                <div className="row" style={{ gap: 6 }}>
                  <Badge tone={WIN_TONE[r3.winning_side]}>{WIN_LABEL[r3.winning_side]}</Badge>
                  <Badge tone={recTone(r3.action_bias)}>{r3.action_bias}</Badge>
                </div>
              </div>
              {r3.bull_response && r3.bull_response.length > 0 && (
                <ul style={{ margin: '9px 0 0', padding: 0, listStyle: 'none', display: 'grid', gap: 6 }}>
                  {r3.bull_response.map((p, i) => (
                    <li key={i} className="row" style={{ alignItems: 'flex-start', gap: 7, fontSize: 12.5, lineHeight: 1.5, color: 'var(--ink-2)' }}>
                      <span className="up" style={{ fontSize: 10, marginTop: 3 }}>▲</span><span>{p}</span>
                    </li>
                  ))}
                </ul>
              )}
              <p style={{ margin: '11px 0 0', fontSize: 13.5, lineHeight: 1.65, color: 'var(--ink)', fontWeight: 500 }}>{r3.rationale}</p>
            </div>
          )}
        </div>
      )}

      {/* 交易员 → 风控 */}
      <div className="grid" style={{ gridTemplateColumns: 'repeat(auto-fit, minmax(220px, 1fr))', gap: 8 }}>
        <div className="glass-inset" style={{ padding: '12px 14px' }}>
          <div className="t-eyebrow">交易员 · 仓位提议</div>
          <div className="t-num" style={{ fontSize: 18, fontWeight: 700, marginTop: 4 }}>{debate.trader.position_pct}%</div>
          <div className="t-dim" style={{ fontSize: 12, marginTop: 4, lineHeight: 1.5 }}>{debate.trader.reasoning}</div>
        </div>
        <div className="glass-inset" style={{ padding: '12px 14px' }}>
          <div className="spread">
            <div className="t-eyebrow">风控 · 最终裁定</div>
            <Badge tone={debate.risk.veto_reason ? 'badge-down' : 'badge-up'}>{debate.risk.veto_reason ? '否决' : '通过'}</Badge>
          </div>
          <div className="row" style={{ gap: 6, marginTop: 4, alignItems: 'baseline' }}>
            <span className="t-faint" style={{ fontSize: 12 }}>{debate.risk.trader_position_pct}% →</span>
            <span className="t-num" style={{ fontSize: 18, fontWeight: 700 }}>{debate.risk.adjusted_position_pct}%</span>
          </div>
          <ul style={{ margin: '7px 0 0', padding: 0, listStyle: 'none', display: 'grid', gap: 4 }}>
            {debate.risk.risk_notes.map((n, i) => (
              <li key={i} className="t-dim" style={{ fontSize: 11.5, lineHeight: 1.45, paddingLeft: 9, position: 'relative' }}>
                <span style={{ position: 'absolute', left: 0, opacity: 0.5 }}>·</span>{n}
              </li>
            ))}
          </ul>
        </div>
      </div>

      <p className="t-faint" style={{ margin: 0, fontSize: 11.5, lineHeight: 1.55 }}>
        多空辩论为研究参考(影子轨),用于暴露分歧;不进入正式信号,不自动下单。
      </p>
    </div>
  );
}

function SourceGateOverview() {
  const G = window.MC_DATA.SOURCE_GATES;
  return (
    <Card eyebrow="ResearchReportGate" title="来源闸门与写入边界" className="pop pop-1"
      right={<Badge tone={G.summary.latest_status === 'pass' ? 'badge-down' : 'badge-warn'}>{G.summary.latest_gate} · {G.summary.latest_status}</Badge>}>
      <div className="grid" style={{ gridTemplateColumns: 'repeat(auto-fit, minmax(150px, 1fr))', gap: 8 }}>
        <Metric label="Pass" value={G.summary.pass} tone="up" />
        <Metric label="Warning" value={G.summary.warning} />
        <Metric label="Blocked" value={G.summary.blocked} tone="down" />
        <Metric label="写入规则" value="blocked=0" sub="不落盘 / 不建记忆" />
      </div>
      <div className="grid" style={{ gridTemplateColumns: 'minmax(0, 1.05fr) minmax(0, 1fr)', gap: 12, marginTop: 14 }} data-grid="review-cols">
        <div className="glass-inset" style={{ padding: 13 }}>
          <div className="t-eyebrow">来源层级</div>
          <div className="grid" style={{ gap: 7, marginTop: 10 }}>
            {G.tiers.map(([key, label, count, note]) => (
              <div key={key} className="spread" style={{ gap: 10 }}>
                <div className="row" style={{ gap: 7, minWidth: 0 }}>
                  <Badge tone={TIER_TONE[key]}>{TIER_LABEL[key] || label}</Badge>
                  <span className="t-dim" style={{ fontSize: 12.5, whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>{note}</span>
                </div>
                <span className="t-num t-faint" style={{ fontSize: 11.5 }}>{count} 源</span>
              </div>
            ))}
          </div>
        </div>
        <div className="glass-inset" style={{ padding: 13 }}>
          <div className="t-eyebrow">写入闸门</div>
          <div className="grid" style={{ gap: 7, marginTop: 10 }}>
            {G.gate_rules.map((r) => (
              <div key={r.rule} className="spread" style={{ gap: 10 }}>
                <div style={{ minWidth: 0 }}>
                  <div style={{ fontSize: 12.5, fontWeight: 620 }}>{r.rule}</div>
                  <div className="t-faint" style={{ fontSize: 11.5, marginTop: 2, lineHeight: 1.45 }}>{r.note}</div>
                </div>
                <Badge tone={r.status === 'pass' ? 'badge-down' : r.status === 'warning' ? 'badge-warn' : 'badge-up'}>{r.status}</Badge>
              </div>
            ))}
          </div>
        </div>
      </div>
    </Card>
  );
}

function ReportGateSnapshot({ status }) {
  return (
    <div className="glass-inset" style={{ padding: '12px 15px' }}>
      <div className="spread" style={{ flexWrap: 'wrap', gap: 8 }}>
        <div className="t-eyebrow">M50 ResearchReportGate / Serenity</div>
        <div className="row" style={{ gap: 6, flexWrap: 'wrap' }}>
          <Badge tone={status === 'pass' ? 'badge-down' : status === 'warning' ? 'badge-warn' : 'badge-up'}>{status}</Badge>
          <Badge tone="badge-dim">observe-only</Badge>
          <Badge tone="badge-dim">no auto memory</Badge>
        </div>
      </div>
      <div className="grid" style={{ gridTemplateColumns: 'repeat(auto-fit, minmax(170px, 1fr))', gap: 8, marginTop: 10 }}>
        {[
          ['来源', '官方/定报/行业交叉验证'],
          ['措辞', '禁止强买、稳赚、确定收益'],
          ['Serenity', '产业链层级与替代风险披露'],
          ['写入', 'blocked 不写 report / 不建 candidate'],
        ].map(([label, value]) => (
          <div key={label} className="glass-inset" style={{ padding: '9px 11px' }}>
            <div className="t-eyebrow">{label}</div>
            <div className="t-dim" style={{ fontSize: 12.3, marginTop: 4, lineHeight: 1.45 }}>{value}</div>
          </div>
        ))}
      </div>
    </div>
  );
}

// ---------- 深度研究 · 完整报告 ----------
function DeepResearchReport({ report }) {
  return (
    <div className="grid" style={{ gap: 14 }}>
      <div className="row" style={{ flexWrap: 'wrap', gap: 8 }}>
        <Badge tone={report.gate_status === 'pass' ? 'badge-up' : report.gate_status === 'warning' ? 'badge-warn' : 'badge-down'}>
          报告闸门 {report.gate_status === 'pass' ? '通过' : report.gate_status === 'warning' ? 'warning' : 'blocked'}
        </Badge>
        <Badge tone={recTone(report.stance)}>{report.stance}</Badge>
        <Badge tone="badge-dim">置信 {report.confidence.toFixed(2)}</Badge>
        <span className="t-faint" style={{ fontSize: 12 }}>{report.symbols.join(' · ')} · {report.as_of}</span>
      </div>
      {report.gate_reasons && report.gate_reasons.length > 0 && (
        <div className="badge badge-warn" style={{ padding: '8px 13px', whiteSpace: 'normal', borderRadius: 11, fontSize: 12.5 }}>⚠ {report.gate_reasons.join(' / ')}</div>
      )}

      <ReportGateSnapshot status={report.gate_status} />

      {/* 来源审计 */}
      <div>
        <div className="spread" style={{ marginBottom: 8 }}>
          <div className="t-eyebrow">来源审计</div>
          <span className="t-faint" style={{ fontSize: 11.5 }}>{report.source_count} 源 · 弱证据 {report.weak_source_count}</span>
        </div>
        <div className="grid" style={{ gap: 6 }}>
          {report.audits.map((a, i) => (
            <div key={i} className="glass-inset row" style={{ padding: '8px 12px', gap: 10, justifyContent: 'space-between' }}>
              <div className="row" style={{ gap: 8, minWidth: 0 }}>
                <Badge tone={TIER_TONE[a.tier]}>{TIER_LABEL[a.tier]}</Badge>
                <span style={{ fontSize: 12.5, fontWeight: 550, whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>{a.source}</span>
              </div>
              <div className="row" style={{ gap: 8, flex: 'none' }}>
                {a.risk_flags && a.risk_flags.map((f) => <Badge key={f} tone="badge-warn">{f}</Badge>)}
                <Badge tone={a.usable ? 'badge-down' : 'badge-dim'}>{a.usable ? '可用' : '不作唯一证据'}</Badge>
                <span className="t-num t-faint" style={{ fontSize: 11 }}>{a.published_at.slice(5)}</span>
              </div>
            </div>
          ))}
        </div>
      </div>

      {/* 证伪条件 */}
      <div className="glass-inset" style={{ padding: '12px 15px' }}>
        <div className="t-eyebrow">证伪条件 · 反方先行</div>
        <ul style={{ margin: '8px 0 0', padding: 0, listStyle: 'none', display: 'grid', gap: 6 }}>
          {report.falsification.map((f, i) => (
            <li key={i} className="row" style={{ alignItems: 'flex-start', gap: 8, fontSize: 12.5, lineHeight: 1.5, color: 'var(--ink-2)' }}>
              <span className="down" style={{ fontSize: 10, marginTop: 3 }}>✕</span><span>{f}</span>
            </li>
          ))}
        </ul>
      </div>

      <div style={{ borderTop: '1px solid var(--hairline-soft)', paddingTop: 6 }}>
        <Markdown text={report.content} />
      </div>
      <p className="t-faint" style={{ margin: 0, fontSize: 11.5, lineHeight: 1.55 }}>
        深度研究为 observe-only;warning 报告携带告警输出,不自动影响生产信号,不自动促进记忆。
      </p>
    </div>
  );
}

// ---------- 外部论题 · ForwardThesis ----------
function ForwardThesisReport({ thesis }) {
  return (
    <div className="grid" style={{ gap: 14 }}>
      <div className="row" style={{ flexWrap: 'wrap', gap: 8 }}>
        <Badge tone="badge-accent">{thesis.source_type}</Badge>
        <Badge tone={thesis.status === 'active' ? 'badge-up' : 'badge-warn'}>{thesis.status === 'active' ? '跟踪中' : '观察'}</Badge>
        <span className="t-faint" style={{ fontSize: 12 }}>{thesis.name} {thesis.symbol} · 来源 {thesis.source_name} · {thesis.as_of}</span>
      </div>
      <p style={{ margin: 0, fontSize: 13.5, lineHeight: 1.65, color: 'var(--ink-2)' }}>{thesis.summary}</p>
      <div className="glass-inset" style={{ padding: '12px 15px' }}>
        <div className="spread" style={{ flexWrap: 'wrap', gap: 8 }}>
          <div className="t-eyebrow">M45 来源门控 · dry-run first</div>
          <div className="row" style={{ gap: 6, flexWrap: 'wrap' }}>
            <Badge tone="badge-warn">pending atoms</Badge>
            <Badge tone="badge-dim">no trusted memory</Badge>
            <Badge tone="badge-dim">no official signal</Badge>
          </div>
        </div>
        <div className="grid" style={{ gridTemplateColumns: 'repeat(auto-fit, minmax(150px, 1fr))', gap: 8, marginTop: 10 }}>
          {[
            ['source_kind', thesis.source_type],
            ['evidence_level', 'cross-check required'],
            ['falsification', `${thesis.kill_conditions.length} 条失效条件`],
            ['write_path', 'ForwardThesis only'],
          ].map(([label, value]) => (
            <div key={label} className="glass-inset" style={{ padding: '9px 11px' }}>
              <div className="t-eyebrow">{label}</div>
              <div className="t-dim" style={{ fontSize: 12.3, marginTop: 4 }}>{value}</div>
            </div>
          ))}
        </div>
      </div>
      <div className="grid" style={{ gridTemplateColumns: 'repeat(auto-fit, minmax(220px, 1fr))', gap: 10 }}>
        <div className="glass-inset" style={{ padding: 13 }}>
          <div className="t-eyebrow">跟进指标</div>
          <ul style={{ margin: '8px 0 0', padding: 0, listStyle: 'none', display: 'grid', gap: 6 }}>
            {thesis.follow_metrics.map((m, i) => (
              <li key={i} className="row" style={{ alignItems: 'flex-start', gap: 7, fontSize: 12.5, lineHeight: 1.5, color: 'var(--ink-2)' }}>
                <span className="t-faint" style={{ marginTop: 1 }}>›</span><span>{m}</span>
              </li>
            ))}
          </ul>
        </div>
        <div className="glass-inset" style={{ padding: 13 }}>
          <div className="t-eyebrow">失效条件 · Kill Conditions</div>
          <ul style={{ margin: '8px 0 0', padding: 0, listStyle: 'none', display: 'grid', gap: 6 }}>
            {thesis.kill_conditions.map((k, i) => (
              <li key={i} className="row" style={{ alignItems: 'flex-start', gap: 7, fontSize: 12.5, lineHeight: 1.5, color: 'var(--ink-2)' }}>
                <span className="down" style={{ fontSize: 10, marginTop: 3 }}>✕</span><span>{k}</span>
              </li>
            ))}
          </ul>
        </div>
      </div>
      <div className="row" style={{ gap: 14, flexWrap: 'wrap' }}>
        <span className="t-faint" style={{ fontSize: 12 }}>复盘节奏 <b style={{ color: 'var(--ink-2)' }}>{thesis.review_cadence}</b></span>
        <span className="t-faint" style={{ fontSize: 12 }}>下次复盘 <b style={{ color: 'var(--ink-2)' }}>{thesis.next_review}</b></span>
      </div>
      <p className="t-faint" style={{ margin: 0, fontSize: 11.5, lineHeight: 1.55 }}>
        论题只作论据,不直接抬高买入分;只有结果兑现、复盘通过,才升级为可信记忆。
      </p>
    </div>
  );
}

// ---------- 证据案卷库 ----------
const REPORT_TYPES = [
  ['all', '全部'],
  ['debate', '辩论裁决'],
  ['deep_research', '深研闸门'],
  ['daily', '盘后复盘'],
  ['long_term', '长期标签复核'],
  ['forward_thesis', '外部论题追踪'],
];
const TYPE_META = {
  debate: { label: '辩论裁决', tone: 'badge-accent' },
  deep_research: { label: '深研闸门', tone: 'badge-up' },
  daily: { label: '盘后复盘', tone: 'badge-accent' },
  long_term: { label: '长期标签复核', tone: 'badge-dim' },
  forward_thesis: { label: '外部论题追踪', tone: 'badge-warn' },
};

function buildReportIndex() {
  const D = window.MC_DATA;
  const out = [];
  // 多空辩论 / 深度研究目前后端无落库 API:live 模式下明确标注「演示」
  const demoTag = window.MC_LIVE && window.MC_LIVE.isLive() ? '演示 · ' : '';
  // 多空辩论(每个有信号的标的一条,按今日决策标的优先)
  Object.keys(D.DEBATE).filter((k) => k !== '_default').forEach((sym) => {
    const d = D.DEBATE[sym];
    const r3 = (d.rounds || []).find((r) => r.speaker === 'adjudicator');
    out.push({
      id: `debate-${sym}`, type: 'debate', title: `${d.name} 多空辩论`, target: `${d.name} ${sym}`,
      date: d.date, status: demoTag + (d.used_llm ? `${d.round_count} 轮 · 用 LLM` : '快速共识'),
      summary: r3 ? r3.rationale : (d.fallback_reason || '四路方向一致,快速共识。'),
      payload: d,
    });
  });
  // 深度研究
  D.DEEP_RESEARCH.forEach((r) => {
    out.push({
      id: r.id, type: 'deep_research', title: r.title, target: r.symbols.join(' · '),
      date: r.as_of, status: demoTag + (r.gate_status === 'pass' ? `闸门通过 · ¥${r.llm_cny}` : `闸门 ${r.gate_status} · ¥${r.llm_cny}`),
      summary: r.topic, payload: r,
    });
  });
  // 复盘(每日 / 长期),每日复盘附盘后导出
  D.REVIEWS.forEach((r) => {
    out.push({
      id: r.id, type: r.kind, title: r.kind === 'daily' ? `每日复盘 ${r.as_of}` : `长期复盘 ${r.as_of}`,
      target: r.kind === 'daily' ? '全市场盘后' : '长期团队', date: r.as_of,
      status: r.kind === 'daily' ? '盘后报告 · 可导出' : '周度反思',
      summary: r.summary, payload: r,
    });
  });
  // 外部论题
  D.FORWARD_THESES.forEach((t) => {
    out.push({
      id: t.id, type: 'forward_thesis', title: t.title, target: `${t.name} ${t.symbol}`,
      date: t.as_of, status: t.status === 'active' ? '跟踪中' : '观察', summary: t.summary, payload: t,
    });
  });
  // 按日期倒序
  return out.sort((a, b) => String(b.date).localeCompare(String(a.date)));
}

function ReportReader({ entry }) {
  if (!entry) return <div className="empty">从左侧选择一份报告,这里显示完整内容。</div>;
  if (entry.type === 'debate') return <DebateReport debate={entry.payload} />;
  if (entry.type === 'deep_research') return <DeepResearchReport report={entry.payload} />;
  if (entry.type === 'forward_thesis') return <ForwardThesisReport thesis={entry.payload} />;
  return <Markdown text={entry.payload.content} />;
}

function EvidenceWorkspace({ reports }) {
  const [filter, setFilter] = useRepState('all');
  const [selectedId, setSelectedId] = useRepState(reports[0]?.id);
  const filtered = filter === 'all' ? reports : reports.filter((r) => r.type === filter);
  const selected = reports.find((r) => r.id === selectedId) || filtered[0] || reports[0];

  const counts = useRepMemo(() => {
    const c = { all: reports.length };
    reports.forEach((r) => { c[r.type] = (c[r.type] || 0) + 1; });
    return c;
  }, [reports]);

  const exportBtns = selected ? (
    <div className="row" style={{ gap: 6 }}>
      <button className="btn btn-sm" onClick={() => toast('已导出 HTML 报告(演示)')}>导出 HTML</button>
      {(selected.type === 'daily' || selected.type === 'long_term' || selected.type === 'deep_research') &&
        <button className="btn btn-sm" onClick={() => toast('已导出 Word 报告(演示)')}>Word</button>}
    </div>
  ) : null;

  return (
    <div className="grid" style={{ gap: 14 }}>
      <SourceGateOverview />

      <div className="row pop" style={{ gap: 6, flexWrap: 'wrap' }}>
        {REPORT_TYPES.map(([id, label]) => (
          <button key={id} type="button" className={`navlink ${filter === id ? 'on' : ''}`}
            style={{ border: '1px solid var(--hairline-soft)' }} onClick={() => setFilter(id)}>
            {label}<span className="t-faint" style={{ marginLeft: 6, fontSize: 11.5 }}>{counts[id] || 0}</span>
          </button>
        ))}
      </div>

      <div className="grid" style={{ gridTemplateColumns: 'minmax(0, 400px) minmax(0, 1fr)', gap: 14 }} data-grid="review-cols">
        <Card eyebrow="Dossier Index" title={`${filtered.length} 份案卷`} className="pop pop-1" pad={false} tour="dossier-index">
          <div>
            {filtered.map((r, i) => {
              const meta = TYPE_META[r.type];
              const on = selected?.id === r.id;
              return (
                <button key={r.id} type="button" onClick={() => setSelectedId(r.id)}
                  style={{
                    display: 'block', width: '100%', textAlign: 'left', cursor: 'pointer',
                    padding: '13px 18px', border: 'none', font: 'inherit', color: 'inherit',
                    background: on ? 'var(--accent-soft)' : 'transparent',
                    borderBottom: i < filtered.length - 1 ? '1px solid var(--hairline-soft)' : 'none',
                    borderLeft: on ? '3px solid var(--accent)' : '3px solid transparent',
                    transition: 'background 0.15s',
                  }}>
                  <div className="spread" style={{ gap: 8 }}>
                    <div className="row" style={{ gap: 8, minWidth: 0 }}>
                      <Badge tone={meta.tone}>{meta.label}</Badge>
                      <span style={{ fontSize: 13.5, fontWeight: 600, whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>{r.title}</span>
                    </div>
                    <span className="t-num t-faint" style={{ fontSize: 11.5, flex: 'none' }}>{r.date}</span>
                  </div>
                  <div className="t-dim" style={{ fontSize: 12.5, marginTop: 5, lineHeight: 1.5, display: '-webkit-box', WebkitLineClamp: 2, WebkitBoxOrient: 'vertical', overflow: 'hidden' }}>{r.summary}</div>
                  <div className="t-faint" style={{ fontSize: 11, marginTop: 5 }}>{r.target} · {r.status}</div>
                </button>
              );
            })}
          </div>
        </Card>

        <Card eyebrow={selected ? TYPE_META[selected.type].label : 'Detail'} title={selected ? selected.title : '案卷详情'}
          className="pop pop-2" right={exportBtns}>
          <ReportReader entry={selected} />
        </Card>
      </div>
    </div>
  );
}

function ReplayReviewCard({ title, item, onEnsure, busy }) {
  return (
    <Card eyebrow={title} title={item ? item.as_of : '尚未生成'}
      right={<button className="btn btn-sm" disabled={busy} onClick={onEnsure}>{busy ? '处理中…' : '立即检查'}</button>}>
      {item ? (
        <div>
          <p style={{ margin: 0, fontSize: 13.5, lineHeight: 1.6, color: 'var(--ink-2)' }}>{item.summary}</p>
          <div className="grid" style={{ gridTemplateColumns: 'repeat(3, 1fr)', gap: 8, marginTop: 12 }}>
            {item.metrics.map(([l, v]) => <Metric key={l} label={l} value={v} />)}
          </div>
          <div className="grid" style={{ gap: 7, marginTop: 12 }}>
            {item.highlights.map((h, i) => (
              <div key={i} style={{ fontSize: 12.5, lineHeight: 1.55, color: 'var(--ink-2)', paddingLeft: 10, borderLeft: '2px solid var(--accent)' }}>{h}</div>
            ))}
          </div>
        </div>
      ) : (
        <div className="empty">尚未生成复盘。点击「立即检查」让系统判断是否需要生成。</div>
      )}
    </Card>
  );
}

function ReviewsWorkspace() {
  const [stState] = useStore();
  const reviews = (stState.reviews && stState.reviews.length) ? stState.reviews : window.MC_DATA.REVIEWS;
  const [busy, setBusy] = useRepState('');
  const [selectedId, setSelectedId] = useRepState(reviews[0]?.id);
  const selected = reviews.find((r) => r.id === selectedId) || reviews[0];
  const latestDaily = reviews.find((r) => r.kind === 'daily');
  const latestLT = reviews.find((r) => r.kind === 'long_term');

  // live 模式:选中没有正文的复盘时,懒取完整报告内容
  useRepEffect(() => {
    if (selected && !selected.content && window.MC_LIVE) {
      window.MC_LIVE.loadReviewContent(selected.id).catch(() => {});
    }
  }, [selected?.id]);

  function ensure(kind) {
    setBusy(kind);
    window.MC_LIVE.ensureReview(kind === 'daily' ? 'daily' : 'long_term')
      .then(() => { setBusy(''); toast(kind === 'daily' ? '每日复盘检查完成' : '长期复盘检查完成'); })
      .catch((e) => {
        setBusy('');
        if (!e || !e.demo) { toast(`复盘检查失败:${e?.message || '后端错误'}`); return; }
        toast(kind === 'daily' ? '今日复盘已是最新(2026-06-09),无需重新生成' : '本周长期复盘已是最新(2026-W24)');
      });
  }

  return (
    <div className="grid" style={{ gap: 14 }}>
      <div className="grid pop" style={{ gridTemplateColumns: 'repeat(auto-fit, minmax(320px, 1fr))', gap: 14 }}>
        <ReplayReviewCard title="每日复盘" item={latestDaily} busy={busy === 'daily'} onEnsure={() => ensure('daily')} />
        <ReplayReviewCard title="长期复盘" item={latestLT} busy={busy === 'long'} onEnsure={() => ensure('long')} />
      </div>

      <div className="grid" style={{ gridTemplateColumns: 'minmax(0, 380px) minmax(0, 1fr)', gap: 14 }} data-grid="review-cols">
        <Card eyebrow="Review History" title="复盘历史" className="pop pop-1" pad={false}>
          <div>
            {reviews.map((r, i) => (
              <button key={r.id} type="button" onClick={() => setSelectedId(r.id)}
                style={{
                  display: 'block', width: '100%', textAlign: 'left', cursor: 'pointer',
                  padding: '12px 18px', border: 'none', font: 'inherit', color: 'inherit',
                  background: selected?.id === r.id ? 'var(--accent-soft)' : 'transparent',
                  borderBottom: i < reviews.length - 1 ? '1px solid var(--hairline-soft)' : 'none',
                  borderLeft: selected?.id === r.id ? '3px solid var(--accent)' : '3px solid transparent',
                  transition: 'background 0.15s',
                }}>
                <div className="row" style={{ gap: 8 }}>
                  <span className="t-num" style={{ fontSize: 12.5, fontWeight: 650 }}>{r.as_of}</span>
                  <Badge tone={r.kind === 'daily' ? 'badge-accent' : 'badge-dim'}>{r.kind === 'daily' ? '每日' : '长期'}</Badge>
                </div>
                <div className="t-dim" style={{ fontSize: 12.5, marginTop: 4, lineHeight: 1.5 }}>{r.summary}</div>
              </button>
            ))}
          </div>
        </Card>

        <Card eyebrow="Review Detail" title={selected ? `${selected.kind === 'daily' ? '每日复盘' : '长期复盘'} · ${selected.as_of}` : '复盘详情'}
          className="pop pop-2"
          right={
            <div className="row" style={{ gap: 6 }}>
              <button className="btn btn-sm" onClick={() => {
                if (window.MC_LIVE && window.MC_LIVE.isLive()) window.open('/api/export/postmarket-review.html', '_blank');
                else toast('已导出 HTML 报告(演示)');
              }}>导出 HTML</button>
              <button className="btn btn-sm" onClick={() => {
                if (window.MC_LIVE && window.MC_LIVE.isLive()) window.open('/api/export/reviews.csv', '_blank');
                else toast('已导出 Word 报告(演示)');
              }}>{window.MC_LIVE && window.MC_LIVE.isLive() ? 'CSV' : 'Word'}</button>
            </div>
          }>
          {selected ? <Markdown text={selected.content || selected.summary || ''} /> : (
            <div className="empty">点击左侧复盘历史条目,这里会展示完整复盘报告。</div>
          )}
        </Card>
      </div>
    </div>
  );
}

function MemoryWorkspace() {
  useStore(); // 订阅 store:候选 promote/reject 后 MEMORY_CENTER 更新需要重渲染
  const M = window.MC_DATA.MEMORY_CENTER;
  const atlasLive = window.MC_LIVE && window.MC_LIVE.isLive() && window.MC_LIVE.isAtlasOn();

  function candidateAct(kind, q) {
    const run = kind === 'promote' ? window.MC_LIVE.candidatePromote : window.MC_LIVE.candidateReject;
    run(q.id)
      .then(() => toast(kind === 'promote' ? `候选已升级:${q.title}` : `候选已标记 refuted:${q.title}`))
      .catch((e) => {
        if (e && e.demo) toast(kind === 'promote' ? '记忆候选已标记为待人工确认(演示)' : '候选已标记为 refuted(演示)');
        else toast(`操作失败:${e?.message || '后端错误'}`);
      });
  }
  return (
    <div className="grid" style={{ gap: 14 }}>
      <div className="grid pop pop-1" style={{ gridTemplateColumns: 'repeat(auto-fit, minmax(150px, 1fr))', gap: 9 }}>
        <Metric label="总记忆" value={M.overview.total} />
        <Metric label="Trusted" value={M.overview.trusted} tone="up" />
        <Metric label="待确认" value={M.overview.pending} tone="warn" />
        <Metric label="已反驳" value={M.overview.refuted} tone="down" />
        <Metric label="个股记忆" value={M.overview.stock_items} />
        <Metric label="L0 Atoms" value={M.overview.l0_atoms} />
      </div>

      <div className="grid" style={{ gridTemplateColumns: 'minmax(0, 1fr) 340px', gap: 14 }} data-grid="stock-cols">
        <div className="grid" style={{ gap: 14 }}>
          <Card eyebrow="Memory Queue" title="候选记忆升级队列" className="pop pop-1">
            <div className="grid" style={{ gap: 10 }}>
              {M.queue.length === 0 && (
                <div className="empty">
                  暂无待确认候选。{atlasLive ? '复盘或研究运行产生记忆候选后,会进入这里等待人工升级。' : ''}
                </div>
              )}
              {M.queue.map((q) => (
                <div key={q.id} className="glass-inset" style={{ padding: '13px 15px' }}>
                  <div className="spread" style={{ flexWrap: 'wrap', gap: 8 }}>
                    <div className="row" style={{ gap: 7, flexWrap: 'wrap' }}>
                      <Badge tone={q.trust === 'pending' ? 'badge-warn' : 'badge-accent'}>{q.trust}</Badge>
                      <span className="t-num t-faint" style={{ fontSize: 11.5 }}>{q.symbol}</span>
                      <span className="t-num t-faint" style={{ fontSize: 11.5 }}>{q.source}</span>
                    </div>
                    <div className="row" style={{ gap: 6 }}>
                      <button className="btn btn-sm" onClick={() => toast('已预览升级影响(演示),真实升级需要人工确认')}>预览</button>
                      <button className="btn btn-sm btn-primary" onClick={() => candidateAct('promote', q)}>确认升级</button>
                      <button className="btn btn-sm btn-quiet btn-danger" onClick={() => candidateAct('reject', q)}>反驳</button>
                    </div>
                  </div>
                  <div style={{ marginTop: 8, fontSize: 14, fontWeight: 650 }}>{q.title}</div>
                  <div className="grid" style={{ gridTemplateColumns: '1fr 1fr', gap: 8, marginTop: 9 }}>
                    <div className="glass-inset" style={{ padding: '8px 11px' }}>
                      <div className="t-eyebrow">Outcome Evidence</div>
                      <div className="t-dim" style={{ fontSize: 12.5, marginTop: 3, lineHeight: 1.5 }}>{q.evidence}</div>
                    </div>
                    <div className="glass-inset" style={{ padding: '8px 11px' }}>
                      <div className="t-eyebrow">建议动作</div>
                      <div className="t-dim" style={{ fontSize: 12.5, marginTop: 3, lineHeight: 1.5 }}>{q.action}</div>
                    </div>
                  </div>
                </div>
              ))}
            </div>
          </Card>

          <Card eyebrow="Recall Audit" title="最近召回与污染防护" className="pop pop-2" pad={false}>
            <table className="mc-table">
              <thead><tr><th>时间</th><th>动作</th><th>对象</th><th>说明</th></tr></thead>
              <tbody>
                {M.audit.map(([time, action, target, note]) => (
                  <tr key={`${time}-${target}`}>
                    <td className="t-num t-faint">{time}</td>
                    <td><Badge tone={action === 'refute' ? 'badge-down' : action === 'candidate' ? 'badge-warn' : 'badge-accent'}>{action}</Badge></td>
                    <td className="t-num">{target}</td>
                    <td className="t-dim" style={{ fontSize: 12.5 }}>{note}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </Card>
        </div>

        <div className="grid pop pop-2" style={{ gap: 10, alignContent: 'start' }}>
          <Card eyebrow="Memory Lanes" title="记忆分层" className="pop">
            <div className="grid" style={{ gap: 8 }}>
              {M.lanes.map(([name, desc, count, state]) => (
                <div key={name} className="glass-inset" style={{ padding: '11px 13px' }}>
                  <div className="spread">
                    <span style={{ fontWeight: 650 }}>{name}</span>
                    <span className="t-num">{count}</span>
                  </div>
                  <div className="t-faint" style={{ fontSize: 11.5, marginTop: 3 }}>{state}</div>
                  <div className="t-dim" style={{ fontSize: 12.5, lineHeight: 1.5, marginTop: 6 }}>{desc}</div>
                </div>
              ))}
            </div>
          </Card>
          <div className="glass" style={{ padding: '14px 16px' }}>
            <div className="t-eyebrow">信任规则</div>
            <div className="grid" style={{ gap: 8, marginTop: 10, fontSize: 12.5, color: 'var(--ink-2)', lineHeight: 1.55 }}>
              <div>1. AI 输出只可生成候选。</div>
              <div>2. ReviewCase 或结果证据必须可回看。</div>
              <div>3. 用户确认后才 trusted。</div>
              <div>4. 被证伪的旧记忆保留 audit,避免重复犯错。</div>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}

function ReportsPage() {
  const [repPageState] = useStore(); // live 数据落地后重建报告索引
  const reports = useRepMemo(() => buildReportIndex(), [repPageState]);
  const [section, setSection] = useRepState('reviews');
  const M = window.MC_DATA.MEMORY_CENTER;
  const summary = [
    ['复盘记录', window.MC_DATA.REVIEWS.length, '每日 / 长期复盘'],
    ['证据案卷', reports.length, '裁决 / 深研 / 外部论题'],
    ['待确认记忆', M.overview.pending, '确认后才 trusted'],
  ];
  const sections = [
    ['reviews', '复盘记录'],
    ['evidence', '证据来源'],
    ['memory', '记忆沉淀'],
  ];

  return (
    <div className="grid" style={{ gap: 14 }}>
      <PageHead eyebrow="Replay Dossier" title="复盘案卷"
        desc="把证据来源、复盘记录和记忆沉淀放在同一个案卷里:先看材料从哪来,再看复盘怎么判,最后看哪些经验可以进入长期记忆。" />

      <div className="grid pop" style={{ gridTemplateColumns: 'repeat(auto-fit, minmax(220px, 1fr))', gap: 10 }}>
        {summary.map(([label, value, sub]) => (
          <div key={label} className="glass" style={{ padding: '13px 16px' }}>
            <div className="t-eyebrow">{label}</div>
            <div className="t-num" style={{ fontSize: 21, fontWeight: 750, marginTop: 5 }}>{value}</div>
            <div className="t-faint" style={{ fontSize: 12, marginTop: 3 }}>{sub}</div>
          </div>
        ))}
      </div>

      <div className="row pop" style={{ gap: 6, flexWrap: 'wrap' }}>
        {sections.map(([id, label]) => (
          <button key={id} type="button" className={`navlink ${section === id ? 'on' : ''}`}
            style={{ border: '1px solid var(--hairline-soft)' }} onClick={() => setSection(id)}>
            {label}
          </button>
        ))}
      </div>

      {section === 'reviews' && <ReviewsWorkspace />}
      {section === 'evidence' && <EvidenceWorkspace reports={reports} />}
      {section === 'memory' && <MemoryWorkspace />}
    </div>
  );
}

Object.assign(window, { ReportsPage, DebateReport, DeepResearchReport, ForwardThesisReport });
