import type { ReactNode } from 'react'
import { Check } from 'lucide-react'

/** A titled card of fields: a form read one section at a time instead of as one long grid. */
export function FormSection({ title, hint, children }: { title?: string; hint?: string; children: ReactNode }) {
  return (
    <section className="rounded-[1.5rem] border border-[color:var(--color-border)] bg-[color:color-mix(in_srgb,var(--orion-surface)_70%,transparent)] p-4 sm:p-5">
      {title && (
        <header className="mb-4 flex items-baseline justify-between gap-3">
          <h3 className="font-display text-base font-semibold">{title}</h3>
          {hint && <p className="t-caption text-[color:var(--color-text-faint)]">{hint}</p>}
        </header>
      )}
      {children}
    </section>
  )
}

/** How much of the form that must be filled is filled: a bar that fills, and the words for it. */
export function FormProgress({ done, total }: { done: number; total: number }) {
  const complete = done >= total
  return (
    <div className="flex items-center gap-3 rounded-full border border-[color:var(--color-border)] bg-[color:color-mix(in_srgb,var(--orion-surface)_70%,transparent)] px-4 py-2" role="status">
      <span className={`grid h-6 w-6 shrink-0 place-items-center rounded-full text-[11px] font-bold ${complete ? 'bg-positive text-on-primary' : 'bg-accent-dim text-accent'}`}>{complete ? <Check className="h-3.5 w-3.5" strokeWidth={3} /> : done}</span>
      <div className="min-w-0 flex-1">
        <div className="h-1.5 overflow-hidden rounded-full bg-muted" aria-hidden="true">
          <div className="h-full rounded-full transition-[width] duration-500 [background-image:var(--orion-highlight-fill)]" style={{ width: `${(done / total) * 100}%` }} />
        </div>
      </div>
      <span className="shrink-0 text-xs font-medium text-[color:var(--color-text-muted)]">{complete ? 'All required fields are filled' : `${done} of ${total} required`}</span>
    </div>
  )
}

/** A short list of fixed choices as pills you tap, instead of a drop-down: one tap, and you see all of them. */
export function SegmentedChoice({
  label,
  value,
  options,
  allowClear,
  disabled,
  onChange,
}: {
  label: string
  value: string
  options: { id: string; label: string }[]
  allowClear: boolean
  disabled?: boolean
  onChange: (next: string | null) => void
}) {
  return (
    <div role="radiogroup" aria-label={label} className="flex flex-wrap gap-1.5">
      {options.map((option) => {
        const on = String(option.id) === value
        return (
          <button
            key={option.id}
            type="button"
            role="radio"
            aria-checked={on}
            disabled={disabled}
            onClick={() => onChange(on && allowClear ? null : option.id)}
            className={`interactive inline-flex h-10 items-center rounded-full border px-4 text-sm font-semibold disabled:opacity-60 ${
              on ? 'border-transparent text-on-primary [background-image:var(--orion-primary-fill)] shadow-card' : 'border-[color:var(--color-border-strong)] bg-surface text-[color:var(--color-text-muted)] hover:border-[color:var(--color-accent)] hover:text-[color:var(--color-text)]'
            }`}
          >
            {option.label}
          </button>
        )
      })}
    </div>
  )
}

const iso = (day: Date) => `${day.getFullYear()}-${String(day.getMonth() + 1).padStart(2, '0')}-${String(day.getDate()).padStart(2, '0')}`

/** Shortcuts under a date field for the days people usually mean. */
export function QuickDates({ onPick }: { onPick: (day: string) => void }) {
  const pick = (offset: number) => {
    const day = new Date()
    day.setDate(day.getDate() + offset)
    onPick(iso(day))
  }
  const first = () => {
    const day = new Date()
    onPick(iso(new Date(day.getFullYear(), day.getMonth(), 1)))
  }
  const chip = 'interactive rounded-full border border-[color:var(--color-border)] px-2.5 py-0.5 text-[11px] font-semibold text-[color:var(--color-text-muted)] hover:border-[color:var(--color-accent)] hover:text-accent'
  return (
    <div className="mt-1.5 flex flex-wrap gap-1.5">
      <button type="button" className={chip} onClick={() => pick(0)}>
        Today
      </button>
      <button type="button" className={chip} onClick={() => pick(-1)}>
        Yesterday
      </button>
      <button type="button" className={chip} onClick={first}>
        Start of month
      </button>
    </div>
  )
}
