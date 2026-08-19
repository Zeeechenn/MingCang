import { Badge, ScoreBar, fmt, recTone } from '../../shared';

const roleTone = (score: number) => (score > 10 ? 'up' : score < -10 ? 'down' : '');
const winLabel: Record<string, string> = { bull: '多方胜', bear: '空方胜', tie: '平局' };
const winTone: Record<string, string> = { bull: 'badge-up', bear: 'badge-down', tie: 'badge-dim' };

export function DebateReport({ debate }: any) {
  if (!debate) return <div className="empty">暂无辩论记录。</div>;
  const quick = !debate.rounds || debate.rounds.length === 0;
  const r1 = (debate.rounds || []).find((r: any) => r.speaker === 'bull');
  const r2 = (debate.rounds || []).find((r: any) => r.speaker === 'bear');
  const r3 = (debate.rounds || []).find((r: any) => r.speaker === 'adjudicator');

  return (
    <div className="grid" style={{ gap: 16 }}>
      <div className="row" style={{ flexWrap: 'wrap', gap: 8 }}>
        <Badge tone="badge-accent">研究总监</Badge>
        <Badge tone={debate.used_llm ? 'badge-up' : 'badge-dim'}>{debate.used_llm ? `${debate.round_count} 轮辩论 · 用 LLM` : '快速共识 · 零 LLM'}</Badge>
        <span className="t-faint" style={{ fontSize: 12 }}>标的 {debate.name} {debate.symbol} · {debate.date}</span>
      </div>

      <div>
        <div className="t-eyebrow" style={{ marginBottom: 8 }}>四路分析师并行打分</div>
        <div className="grid" style={{ gridTemplateColumns: 'repeat(auto-fit, minmax(150px, 1fr))', gap: 8 }}>
          {(debate.analysts || []).map((a: any) => (
            <div key={a.key} className="glass-inset" style={{ padding: '11px 13px' }}>
              <div className="spread">
                <span style={{ fontSize: 13, fontWeight: 650 }}>{a.role}</span>
                <span className={`t-num ${roleTone(a.score)}`} style={{ fontSize: 15, fontWeight: 700 }}>{fmt.signed(a.score)}</span>
              </div>
              <div className="t-faint" style={{ fontSize: 11, marginTop: 2 }}>置信 {Number(a.confidence || 0).toFixed(2)}</div>
              <div style={{ marginTop: 7 }}><ScoreBar score={a.score} height={4} /></div>
              <ul style={{ margin: '9px 0 0', padding: 0, listStyle: 'none', display: 'grid', gap: 4 }}>
                {(a.findings || []).map((f: string, i: number) => (
                  <li key={i} className="t-dim" style={{ fontSize: 11.5, lineHeight: 1.45, paddingLeft: 9, position: 'relative' }}>
                    <span style={{ position: 'absolute', left: 0, opacity: 0.5 }}>·</span>{f}
                  </li>
                ))}
              </ul>
            </div>
          ))}
        </div>
      </div>

      <div className="glass-inset" style={{ padding: '13px 15px' }}>
        <div className="spread" style={{ flexWrap: 'wrap', gap: 8 }}>
          <div className="t-eyebrow">研究总监 · 质量评估与议题</div>
          <div className="row" style={{ gap: 6 }}>
            <Badge tone="badge-dim">分歧 σ {debate.director?.score_stdev}</Badge>
            <Badge tone={debate.director?.diverged ? 'badge-warn' : 'badge-dim'}>{debate.director?.diverged ? '达辩论阈值' : '方向一致'}</Badge>
          </div>
        </div>
        {debate.director?.debate_topic ? (
          <p style={{ margin: '9px 0 0', fontSize: 13, lineHeight: 1.6, color: 'var(--ink-2)' }}>
            <span style={{ color: 'var(--accent-ink)', fontWeight: 650, marginRight: 6 }}>议题</span>{debate.director.debate_topic}
          </p>
        ) : (
          <p className="t-dim" style={{ margin: '9px 0 0', fontSize: 13 }}>未达辩论阈值，研究员快速达成共识，不下达议题。</p>
        )}
      </div>

      {quick ? (
        <div className="empty">{debate.fallback_reason || '四路方向一致，跳过辩论。'}</div>
      ) : (
        <div className="grid" style={{ gap: 10 }}>
          <div className="t-eyebrow">三轮辩论记录</div>
          {r1 && (
            <div className="glass-inset" style={{ padding: '13px 15px', borderLeft: '3px solid var(--up)' }}>
              <div className="spread">
                <span className="up" style={{ fontSize: 12.5, fontWeight: 700 }}>第 1 轮 · 看多开场</span>
                <span className="t-faint" style={{ fontSize: 11 }}>引用 {r1.key_signal}</span>
              </div>
              <ul style={{ margin: '9px 0 0', padding: 0, listStyle: 'none', display: 'grid', gap: 7 }}>
                {(r1.points || []).map((p: string, i: number) => (
                  <li key={i} className="row" style={{ alignItems: 'flex-start', gap: 7, fontSize: 13, lineHeight: 1.55, color: 'var(--ink-2)' }}>
                    <span className="up" style={{ fontSize: 10, marginTop: 3 }}>▲</span><span>{p}</span>
                  </li>
                ))}
              </ul>
            </div>
          )}
          {r2 && (
            <div className="glass-inset" style={{ padding: '13px 15px', borderLeft: '3px solid var(--down)' }}>
              <span className="down" style={{ fontSize: 12.5, fontWeight: 700 }}>第 2 轮 · 看空逐条反驳</span>
              <div className="grid" style={{ gap: 8, marginTop: 9 }}>
                {(r2.rebuttals || []).map((rb: any, i: number) => (
                  <div key={i} style={{ fontSize: 12.5, lineHeight: 1.55 }}>
                    <span className="t-faint">针对「{rb.target}」</span>
                    <div className="row" style={{ alignItems: 'flex-start', gap: 7, marginTop: 2, color: 'var(--ink-2)' }}>
                      <span className="down" style={{ fontSize: 10, marginTop: 3 }}>▼</span><span>{rb.counter}</span>
                    </div>
                  </div>
                ))}
              </div>
            </div>
          )}
          {r3 && (
            <div className="glass-inset" style={{ padding: '13px 15px', borderLeft: '3px solid var(--accent)' }}>
              <div className="spread" style={{ flexWrap: 'wrap', gap: 8 }}>
                <span style={{ fontSize: 12.5, fontWeight: 700, color: 'var(--accent-ink)' }}>第 3 轮 · 看多回应 + 裁定</span>
                <div className="row" style={{ gap: 6 }}>
                  <Badge tone={winTone[r3.winning_side]}>{winLabel[r3.winning_side]}</Badge>
                  <Badge tone={recTone(r3.action_bias)}>{r3.action_bias}</Badge>
                </div>
              </div>
              <p style={{ margin: '11px 0 0', fontSize: 13.5, lineHeight: 1.65, color: 'var(--ink)', fontWeight: 500 }}>{r3.rationale}</p>
            </div>
          )}
        </div>
      )}

      <p className="t-faint" style={{ margin: 0, fontSize: 11.5, lineHeight: 1.55 }}>
        多空辩论为研究参考(影子轨)，用于暴露分歧；不进入正式信号，不自动下单。
      </p>
    </div>
  );
}
