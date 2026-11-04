import type { ButtonHTMLAttributes, ReactNode } from 'react'

type Variant = 'primary' | 'secondary' | 'ghost' | 'danger' | 'strong'
type Size = 'sm' | 'md' | 'lg'

interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: Variant
  size?: Size
  loading?: boolean
  children: ReactNode
}

/*
 * Every variant is made of tokens, so a theme restyles all of them at once.
 *   primary    the one action a screen is about: the theme's accent, solid or gradient, with its glow
 *   secondary  a normal action
 *   ghost      a quiet action beside others
 *   danger     deletes and cancellations
 *   strong     the emphasised action on a screen that already has a primary: the text colour inverted
 */
const variants: Record<Variant, string> = {
  primary: 'btn-primary font-semibold',
  secondary:
    'bg-surface text-[color:var(--color-text)] font-medium border border-[color:var(--color-border-strong)] shadow-card hover:bg-surface-hover hover:border-[color:var(--color-text-faint)]',
  ghost:
    'text-[color:var(--color-text-muted)] font-medium border border-transparent hover:text-[color:var(--color-text)] hover:bg-muted',
  danger:
    'bg-negative text-on-negative font-semibold border border-transparent shadow-card hover:brightness-110',
  strong:
    'bg-[color:var(--color-text)] text-[color:var(--color-bg)] font-semibold border border-[color:var(--color-text)] shadow-card hover:opacity-90',
}

const sizes: Record<Size, string> = {
  sm: 'h-8 px-3 text-xs rounded-lg',
  md: 'h-9 px-4 text-sm rounded-lg',
  lg: 'h-11 px-5 text-sm rounded-xl',
}

export function Button({
  variant = 'primary',
  size = 'md',
  loading,
  className = '',
  disabled,
  children,
  ...props
}: ButtonProps) {
  return (
    <button
      type="button"
      className={`interactive inline-flex shrink-0 items-center justify-center gap-2 whitespace-nowrap disabled:pointer-events-none disabled:opacity-50 disabled:shadow-none ${variants[variant]} ${sizes[size]} ${className}`}
      disabled={disabled || loading}
      aria-busy={loading || undefined}
      {...props}
    >
      {loading && (
        <span className="h-4 w-4 animate-spin rounded-full border-2 border-current border-t-transparent" aria-hidden="true" />
      )}
      {children}
    </button>
  )
}
