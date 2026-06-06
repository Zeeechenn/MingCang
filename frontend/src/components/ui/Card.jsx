/**
 * Card — surface panel primitive.
 *
 * Props:
 *   variant: 'default' | 'alt'   (default 'default')
 *   className: extra classes
 *   All native <div> props are forwarded.
 *
 * 'default' matches the project's main panel style (PANEL).
 * 'alt'     matches the lighter panel style (PANEL_ALT).
 */
const VARIANT = {
  default:
    'rounded-sm border border-stone-300/80 bg-[#faf6ec] dark:border-slate-700 dark:bg-[#1d232e]',
  alt:
    'rounded-sm border border-stone-300/80 bg-[#fffaf0] dark:border-slate-700 dark:bg-[#222936]',
  inset:
    'rounded-sm border border-stone-300 bg-[#f3eddc] dark:border-slate-700 dark:bg-[#161b25]',
}

export default function Card({ variant = 'default', className = '', children, ...props }) {
  const variantClass = VARIANT[variant] ?? VARIANT.default
  return (
    <div className={`${variantClass} ${className}`} {...props}>
      {children}
    </div>
  )
}
