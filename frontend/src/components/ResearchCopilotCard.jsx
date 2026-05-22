import { getCopilotActionLabel, getCopilotCardView } from './copilotSummary'

const TONE = {
  support: 'border-red-500/35 bg-red-500/10 text-red-200',
  caution: 'border-amber-500/35 bg-amber-500/10 text-amber-200',
  oppose: 'border-emerald-500/35 bg-emerald-500/10 text-emerald-200',
  neutral: 'border-slate-600 bg-slate-800 text-slate-200',
}

function InfoRow({ label, value }) {
  return (
    <div>
      <div className="text-[10px] uppercase tracking-[0.16em] text-gray-500">{label}</div>
      <div className="mt-1 font-mono text-sm text-gray-200">{value}</div>
    </div>
  )
}

export default function ResearchCopilotCard({
  copilot,
  loading = false,
  error = '',
  onRefresh,
}) {
  const hasCopilot = Boolean(copilot)
  const view = getCopilotCardView(copilot || {})
  const label = getCopilotActionLabel({ loading, hasCopilot, error })

  return (
    <section className="bg-gray-900 border border-gray-800 rounded-lg p-4 space-y-4">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <div className="text-xs text-gray-500">LLM 副驾驶</div>
          <h2 className="mt-1 text-sm font-semibold text-gray-200">双轨影子决策卡</h2>
        </div>
        <button
          type="button"
          disabled={loading}
          onClick={onRefresh}
          className="rounded border border-gray-700 bg-gray-950 px-3 py-1.5 text-xs font-semibold text-gray-200 hover:border-cyan-500 hover:text-cyan-200 disabled:cursor-not-allowed disabled:opacity-50"
        >
          {label}
        </button>
      </div>

      {error && (
        <div className="rounded border border-red-500/40 bg-red-500/10 px-3 py-2 text-xs text-red-200">
          {error}
        </div>
      )}

      {!hasCopilot ? (
        <div className="border-t border-gray-800 pt-3 text-sm text-gray-500">
          暂无副驾驶影子意见。
        </div>
      ) : (
        <>
          <div className="grid gap-5 border-t border-gray-800 pt-4 md:grid-cols-2">
            <div>
              <div className="text-xs text-gray-500">官方规则</div>
              <div className="mt-2 grid grid-cols-2 gap-3">
                <InfoRow label="建议" value={view.officialRecommendation} />
                <InfoRow label="综合分" value={view.officialScore} />
                <InfoRow label="技术" value={view.officialTechnical} />
                <InfoRow label="情绪" value={view.officialSentiment} />
                <InfoRow label="官方仓位" value={view.officialPosition} />
                <InfoRow label="止损 / 止盈" value={`${view.officialStopLoss} / ${view.officialTakeProfit}`} />
              </div>
            </div>

            <div>
              <div className="flex flex-wrap items-center gap-2">
                <span className={`rounded border px-2 py-0.5 text-xs font-semibold ${TONE[view.stanceTone]}`}>
                  {view.stance}
                </span>
                {view.conflictLabel && (
                  <span className="rounded border border-red-500/40 bg-red-500/10 px-2 py-0.5 text-xs font-semibold text-red-200">
                    {view.conflictLabel}
                  </span>
                )}
              </div>
              <div className="mt-3 text-sm leading-relaxed text-gray-200">{view.summary}</div>
              <div className="mt-3 grid grid-cols-2 gap-3">
                <InfoRow label="影子仓位" value={view.shadowPosition} />
                <InfoRow label="仓位理由" value={view.positionNote || '-'} />
              </div>
            </div>
          </div>

          <div className="grid gap-5 border-t border-gray-800 pt-4 md:grid-cols-2">
            <div className="text-sm text-gray-300">
              <div className="text-xs text-gray-500 mb-2">事件与技术解读</div>
              <div>{view.eventRead || '-'}</div>
              <div className="mt-2 text-gray-400">{view.technicalRead || '-'}</div>
            </div>
            <div className="text-sm text-gray-300">
              <div className="text-xs text-gray-500 mb-2">风险 / 待验证</div>
              {(view.risks.length ? view.risks : ['暂无额外风险']).slice(0, 3).map((item, index) => (
                <div key={`risk-${index}`}>风险：{item}</div>
              ))}
              {(view.validationQuestions.length ? view.validationQuestions : ['等待后续走势验证']).slice(0, 3).map((item, index) => (
                <div key={`question-${index}`} className="mt-1 text-gray-400">验证：{item}</div>
              ))}
            </div>
          </div>
        </>
      )}
    </section>
  )
}
