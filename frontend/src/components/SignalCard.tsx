import type { LLMArbitration, SignalOut } from '../apiTypes'
import { formatDate, formatPrice } from '../financialNumbers'
import StatusBadge, { type StatusBadgeStatus } from './ui/StatusBadge'

const REC_STATUS: Record<string, StatusBadgeStatus> = {
  可小仓试错: 'bull',
  可关注: 'watch',
  强买: 'bull',
  买入: 'bull',
  观望: 'watch',
  规避: 'bear',
  卖出: 'bear',
  强卖: 'bear',
}

function ScoreGauge({ score }: { score: number | null | undefined }) {
  const clamp = Math.max(-100, Math.min(100, Number(score || 0)))
  const color = clamp > 20 ? '#ef4444' : clamp < -20 ? '#22c55e' : '#eab308'
  const width = `${Math.abs(clamp) / 2}%`
  const left = clamp < 0 ? `${50 - Math.abs(clamp) / 2}%` : '50%'
  return (
    <div className="text-center">
      <div className="text-5xl font-bold font-mono" style={{ color }}>
        {clamp > 0 ? '+' : ''}{clamp.toFixed(0)}
      </div>
      <div className="text-xs text-gray-500 mb-2">综合得分（-100 ~ +100）</div>
      <div className="relative h-2 bg-gray-700 rounded-full overflow-hidden">
        <div
          className="absolute top-0 h-2 rounded-full transition-all"
          style={{ left, width, background: color }}
        />
        <div className="absolute top-0 left-1/2 w-px h-2 bg-gray-500" />
      </div>
      <div className="flex justify-between text-xs text-gray-600 mt-0.5">
        <span>规避</span><span>中性</span><span>试错</span>
      </div>
    </div>
  )
}

interface BreakdownProps {
  quant: number | null | undefined
  technical: number | null | undefined
  sentiment: number | null | undefined
}

function Breakdown({ quant, technical, sentiment }: BreakdownProps) {
  const bars = [
    { label: '量化', value: quant, color: '#818cf8' },
    { label: '技术', value: technical, color: '#38bdf8' },
    { label: '情感', value: sentiment, color: '#fb923c' },
  ]
  return (
    <div className="space-y-1.5 mt-4">
      {bars.map(({ label, value, color }) => {
        const normalized = Math.max(-100, Math.min(100, Number(value || 0)))
        const pct = ((normalized + 100) / 200) * 100
        return (
          <div key={label} className="flex items-center gap-2">
            <span className="text-xs text-gray-400 w-8">{label}</span>
            <div className="flex-1 bg-gray-700 rounded-full h-1.5">
              <div className="h-1.5 rounded-full" style={{ width: `${pct}%`, background: color }} />
            </div>
            <span className="text-xs font-mono w-8 text-right" style={{ color }}>
              {normalized > 0 ? '+' : ''}{normalized.toFixed(0)}
            </span>
          </div>
        )
      })}
    </div>
  )
}

function DebateSection({ arb }: { arb: LLMArbitration | null | undefined }) {
  if (!arb || (!arb.bull_points?.length && !arb.bear_points?.length)) return null
  return (
    <div className="mt-4 border-t border-gray-800 pt-4">
      <div className="text-xs text-gray-400 mb-2 font-medium">多空辩论</div>
      <div className="grid grid-cols-2 gap-2">
        <div>
          <div className="text-xs text-red-400 font-medium mb-1">多方</div>
          <ul className="space-y-1">
            {arb.bull_points.map((point, index) => (
              <li key={index} className="text-xs text-gray-300">· {point}</li>
            ))}
          </ul>
        </div>
        <div>
          <div className="text-xs text-green-400 font-medium mb-1">空方</div>
          <ul className="space-y-1">
            {arb.bear_points.map((point, index) => (
              <li key={index} className="text-xs text-gray-300">· {point}</li>
            ))}
          </ul>
        </div>
      </div>
      {arb.rationale && (
        <div className="mt-2 text-xs text-gray-400 italic">"{arb.rationale}"</div>
      )}
      {arb.action_bias && (
        <div className="mt-1">
          <StatusBadge
            status={
              arb.action_bias === '偏多'
                ? 'bull'
                : arb.action_bias === '偏空'
                  ? 'bear'
                  : 'neutral'
            }
          >
            {arb.action_bias}
          </StatusBadge>
        </div>
      )}
    </div>
  )
}

export default function SignalCard({ signal }: { signal?: SignalOut | null }) {
  if (!signal) {
    return (
      <div className="bg-gray-900 border border-gray-800 rounded-xl p-6 text-center text-gray-500">
        暂无信号数据
      </div>
    )
  }

  const recommendationStatus = REC_STATUS[signal.recommendation] || 'neutral'
  const breakdown = {
    quant: signal.quant_score ?? 0,
    technical: signal.technical_score ?? 0,
    sentiment: signal.sentiment_score ?? 0,
  }

  return (
    <div className="bg-gray-900 border border-gray-800 rounded-xl p-6">
      <div className="flex justify-between items-center mb-4">
        <div>
          <StatusBadge status={recommendationStatus} className="text-xs">
            {signal.recommendation}
          </StatusBadge>
          <span className="ml-2 text-xs text-gray-400">置信度 {signal.confidence}</span>
        </div>
        <span className="text-xs text-gray-500">{formatDate(signal.date)}</span>
      </div>

      <ScoreGauge score={signal.composite_score} />

      {signal.stop_loss && (
        <div className="mt-4 grid grid-cols-2 gap-3 text-center">
          <div className="bg-gray-800 rounded-lg p-2">
            <div className="text-xs text-gray-400">止损</div>
            <div className="text-green-400 font-mono font-bold">{formatPrice(signal.stop_loss)}</div>
          </div>
          <div className="bg-gray-800 rounded-lg p-2">
            <div className="text-xs text-gray-400">止盈</div>
            <div className="text-red-400 font-mono font-bold">{formatPrice(signal.take_profit)}</div>
          </div>
        </div>
      )}

      <Breakdown {...breakdown} />
      <DebateSection arb={signal.llm_arbitration} />

      {signal.limit_status && signal.limit_status !== 'normal' && (
        <div className="mt-3">
          <StatusBadge status={signal.limit_status === 'limit_up' ? 'bull' : 'bear'}>
            {signal.limit_status === 'limit_up' ? '今日涨停，买入难以成交' : '今日跌停，止损不可执行'}
          </StatusBadge>
        </div>
      )}
    </div>
  )
}
