/**
 * Badge — small status/label pill primitive.
 *
 * Props:
 *   tone: 'neutral' | 'bull' | 'bear' | 'watch' | 'cyan' | 'amber'
 *         (default 'neutral')
 *   className: extra classes
 *   All native <span> props are forwarded.
 *
 * Tones map to the project's semantic colours:
 *   bull  = red  (buy-side / bullish in A-share convention)
 *   bear  = green (sell-side / bearish in A-share convention)
 *   watch = amber
 *   cyan  = informational
 */
const TONE = {
  neutral:
    'border-slate-400/40 bg-slate-500/10 text-slate-600 dark:text-slate-300',
  bull:
    'border-red-500/35 bg-red-500/10 text-red-700 dark:text-red-200',
  bear:
    'border-emerald-500/35 bg-emerald-500/10 text-emerald-700 dark:text-emerald-200',
  watch:
    'border-amber-500/35 bg-amber-500/10 text-amber-700 dark:text-amber-200',
  cyan:
    'border-cyan-600/30 bg-cyan-600/10 text-cyan-700 dark:text-cyan-200',
  amber:
    'border-amber-500/35 bg-amber-500/10 text-amber-700 dark:text-amber-200',
}

export default function Badge({ tone = 'neutral', className = '', children, ...props }) {
  const toneClass = TONE[tone] ?? TONE.neutral
  return (
    <span
      className={`inline-flex items-center rounded-sm border px-2 py-0.5 text-[11px] font-semibold ${toneClass} ${className}`}
      {...props}
    >
      {children}
    </span>
  )
}
