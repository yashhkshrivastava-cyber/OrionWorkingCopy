import { useMemo, useRef, useState, type ReactNode } from 'react'
import { ChevronDown, ChevronLeft, Search, X } from 'lucide-react'
import type { CatalogGroup } from '../components/data/WorkbenchCatalog'

const HUES = ['indigo', 'cyan', 'green', 'amber', 'coral', 'pink', 'violet', 'blue', 'teal', 'orange']

/**
 * The catalog of a data workbench drawn as an explorer: a search box that narrows every group at once, groups with a coloured badge that fold away,
 * and rows that glow when chosen. Arrow keys move through the rows; Escape clears the search. What is listed and what choosing a row does are exactly
 * what the plain catalog does.
 */
export function LumenCatalog({
  title,
  groups,
  selected,
  onSelect,
  onCollapse,
}: {
  title: string
  groups: CatalogGroup[]
  selected: string
  onSelect: (id: string) => void
  onCollapse?: () => void
}) {
  const [query, setQuery] = useState('')
  const [folded, setFolded] = useState<Record<string, boolean>>({})
  const list = useRef<HTMLDivElement>(null)
  const text = query.trim().toLowerCase()

  const shown = useMemo(
    () =>
      groups
        .map((group, index) => ({
          group,
          hue: HUES[index % HUES.length],
          items: text ? group.items.filter((item) => item.label.toLowerCase().includes(text) || group.label.toLowerCase().includes(text)) : group.items,
        }))
        .filter((entry) => entry.items.length > 0),
    [groups, text],
  )
  const total = groups.reduce((sum, group) => sum + group.items.length, 0)

  const move = (event: React.KeyboardEvent) => {
    if (event.key !== 'ArrowDown' && event.key !== 'ArrowUp') return
    const rows = [...(list.current?.querySelectorAll<HTMLButtonElement>('[data-catalog-row]') ?? [])]
    if (!rows.length) return
    event.preventDefault()
    const at = rows.indexOf(document.activeElement as HTMLButtonElement)
    const next = event.key === 'ArrowDown' ? Math.min(rows.length - 1, at + 1) : Math.max(0, at <= 0 ? 0 : at - 1)
    rows[next]?.focus()
  }

  return (
    <section className="panel flex h-full min-h-0 flex-col overflow-hidden !p-3">
      <div className="flex items-center justify-between gap-2 px-1.5 pb-2 pt-1">
        <div>
          <p className="font-display text-base font-semibold leading-none">{title}</p>
          <p className="t-caption mt-1 text-[color:var(--color-text-faint)]">{total} to choose from</p>
        </div>
        {onCollapse && (
          <button type="button" onClick={onCollapse} aria-label="Collapse catalog" title="Collapse catalog" className="interactive grid h-8 w-8 place-items-center rounded-full text-[color:var(--color-text-faint)] hover:bg-muted hover:text-[color:var(--color-text)]">
            <ChevronLeft className="h-4 w-4" />
          </button>
        )}
      </div>

      <label className="relative mx-1 mb-2 block">
        <span className="sr-only">Find in the catalog</span>
        <Search className="pointer-events-none absolute left-3.5 top-1/2 h-4 w-4 -translate-y-1/2 text-[color:var(--color-text-faint)]" aria-hidden="true" />
        <input
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === 'Escape') setQuery('')
            if (e.key === 'ArrowDown') {
              e.preventDefault()
              list.current?.querySelector<HTMLButtonElement>('[data-catalog-row]')?.focus()
            }
          }}
          placeholder="Find…"
          className="h-10 w-full rounded-full pl-10 pr-9 text-sm"
        />
        {query && (
          <button type="button" onClick={() => setQuery('')} aria-label="Clear" className="absolute right-2 top-1/2 grid h-6 w-6 -translate-y-1/2 place-items-center rounded-full text-[color:var(--color-text-faint)] hover:bg-muted">
            <X className="h-3.5 w-3.5" />
          </button>
        )}
      </label>

      <div ref={list} role="group" aria-label={title} onKeyDown={move} className="scroll-quiet min-h-0 flex-1 space-y-2 overflow-y-auto px-1 pb-2">
        {shown.map(({ group, hue, items }) => {
          const open = text ? true : !folded[group.label]
          return (
            <div key={group.label} style={{ '--hue': `var(--lumen-${hue})` } as React.CSSProperties}>
              <button
                type="button"
                onClick={() => setFolded((now) => ({ ...now, [group.label]: open }))}
                aria-expanded={open}
                className="interactive flex w-full items-center gap-2.5 rounded-2xl px-2 py-1.5 text-left hover:bg-muted/70"
              >
                <span className="lumen-chip grid h-8 w-8 shrink-0 place-items-center rounded-xl [&_svg]:h-4 [&_svg]:w-4">{(group.icon as ReactNode) ?? <span className="h-2 w-2 rounded-full bg-current" />}</span>
                <span className="font-display min-w-0 flex-1 truncate text-sm font-semibold">{group.label}</span>
                <span className="rounded-full bg-muted px-2 text-[11px] font-semibold tabular-nums text-[color:var(--color-text-faint)]">{items.length}</span>
                <ChevronDown className={`h-4 w-4 text-[color:var(--color-text-faint)] transition-transform duration-300 ${open ? '' : '-rotate-90'}`} aria-hidden="true" />
              </button>
              {open && (
                <div className="mt-0.5 space-y-0.5 pl-3">
                  {items.map((item) => {
                    const active = item.id === selected
                    return (
                      <button
                        key={item.id}
                        type="button"
                        data-catalog-row
                        onClick={() => onSelect(item.id)}
                        aria-current={active ? 'true' : undefined}
                        className={`interactive group relative flex w-full items-center gap-2.5 rounded-full py-2 pl-3.5 pr-3 text-left text-sm ${
                          active ? 'lumen-catalog-active font-semibold text-[color:var(--color-text)]' : 'text-[color:var(--color-text-muted)] hover:bg-muted/70 hover:text-[color:var(--color-text)]'
                        }`}
                      >
                        <span className={`h-2 w-2 shrink-0 rounded-full transition-transform duration-300 ${active ? 'scale-125' : 'opacity-50 group-hover:opacity-100'}`} style={{ background: 'var(--hue)' }} aria-hidden="true" />
                        <span className="min-w-0 flex-1 truncate">{item.label}</span>
                        {item.meta ? <span className="shrink-0 text-[11px] tabular-nums text-[color:var(--color-text-faint)]">{item.meta}</span> : null}
                      </button>
                    )
                  })}
                </div>
              )}
            </div>
          )
        })}
        {shown.length === 0 && <p className="px-3 py-8 text-center text-sm text-[color:var(--color-text-muted)]">Nothing matches “{query}”.</p>}
      </div>
    </section>
  )
}
