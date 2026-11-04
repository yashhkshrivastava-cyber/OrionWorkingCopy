import { useEffect, useMemo, useRef, useState, type KeyboardEvent as ReactKeyboardEvent } from 'react'
import { Check, ChevronDown, Search } from 'lucide-react'

export type SearchOption = { id: string; label: string }

export function optionIdEquals(optionId: string, value: unknown): boolean {
  return String(optionId ?? '').trim() === String(value ?? '').trim()
}

function matches(option: SearchOption, query: string): boolean {
  const parts = query.trim().toLowerCase().split(/\s+/).filter(Boolean)
  if (!parts.length) return true
  const hay = `${option.label} ${option.id}`.toLowerCase()
  return parts.every((part) => hay.includes(part))
}

/**
 * Dropdown you can type into. Native &lt;select&gt; cannot search, and lookup
 * lists (cases, employees, records) are too long to scroll.
 */
export function SearchSelect({
  value,
  options,
  onChange,
  placeholder = '— Select —',
  disabled = false,
  allowEmpty = true,
  emptyLabel,
  fallbackLabel,
}: {
  value: string
  options: SearchOption[]
  onChange: (value: string | null) => void
  placeholder?: string
  disabled?: boolean
  allowEmpty?: boolean
  emptyLabel?: string
  /** Shown when the stored code has not matched an option yet (update hydrate). */
  fallbackLabel?: string
}) {
  const [open, setOpen] = useState(false)
  const [query, setQuery] = useState('')
  const [active, setActive] = useState(0)
  const root = useRef<HTMLDivElement>(null)
  const search = useRef<HTMLInputElement>(null)
  const list = useRef<HTMLDivElement>(null)

  const selected = options.find((option) => optionIdEquals(option.id, value))
  const shown = selected?.label || fallbackLabel || ''
  const filtered = useMemo(() => options.filter((option) => matches(option, query)), [options, query])

  useEffect(() => {
    if (!open) return
    setQuery('')
    const selectedIndex = options.findIndex((option) => optionIdEquals(option.id, value))
    setActive(selectedIndex >= 0 ? selectedIndex : 0)
    const timer = window.setTimeout(() => search.current?.focus(), 0)
    const onPointer = (event: MouseEvent) => {
      if (root.current && !root.current.contains(event.target as Node)) setOpen(false)
    }
    const onKey = (event: globalThis.KeyboardEvent) => {
      if (event.key === 'Escape') setOpen(false)
    }
    document.addEventListener('mousedown', onPointer)
    document.addEventListener('keydown', onKey)
    return () => {
      window.clearTimeout(timer)
      document.removeEventListener('mousedown', onPointer)
      document.removeEventListener('keydown', onKey)
    }
  }, [open, options, value])

  useEffect(() => {
    if (!open) return
    const node = list.current?.querySelector('[data-active="true"]')
    node?.scrollIntoView({ block: 'nearest' })
  }, [active, open, filtered])

  const pick = (id: string | null) => {
    onChange(id)
    setOpen(false)
  }

  const onSearchKey = (event: ReactKeyboardEvent<HTMLInputElement>) => {
    if (event.key === 'ArrowDown') {
      event.preventDefault()
      setActive((index) => Math.min(index + 1, Math.max(filtered.length - 1, 0)))
    } else if (event.key === 'ArrowUp') {
      event.preventDefault()
      setActive((index) => Math.max(index - 1, 0))
    } else if (event.key === 'Enter') {
      event.preventDefault()
      const option = filtered[active]
      if (option) pick(option.id)
      else if (allowEmpty && !query.trim()) pick(null)
    }
  }

  return (
    <div ref={root} className="relative">
      <button
        type="button"
        disabled={disabled}
        aria-haspopup="listbox"
        aria-expanded={open}
        onClick={() => !disabled && setOpen((value) => !value)}
        className={`flex min-h-11 w-full items-center justify-between gap-2 rounded-lg border bg-surface px-3 py-2 text-left text-base transition-colors duration-[var(--orion-dur-fast)] sm:min-h-0 sm:text-sm ${
          disabled
            ? 'cursor-not-allowed border-[color:var(--color-border)] text-[color:var(--color-text-faint)]'
            : 'cursor-pointer border-[color:var(--color-border-strong)] bg-surface text-[color:var(--color-text)] hover:border-[color:var(--color-text-faint)] focus:border-accent focus:ring-[3px] focus:ring-[color:var(--orion-ring)]'
        }`}
      >
        <span className={`min-w-0 truncate ${shown ? '' : 'text-[color:var(--color-text-faint)]'}`} title={shown || undefined}>
          {shown || placeholder}
        </span>
        <ChevronDown className={`h-4 w-4 shrink-0 text-[color:var(--color-text-faint)] transition-transform ${open ? 'rotate-180' : ''}`} />
      </button>

      {open && (
        <div className="pop-in overlay absolute z-30 mt-1 w-full origin-top overflow-hidden rounded-lg border border-[color:var(--color-border)]">
          <div className="flex items-center gap-2 border-b border-[color:var(--color-border)] px-2.5 py-2">
            <Search className="h-3.5 w-3.5 shrink-0 text-[color:var(--color-text-faint)]" />
            <input
              ref={search}
              value={query}
              onChange={(event) => {
                setQuery(event.target.value)
                setActive(0)
              }}
              onKeyDown={onSearchKey}
              placeholder="Type to search…"
              className="w-full bg-transparent text-sm text-[color:var(--color-text)] outline-none placeholder:text-[color:var(--color-text-faint)]"
            />
          </div>
          <div ref={list} role="listbox" className="max-h-56 overflow-y-auto py-1">
            {allowEmpty && !query.trim() && (
              <button
                type="button"
                role="option"
                aria-selected={!value}
                onClick={() => pick(null)}
                className={`block w-full truncate px-3 py-1.5 text-left text-sm text-[color:var(--color-text-faint)] hover:bg-muted ${
                  !value ? 'bg-muted' : ''
                }`}
              >
                {emptyLabel || placeholder}
              </button>
            )}
            {filtered.length === 0 ? (
              <p className="px-3 py-2 text-xs text-[color:var(--color-text-faint)]">
                {options.length ? 'No matches' : 'Nothing to choose from'}
              </p>
            ) : (
              filtered.map((option, index) => {
                const isSelected = optionIdEquals(option.id, value)
                const isActive = index === active
                return (
                  <button
                    key={option.id}
                    type="button"
                    role="option"
                    aria-selected={isSelected}
                    data-active={isActive}
                    onMouseEnter={() => setActive(index)}
                    onClick={() => pick(option.id)}
                    className={`flex w-full items-start justify-between gap-2 px-3 py-1.5 text-left text-sm ${
                      isActive
                        ? 'bg-accent-dim text-[color:var(--color-text)]'
                        : 'text-[color:var(--color-text)] hover:bg-muted'
                    }`}
                  >
                    <span className="min-w-0 whitespace-normal leading-snug" title={option.label}>{option.label}</span>
                    {isSelected && <Check className="h-3.5 w-3.5 shrink-0 text-accent" />}
                  </button>
                )
              })
            )}
          </div>
        </div>
      )}
    </div>
  )
}
