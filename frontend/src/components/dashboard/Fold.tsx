import { Children, useState, type ReactNode } from 'react'
import { ChevronDown } from 'lucide-react'
import { useLumen } from '../../lumen/useLumen'

/**
 * The first few charts of a dashboard, and the rest one tap away. In Lumen a dashboard opens on the headline row or two and says how many more there are; the plain look shows them all, as
 * it always did. It goes inside the dashboard's grid and lays the "show more" bar across it. Charts that are not shown are not drawn.
 */
export function Fold({ keep, children, label, noun = 'charts and tables' }: { keep: number; children: ReactNode; label?: string; noun?: string }) {
  const lumen = useLumen()
  const [open, setOpen] = useState(false)
  const items = Children.toArray(children)
  // One chart is not worth hiding behind a button.
  if (!lumen || items.length <= keep + 1) return <>{children}</>
  const hidden = items.length - keep
  return (
    <>
      {items.slice(0, keep)}
      {open && items.slice(keep)}
      <div className="flex justify-center lg:col-span-3">
        <button
          type="button"
          aria-expanded={open}
          onClick={() => setOpen((value) => !value)}
          className="interactive inline-flex items-center gap-2 rounded-full border border-[color:var(--color-border-strong)] bg-surface px-5 py-2.5 text-sm font-semibold text-[color:var(--color-text-muted)] shadow-card hover:text-[color:var(--color-text)]"
        >
          {open ? 'Show fewer' : (label ?? `Show ${hidden} more ${noun}`)}
          <ChevronDown className={`h-4 w-4 transition-transform ${open ? 'rotate-180' : ''}`} aria-hidden="true" />
        </button>
      </div>
    </>
  )
}
