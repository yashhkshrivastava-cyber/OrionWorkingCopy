import { useEffect, useId, useMemo, useRef, useState, type KeyboardEvent } from 'react'
import { Check, ChevronDown, Plus, Search, X } from 'lucide-react'

/** A shortcut shown above the list, for the choice people make most ("all 53 cities in Madhya Pradesh"). */
export type MultiSelectAction = {
  label: string
  /** Given ways to add or remove several at once, which keep to the `max` and the spelling already chosen. */
  onClick: (helpers: { add: (items: string[]) => void; remove: (items: string[]) => void }) => void
  disabled?: boolean
  title?: string
}

const ROW_LIMIT = 300

const same = (a: string, b: string) => a.trim().toLowerCase() === b.trim().toLowerCase()

/**
 * Choosing several things from a list, without adding them one at a time.
 *
 * - A button opens a panel with a search box over the whole list; each row is a checkbox, so a choice is one click and stays on screen.
 * - "Select all" takes everything the search shows (everything, when nothing is typed), "Clear" lets go of them; `actions` add shortcuts of the caller's own.
 * - With `allowCustom` a word that is not in the list can be added (Enter), so the list is a help and never a limit.
 * - What is chosen is shown as chips under the button, the first few at a time with "+N more", and one "Clear all".
 * - The keyboard does all of it: type to search, ↑ ↓ to move, Enter to tick or add, Esc to close.
 *
 * The panel opens in the page (it pushes what is below it down) rather than floating, so a dialog never cuts it off and a small screen has room for it.
 */
export function MultiSelect({
  label,
  values,
  onChange,
  options,
  noun = ['item', 'items'],
  placeholder,
  searchPlaceholder,
  allowCustom = false,
  separator,
  max,
  actions = [],
  emptyText,
  chipLimit = 8,
  disabled = false,
}: {
  /** What this chooses, for people using a screen reader. */
  label: string
  values: string[]
  onChange: (next: string[]) => void
  options: string[]
  /** The word for one and for several, used in the counts ("12 cities selected"). */
  noun?: [string, string]
  placeholder?: string
  searchPlaceholder?: string
  allowCustom?: boolean
  /** With `allowCustom`, what splits one typed entry into several (a comma, for tags). */
  separator?: RegExp
  /** The most that may be chosen: past it nothing more is added and the panel says so. */
  max?: number
  actions?: MultiSelectAction[]
  emptyText?: string
  chipLimit?: number
  disabled?: boolean
}) {
  const [open, setOpen] = useState(false)
  const [query, setQuery] = useState('')
  const [active, setActive] = useState(0)
  const [expanded, setExpanded] = useState(false)
  const [note, setNote] = useState('')
  const root = useRef<HTMLDivElement>(null)
  const trigger = useRef<HTMLButtonElement>(null)
  const search = useRef<HTMLInputElement>(null)
  const list = useRef<HTMLUListElement>(null)
  const id = useId()

  const picked = useMemo(() => new Set(values.map((v) => v.trim().toLowerCase())), [values])
  const isPicked = (value: string) => picked.has(value.trim().toLowerCase())
  const text = query.trim().toLowerCase()

  // What is chosen but not in the list (typed in, or from another state) is shown first, so nothing chosen can hide.
  const rows = useMemo(() => {
    const listed = new Set(options.map((o) => o.toLowerCase()))
    const extras = values.filter((v) => !listed.has(v.trim().toLowerCase()))
    return [...extras, ...options].filter((v) => !text || v.toLowerCase().includes(text))
  }, [options, values, text])
  const shown = rows.slice(0, ROW_LIMIT)
  const canAdd = allowCustom && text !== '' && !rows.some((row) => same(row, query)) && !isPicked(query)
  const total = shown.length + (canAdd ? 1 : 0)

  const close = () => {
    setOpen(false)
    setQuery('')
    setNote('')
  }

  useEffect(() => {
    if (!open) return
    const onPointer = (event: MouseEvent) => {
      if (root.current && !root.current.contains(event.target as Node)) close()
    }
    document.addEventListener('mousedown', onPointer)
    return () => document.removeEventListener('mousedown', onPointer)
  }, [open])

  useEffect(() => {
    if (open) search.current?.focus()
  }, [open])

  useEffect(() => {
    setActive(0)
  }, [query, open])

  useEffect(() => {
    list.current?.querySelector<HTMLElement>('[data-active="true"]')?.scrollIntoView({ block: 'nearest' })
  }, [active])

  const room = (count: number) => (max === undefined ? count : Math.max(0, max - values.length))
  const clean = (raw: string) => raw.split(/\s+/).filter(Boolean).join(' ')

  const add = (items: string[]) => {
    const fresh = items.map(clean).filter((item) => item && !isPicked(item))
    const allowed = fresh.slice(0, room(fresh.length))
    if (allowed.length < fresh.length) setNote(`At most ${max} ${noun[1]} can be chosen. ${allowed.length ? `${allowed.length} were added.` : 'Remove some first.'}`)
    else setNote('')
    if (allowed.length) onChange([...values, ...allowed])
  }
  const remove = (items: string[]) => {
    setNote('')
    onChange(values.filter((value) => !items.some((item) => same(item, value))))
  }
  const toggle = (value: string) => (isPicked(value) ? remove([value]) : add([value]))

  const typed = () => (separator ? query.split(separator) : [query])

  const chooseActive = () => {
    if (active < shown.length) toggle(shown[active])
    else if (canAdd) {
      add(typed())
      setQuery('')
    }
  }

  const onKey = (event: KeyboardEvent<HTMLInputElement>) => {
    if (event.key === 'ArrowDown') {
      event.preventDefault()
      setActive((index) => Math.min(index + 1, Math.max(total - 1, 0)))
    } else if (event.key === 'ArrowUp') {
      event.preventDefault()
      setActive((index) => Math.max(index - 1, 0))
    } else if (event.key === 'Enter') {
      event.preventDefault()
      chooseActive()
    } else if (event.key === 'Escape') {
      event.preventDefault()
      event.stopPropagation() // closes this panel, not the dialog it is in
      close()
      trigger.current?.focus()
    }
  }

  const allShownPicked = shown.length > 0 && shown.every(isPicked)
  const visibleChips = expanded ? values : values.slice(0, chipLimit)
  const count = values.length
  const summary = count ? `${count} ${count === 1 ? noun[0] : noun[1]} selected` : (placeholder ?? `Choose ${noun[1]}`)

  return (
    <div ref={root} className="space-y-2">
      <button
        ref={trigger}
        type="button"
        disabled={disabled}
        aria-haspopup="listbox"
        aria-expanded={open}
        aria-label={`${label}: ${summary}`}
        onClick={() => (open ? close() : setOpen(true))}
        className="interactive flex min-h-11 w-full items-center justify-between gap-2 rounded-lg border border-[color:var(--color-border-strong)] bg-surface px-3 py-2 text-left text-base text-[color:var(--color-text)] hover:border-[color:var(--color-text-faint)] focus-visible:ring-[3px] focus-visible:ring-[color:var(--orion-ring)] disabled:cursor-not-allowed disabled:opacity-60 sm:min-h-0 sm:text-sm"
      >
        <span className={count ? 'font-medium' : 'text-[color:var(--color-text-faint)]'}>{summary}</span>
        <ChevronDown className={`h-4 w-4 shrink-0 text-[color:var(--color-text-muted)] transition-transform ${open ? 'rotate-180' : ''}`} aria-hidden="true" />
      </button>

      {open && (
        <div className="rounded-xl border border-[color:var(--color-border)] bg-surface shadow-sm">
          <div className="relative border-b border-[color:var(--color-border)] p-2">
            <Search className="pointer-events-none absolute left-4 top-1/2 h-4 w-4 -translate-y-1/2 text-[color:var(--color-text-faint)]" aria-hidden="true" />
            <input
              ref={search}
              role="combobox"
              aria-expanded="true"
              aria-controls={`${id}-list`}
              aria-activedescendant={total ? `${id}-row-${active}` : undefined}
              aria-label={`Search ${noun[1]}`}
              value={query}
              onChange={(event) => setQuery(event.target.value)}
              onKeyDown={onKey}
              placeholder={searchPlaceholder ?? (allowCustom ? `Search or type a new one, then Enter` : `Search ${noun[1]}`)}
              className="w-full rounded-lg border border-[color:var(--color-border)] bg-surface py-2 pl-9 pr-3 text-sm text-[color:var(--color-text)] placeholder:text-[color:var(--color-text-faint)] focus:border-accent focus:outline-none focus:ring-[3px] focus:ring-[color:var(--orion-ring)]"
            />
          </div>

          <div className="flex flex-wrap items-center gap-x-4 gap-y-1.5 border-b border-[color:var(--color-border)] px-3 py-2 text-xs">
            {actions.map((action) => (
              <button
                key={action.label}
                type="button"
                disabled={action.disabled}
                title={action.title}
                onClick={() => {
                  setNote('')
                  action.onClick({ add, remove })
                }}
                className="rounded-full bg-accent-dim px-2.5 py-1 font-semibold text-accent hover:bg-accent/15 disabled:cursor-not-allowed disabled:opacity-50"
              >
                {action.label}
              </button>
            ))}
            <button
              type="button"
              disabled={!shown.length || allShownPicked}
              onClick={() => add(shown)}
              className="font-medium text-accent hover:underline disabled:cursor-not-allowed disabled:no-underline disabled:opacity-40"
            >
              {text ? `Select all ${shown.length} shown` : `Select all ${shown.length}`}
            </button>
            <button
              type="button"
              disabled={!shown.some(isPicked)}
              onClick={() => remove(shown)}
              className="font-medium text-accent hover:underline disabled:cursor-not-allowed disabled:no-underline disabled:opacity-40"
            >
              {text ? 'Clear these' : 'Clear all'}
            </button>
            <span className="ml-auto t-caption" aria-live="polite">
              {count} {count === 1 ? noun[0] : noun[1]} selected
            </span>
          </div>

          <ul ref={list} id={`${id}-list`} role="listbox" aria-multiselectable="true" aria-label={label} className="scroll-quiet max-h-64 overflow-y-auto p-1">
            {shown.map((value, index) => {
              const on = isPicked(value)
              return (
                <li
                  key={value}
                  id={`${id}-row-${index}`}
                  role="option"
                  aria-selected={on}
                  data-active={index === active}
                  onMouseMove={() => setActive(index)}
                  onClick={() => {
                    toggle(value)
                    search.current?.focus()
                  }}
                  className={`flex cursor-pointer items-center gap-2.5 rounded-lg px-2.5 py-2 text-sm ${index === active ? 'bg-muted' : ''}`}
                >
                  <span
                    aria-hidden="true"
                    className={`flex h-4 w-4 shrink-0 items-center justify-center rounded border ${on ? 'border-primary bg-primary text-on-primary' : 'border-[color:var(--color-border-strong)] bg-surface'}`}
                  >
                    {on && <Check className="h-3 w-3" strokeWidth={3} />}
                  </span>
                  <span className={on ? 'font-medium' : ''}>{value}</span>
                </li>
              )
            })}
            {canAdd && (
              <li
                id={`${id}-row-${shown.length}`}
                role="option"
                aria-selected="false"
                data-active={active === shown.length}
                onMouseMove={() => setActive(shown.length)}
                onClick={() => {
                  add(typed())
                  setQuery('')
                  search.current?.focus()
                }}
                className={`flex cursor-pointer items-center gap-2.5 rounded-lg px-2.5 py-2 text-sm text-accent ${active === shown.length ? 'bg-muted' : ''}`}
              >
                <Plus className="h-4 w-4 shrink-0" aria-hidden="true" />
                <span>
                  Add “{clean(query)}”
                </span>
              </li>
            )}
            {!total && <li className="px-3 py-4 text-center text-sm text-[color:var(--color-text-muted)]">{emptyText ?? (text ? `No ${noun[1]} match “${query.trim()}”.` : `No ${noun[1]} to choose from.`)}</li>}
            {rows.length > ROW_LIMIT && <li className="px-3 py-2 text-center t-caption">Showing the first {ROW_LIMIT} of {rows.length}. Type to narrow the list.</li>}
          </ul>

          <div className="flex items-center justify-between gap-3 border-t border-[color:var(--color-border)] px-3 py-2">
            <p className={`t-caption ${note ? 'text-warning' : ''}`} role={note ? 'alert' : undefined}>
              {note || (max !== undefined ? `Up to ${max} ${noun[1]}.` : '↑ ↓ to move, Enter to choose, Esc to close.')}
            </p>
            <button
              type="button"
              onClick={() => {
                close()
                trigger.current?.focus()
              }}
              className="rounded-lg bg-primary px-3 py-1.5 text-sm font-semibold text-on-primary hover:opacity-90"
            >
              Done
            </button>
          </div>
        </div>
      )}

      {count > 0 && (
        <div className="flex flex-wrap items-center gap-1.5">
          {visibleChips.map((value) => (
            <span key={value} className="inline-flex max-w-full items-center gap-1 rounded-full bg-accent-dim px-2.5 py-1 text-xs font-medium text-accent">
              <span className="truncate">{value}</span>
              <button
                type="button"
                disabled={disabled}
                aria-label={`Remove ${value}`}
                className="interactive rounded-full p-0.5 hover:bg-accent/15"
                onClick={() => remove([value])}
              >
                <X className="h-3 w-3" aria-hidden="true" />
              </button>
            </span>
          ))}
          {count > chipLimit && (
            <button type="button" onClick={() => setExpanded((value) => !value)} className="rounded-full px-2 py-1 text-xs font-medium text-accent hover:underline">
              {expanded ? 'Show fewer' : `+${count - chipLimit} more`}
            </button>
          )}
          {count > 1 && !disabled && (
            <button type="button" onClick={() => remove(values)} className="ml-auto rounded-full px-2 py-1 text-xs font-medium text-[color:var(--color-text-muted)] hover:text-negative">
              Clear all
            </button>
          )}
        </div>
      )}
    </div>
  )
}
