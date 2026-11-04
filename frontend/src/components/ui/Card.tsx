import type { ReactNode } from 'react'

interface CardProps {
  children: ReactNode
  className?: string
  padding?: 'sm' | 'md' | 'lg'
  /** A small coloured marker beside the card's heading, to tell sibling cards apart. */
  accent?: 'blue' | 'teal' | 'amber' | 'violet' | 'rose' | 'emerald'
}

const paddingMap = { sm: 'p-4', md: 'p-5', lg: 'p-6' }

// The markers are tokens too: brand follows the accent, the others are the status colours.
const accentMap = {
  blue: 'before:bg-brand-500',
  teal: 'before:bg-brand-500',
  amber: 'before:bg-amber',
  violet: 'before:bg-alt-500',
  rose: 'before:bg-negative',
  emerald: 'before:bg-positive',
}

export function Card({ children, className = '', padding = 'md', accent }: CardProps) {
  return (
    <div
      className={`panel relative ${paddingMap[padding]} ${
        accent
          ? `before:absolute before:left-0 before:top-5 before:h-5 before:w-1 before:rounded-r ${accentMap[accent]}`
          : ''
      } ${className}`}
    >
      {children}
    </div>
  )
}

export function CardHeader({
  title,
  subtitle,
  action,
}: {
  title: string
  subtitle?: string
  action?: ReactNode
}) {
  return (
    <div className="mb-4 flex items-start justify-between gap-4">
      <div className="min-w-0">
        <h3 className="t-h3 text-[color:var(--color-text)]">{title}</h3>
        {subtitle && <p className="t-caption mt-0.5">{subtitle}</p>}
      </div>
      {action}
    </div>
  )
}
