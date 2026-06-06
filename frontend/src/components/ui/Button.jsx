/**
 * Button — minimal Tailwind-based button primitive.
 *
 * Props:
 *   variant: 'primary' | 'secondary' | 'ghost' | 'danger'  (default 'secondary')
 *   size:    'sm' | 'md'                                     (default 'sm')
 *   className: extra classes appended after base styles
 *   All native <button> props are forwarded.
 */
const VARIANT = {
  primary:
    'bg-cyan-700 text-white border border-cyan-700 hover:bg-cyan-600 disabled:opacity-50 dark:bg-cyan-300 dark:text-slate-950 dark:border-cyan-300 dark:hover:bg-cyan-200',
  secondary:
    'border border-stone-300 bg-[#f3eddc] text-stone-700 hover:border-cyan-700 hover:text-cyan-700 dark:border-slate-700 dark:bg-[#161b25] dark:text-slate-300 dark:hover:border-cyan-400 dark:hover:text-cyan-200',
  ghost:
    'border border-transparent text-stone-500 hover:border-stone-300 hover:text-stone-700 dark:text-slate-400 dark:hover:border-slate-700 dark:hover:text-slate-200',
  danger:
    'border border-stone-300 text-stone-500 hover:border-red-500 hover:text-red-700 dark:border-slate-700 dark:text-slate-400 dark:hover:border-red-500 dark:hover:text-red-200',
}

const SIZE = {
  sm: 'px-2.5 py-1 text-xs',
  md: 'px-4 py-2 text-sm',
}

export default function Button({
  variant = 'secondary',
  size = 'sm',
  className = '',
  children,
  ...props
}) {
  const base = 'rounded-sm font-medium transition-colors disabled:cursor-not-allowed'
  const variantClass = VARIANT[variant] ?? VARIANT.secondary
  const sizeClass = SIZE[size] ?? SIZE.sm
  return (
    <button type="button" className={`${base} ${variantClass} ${sizeClass} ${className}`} {...props}>
      {children}
    </button>
  )
}
