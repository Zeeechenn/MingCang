import { useState } from 'react'

const REC_BADGE = {
  可小仓试错: 'bg-red-500/20 text-red-300 border-red-500/40',
  可关注: 'bg-orange-400/20 text-orange-300 border-orange-400/40',
  买入: 'bg-red-400/20 text-red-300 border-red-400/40',
  强买: 'bg-red-600/20 text-red-400 border-red-600/40',
  观望: 'bg-yellow-500/15 text-yellow-300 border-yellow-500/30',
  规避: 'bg-green-600/20 text-green-300 border-green-600/40',
  卖出: 'bg-green-500/20 text-green-300 border-green-500/40',
  强卖: 'bg-green-700/20 text-green-400 border-green-700/40',
}

function StatCell({ label, value, suffix = '', tone = 'gray' }) {
  const toneClass = {
    red: 'text-red-400',
    green: 'text-green-400',
    yellow: 'text-yellow-300',
    gray: 'text-gray-200',
  }[tone]
  return (
    <div className="bg-gray-800 rounded-lg p-3">
      <div className="text-xs text-gray-500">{label}</div>
      <div className={`text-lg font-mono font-bold ${toneClass}`}>
        {value === null || value === undefined ? '—' : value}
        {value !== null && value !== undefined && suffix}
      </div>
    </div>
  )
}

function DirectionRow({ label, avg, color }) {
  if (avg === null || avg === undefined) {
    return (
      <div className="flex items-center justify-between text-xs">
        <span className="text-gray-500">{label}</span>
        <span className="text-gray-600 font-mono">无样本</span>
      </div>
    )
  }
  const isGood =
    (label === '试错方向' && avg > 0) ||
    (label === '规避方向' && avg < 0) ||
    (label === '观望方向' && Math.abs(avg) <= 0.5)
  const tone = isGood ? 'text-green-400' : 'text-orange-400'
  return (
    <div className="flex items-center justify-between text-xs">
      <span className="text-gray-400">
        <span className="inline-block w-2 h-2 rounded-full mr-2" style={{ background: color }} />
        {label}
      </span>
      <span className={`font-mono ${tone}`}>
        {avg > 0 ? '+' : ''}{avg.toFixed(2)}%
      </span>
    </div>
  )
}

function RecordRow({ rec }) {
  const badge = REC_BADGE[rec.recommendation] || 'bg-gray-700 text-gray-300 border-gray-600'
  const ret = rec.next_day_return
  const retColor =
    ret === null || ret === undefined
      ? 'text-gray-600'
      : ret > 0
      ? 'text-red-400'
      : ret < 0
      ? 'text-green-400'
      : 'text-gray-400'

  return (
    <div className="grid grid-cols-12 items-center text-xs py-1.5 border-b border-gray-800/60 last:border-b-0">
      <span className="col-span-3 text-gray-500 font-mono">{rec.date}</span>
      <span className="col-span-3">
        <span className={`inline-block px-2 py-0.5 rounded border text-[10px] ${badge}`}>
          {rec.recommendation}
        </span>
      </span>
      <span className="col-span-2 text-gray-400 font-mono text-right">
        {rec.composite_score > 0 ? '+' : ''}
        {rec.composite_score.toFixed(0)}
      </span>
      <span className={`col-span-3 text-right font-mono ${retColor}`}>
        {ret === null || ret === undefined ? '—' : `${ret > 0 ? '+' : ''}${ret.toFixed(2)}%`}
      </span>
      <span className="col-span-1 text-right">
        {rec.correct === true ? (
          <span className="text-green-400">✓</span>
        ) : rec.correct === false ? (
          <span className="text-gray-600">✗</span>
        ) : (
          <span className="text-gray-700">·</span>
        )}
      </span>
    </div>
  )
}

export default function SignalEvalCard({ evalData, days, onDaysChange, loading }) {
  const [showAll, setShowAll] = useState(false)

  if (loading) {
    return (
      <div className="bg-gray-900 border border-gray-800 rounded-xl p-6 text-center text-gray-500">
        复盘加载中…
      </div>
    )
  }

  if (!evalData) {
    return (
      <div className="bg-gray-900 border border-gray-800 rounded-xl p-6 text-center text-gray-500">
        暂无复盘数据
      </div>
    )
  }

  const { total_signals, evaluated, win_rate, avg_return, records } = evalData
  const visible = showAll ? records : records.slice(-8).reverse()
  const winTone =
    win_rate === null || win_rate === undefined
      ? 'gray'
      : win_rate >= 55
      ? 'green'
      : win_rate >= 45
      ? 'yellow'
      : 'red'
  const returnTone =
    avg_return === null || avg_return === undefined
      ? 'gray'
      : avg_return > 0
      ? 'red'
      : avg_return < 0
      ? 'green'
      : 'gray'

  return (
    <div className="bg-gray-900 border border-gray-800 rounded-xl p-6">
      <div className="flex items-center justify-between mb-4">
        <div>
          <h3 className="text-sm font-bold text-gray-200">信号复盘</h3>
          <p className="text-xs text-gray-500 mt-0.5">
            过去 {days} 天 · 信号 {total_signals} 条 · 已评估 {evaluated} 条
          </p>
        </div>
        <select
          value={days}
          onChange={(e) => onDaysChange(Number(e.target.value))}
          className="bg-gray-800 border border-gray-700 text-xs text-gray-300 rounded px-2 py-1"
        >
          <option value={30}>30 天</option>
          <option value={60}>60 天</option>
          <option value={90}>90 天</option>
          <option value={180}>180 天</option>
        </select>
      </div>

      <div className="grid grid-cols-2 gap-3 mb-4">
        <StatCell
          label="方向胜率"
          value={win_rate === null || win_rate === undefined ? null : win_rate.toFixed(1)}
          suffix="%"
          tone={winTone}
        />
        <StatCell
          label="平均次日收益"
          value={avg_return === null || avg_return === undefined ? null : `${avg_return > 0 ? '+' : ''}${avg_return.toFixed(2)}`}
          suffix="%"
          tone={returnTone}
        />
      </div>

      <div className="bg-gray-800/40 rounded-lg p-3 mb-4 space-y-1.5">
        <div className="text-xs text-gray-500 mb-1">分方向次日收益</div>
        <DirectionRow label="试错方向" avg={evalData.avg_return_on_buy} color="#ef4444" />
        <DirectionRow label="观望方向" avg={evalData.avg_return_on_neutral} color="#eab308" />
        <DirectionRow label="规避方向" avg={evalData.avg_return_on_sell} color="#22c55e" />
      </div>

      {records.length === 0 ? (
        <div className="text-center text-xs text-gray-600 py-4">区间内无信号</div>
      ) : (
        <>
          <div className="grid grid-cols-12 text-[10px] text-gray-600 uppercase tracking-wider pb-1 border-b border-gray-800">
            <span className="col-span-3">日期</span>
            <span className="col-span-3">建议</span>
            <span className="col-span-2 text-right">综合分</span>
            <span className="col-span-3 text-right">次日收益</span>
            <span className="col-span-1 text-right">方向</span>
          </div>
          <div className="mt-1">
            {visible.map((rec) => (
              <RecordRow key={rec.date} rec={rec} />
            ))}
          </div>
          {records.length > 8 && (
            <button
              onClick={() => setShowAll((v) => !v)}
              className="mt-2 text-xs text-gray-500 hover:text-gray-300 transition-colors"
            >
              {showAll ? '收起' : `展开全部 ${records.length} 条`}
            </button>
          )}
        </>
      )}

      <p className="mt-4 text-[10px] text-gray-600 leading-relaxed">
        胜率口径：试错方向次日上涨、规避方向次日下跌、观望方向次日波动 ≤ 0.5% 计为正确。
      </p>
    </div>
  )
}
