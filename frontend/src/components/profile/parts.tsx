import type { ReactNode } from 'react'

/** The first letter of a name on a coloured tile, so a long list of clients, cases or people can be told apart at a glance. */
export function Mark({ name, size = 'md' }: { name: string; size?: 'md' | 'lg' }) {
  return (
    <span
      className={`grid shrink-0 place-items-center font-bold text-on-primary [background-image:var(--orion-highlight-fill)] ${size === 'lg' ? 'h-16 w-16 rounded-3xl text-2xl' : 'h-12 w-12 rounded-2xl text-lg'}`}
      aria-hidden="true"
    >
      {name.trim()[0]?.toUpperCase() ?? '?'}
    </span>
  )
}

/** A titled card on a profile page. */
export function Section({ title, hint, action, children }: { title: string; hint?: string; action?: ReactNode; children: ReactNode }) {
  return (
    <section className="panel !p-5">
      <header className="mb-3 flex flex-wrap items-baseline justify-between gap-2">
        <div>
          <h2 className="t-h3">{title}</h2>
          {hint && <p className="t-caption text-[color:var(--color-text-muted)]">{hint}</p>}
        </div>
        {action}
      </header>
      {children}
    </section>
  )
}

/** One line of a details list; nothing when there is nothing to say. */
export function Fact({ label, value }: { label: string; value: string | null | undefined }) {
  if (!value) return null
  return (
    <div className="flex flex-wrap items-baseline justify-between gap-x-4 gap-y-0.5 py-1.5">
      <dt className="t-caption text-[color:var(--color-text-muted)]">{label}</dt>
      <dd className="text-right text-sm font-medium">{value}</dd>
    </div>
  )
}

/** What a card says when there is nothing to list. */
export function Nothing({ children }: { children: ReactNode }) {
  return <p className="rounded-2xl bg-muted px-4 py-3 text-sm text-[color:var(--color-text-muted)]">{children}</p>
}

/** A small status word: green for good, grey for ended, as on the other pages. */
export function StatusPill({ status }: { status: string | null | undefined }) {
  const inactive = status === 'Inactive' || status === 'Left organisation'
  return <span className={`rounded-full px-2.5 py-1 text-xs font-bold ${inactive ? 'bg-muted text-[color:var(--color-text-muted)]' : 'bg-positive-dim text-positive'}`}>{status ?? 'Active'}</span>
}
