import { useState, type ReactNode } from 'react'
import { ChevronDown } from 'lucide-react'

/**
 * A titled group of visuals, so a long tab reads as a few chapters instead of one wall of cards. `collapsible`
 * keeps the detail (a big table, a scorecard) one click away and does not draw it until it is opened.
 */
export function Section({
  title,
  description,
  actions,
  collapsible = false,
  defaultOpen = true,
  children,
}: {
  title: string
  description?: string
  actions?: ReactNode
  collapsible?: boolean
  defaultOpen?: boolean
  children: ReactNode
}) {
  const [open, setOpen] = useState(defaultOpen || !collapsible)

  const heading = (
    <div className="min-w-0 text-left">
      <h2 className="t-h2 lumen-section-title text-[color:var(--color-text)]">{title}</h2>
      {description && <p className="mt-0.5 text-xs text-[color:var(--color-text-muted)]">{description}</p>}
    </div>
  )

  return (
    <section aria-label={title} className="space-y-3">
      <header className="flex items-end justify-between gap-3">
        {collapsible ? (
          <button
            type="button"
            onClick={() => setOpen((value) => !value)}
            aria-expanded={open}
            className="interactive -ml-2 flex min-w-0 items-center gap-2 rounded-lg px-2 py-1 hover:bg-muted"
          >
            {heading}
            <ChevronDown
              className={`h-4 w-4 shrink-0 text-[color:var(--color-text-faint)] transition-transform ${open ? 'rotate-180' : ''}`}
              aria-hidden="true"
            />
          </button>
        ) : (
          heading
        )}
        {actions && <div className="flex shrink-0 items-center gap-2">{actions}</div>}
      </header>
      {open && children}
    </section>
  )
}
