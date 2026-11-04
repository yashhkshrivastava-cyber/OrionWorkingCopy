import type { ReactNode } from 'react'

export function PageHeader({
  eyebrow,
  title,
  subtitle,
  action,
}: {
  eyebrow?: string
  title: string
  subtitle?: string
  action?: ReactNode
}) {
  return (
    <header className="page-enter mb-6">
      <div className="flex flex-col gap-3 sm:flex-row sm:items-end sm:justify-between">
        <div className="min-w-0">
          {eyebrow && <p className="eyebrow mb-1.5">{eyebrow}</p>}
          <h1 className="t-h1 lumen-title text-[color:var(--color-text)]">{title}</h1>
          {subtitle && <p className="t-small mt-1 max-w-2xl text-[color:var(--color-text-muted)]">{subtitle}</p>}
        </div>
        {action}
      </div>
    </header>
  )
}
