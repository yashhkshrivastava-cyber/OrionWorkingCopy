import { useCallback, useEffect, useLayoutEffect, useRef, useState } from 'react'
import { createPortal } from 'react-dom'
import { Filter, X } from 'lucide-react'
import { Button } from '../components/ui/Button'
import { Input, Select } from '../components/ui/Field'
import {
  describeFilter,
  isComplete,
  OP_LABEL,
  OPS,
  takesValue,
  type ColumnFilter,
  type FilterKind,
  type FilterOp,
  type PickList,
} from './columnFilter'

/**
 * The funnel in a column's header. It opens a small panel under it with two ways to filter the column: a condition (contains, is more than,
 * is between, is empty…) or a pick of the values the column holds, with how many rows each is on. Apply puts the filter on the table; Clear takes it off.
 *
 * `loadValues` supplies the pick list (the server's, or the rows in the page); without it only conditions are offered.
 */
export function ColumnFilterMenu({
  column,
  label,
  kind,
  filter,
  loadValues,
  onChange,
}: {
  column: string
  label: string
  kind: FilterKind
  filter?: ColumnFilter
  loadValues?: (contains: string) => Promise<PickList>
  onChange: (next: ColumnFilter | null) => void
}) {
  const [open, setOpen] = useState(false)
  const button = useRef<HTMLButtonElement>(null)
  const panel = useRef<HTMLDivElement>(null)
  const [at, setAt] = useState<{ left: number; top: number }>({ left: 0, top: 0 })

  const place = useCallback(() => {
    const anchor = button.current?.getBoundingClientRect()
    if (!anchor) return
    const width = 304
    const left = Math.max(8, Math.min(anchor.left, window.innerWidth - width - 8))
    setAt({ left, top: anchor.bottom + 6 })
  }, [])

  useLayoutEffect(() => {
    if (open) place()
  }, [open, place])

  useEffect(() => {
    if (!open) return
    const close = (event: Event) => {
      if (event.type === 'keydown' && (event as KeyboardEvent).key !== 'Escape') return
      if (event.type === 'pointerdown' && (panel.current?.contains(event.target as Node) || button.current?.contains(event.target as Node))) return
      if (event.type === 'scroll' && panel.current?.contains(event.target as Node)) return
      setOpen(false)
      if (event.type === 'keydown') button.current?.focus()
    }
    window.addEventListener('pointerdown', close)
    window.addEventListener('keydown', close)
    window.addEventListener('scroll', close, true)
    window.addEventListener('resize', place)
    return () => {
      window.removeEventListener('pointerdown', close)
      window.removeEventListener('keydown', close)
      window.removeEventListener('scroll', close, true)
      window.removeEventListener('resize', place)
    }
  }, [open, place])

  const active = Boolean(filter && isComplete(filter))
  return (
    <>
      <button
        ref={button}
        type="button"
        onClick={(event) => {
          event.stopPropagation()
          setOpen((now) => !now)
        }}
        aria-label={`Filter ${label}`}
        aria-expanded={open}
        title={active && filter ? describeFilter(filter, label, kind) : `Filter ${label}`}
        className={`inline-flex h-5 w-5 shrink-0 items-center justify-center rounded transition-colors focus-visible:ring-2 focus-visible:ring-accent ${
          active ? 'bg-accent-dim text-accent' : 'text-[color:var(--color-text-faint)] opacity-60 hover:bg-muted hover:opacity-100'
        }`}
      >
        <Filter className="h-3 w-3" fill={active ? 'currentColor' : 'none'} />
      </button>
      {open &&
        createPortal(
          <div
            ref={panel}
            role="dialog"
            aria-label={`Filter ${label}`}
            onPointerDown={(event) => event.stopPropagation()}
            style={{ left: at.left, top: at.top }}
            className="overlay fixed z-[85] w-[19rem] rounded-xl border border-[color:var(--color-border)] p-3 text-sm normal-case tracking-normal shadow-lg"
          >
            <Panel
              column={column}
              label={label}
              kind={kind}
              filter={filter}
              loadValues={loadValues}
              onApply={(next) => {
                onChange(next)
                setOpen(false)
              }}
              onClear={() => {
                onChange(null)
                setOpen(false)
              }}
            />
          </div>,
          document.body,
        )}
    </>
  )
}

function Panel({
  column,
  label,
  kind,
  filter,
  loadValues,
  onApply,
  onClear,
}: {
  column: string
  label: string
  kind: FilterKind
  filter?: ColumnFilter
  loadValues?: (contains: string) => Promise<PickList>
  onApply: (next: ColumnFilter) => void
  onClear: () => void
}) {
  const startOp: FilterOp = filter && filter.op !== 'in' ? filter.op : OPS[kind][0]
  const [mode, setMode] = useState<'condition' | 'values'>(filter?.op === 'in' || (kind === 'bool' && loadValues) ? 'values' : 'condition')
  const [op, setOp] = useState<FilterOp>(kind === 'bool' ? 'empty' : startOp)
  const [value, setValue] = useState(filter?.value ?? '')
  const [value2, setValue2] = useState(filter?.value2 ?? '')
  const [picked, setPicked] = useState<Set<string>>(new Set(filter?.values ?? []))
  const [withEmpty, setWithEmpty] = useState(Boolean(filter?.empty))
  const [contains, setContains] = useState('')
  const [list, setList] = useState<PickList | null>(null)
  const [error, setError] = useState('')

  // The values this column holds: read when the pick tab is open, again a moment after the search is typed.
  useEffect(() => {
    if (mode !== 'values' || !loadValues) return
    let stale = false
    const timer = window.setTimeout(() => {
      loadValues(contains)
        .then((found) => !stale && setList(found))
        .catch((e: Error) => !stale && setError(e.message))
    }, contains ? 250 : 0)
    return () => {
      stale = true
      window.clearTimeout(timer)
    }
  }, [mode, contains, loadValues])

  const conditionOps = OPS[kind].filter((o) => o !== 'in' || !loadValues)
  const apply = () => {
    const next: ColumnFilter =
      mode === 'values' ? { column, op: 'in', values: [...picked], empty: withEmpty } : { column, op, value: value.trim(), value2: value2.trim() }
    if (!isComplete(next)) {
      setError(mode === 'values' ? 'Tick at least one value.' : op === 'between' ? 'Give both values.' : 'Give a value to filter by.')
      return
    }
    onApply(next)
  }

  const toggle = (item: string) =>
    setPicked((now) => {
      const next = new Set(now)
      if (next.has(item)) next.delete(item)
      else next.add(item)
      return next
    })

  const inputType = kind === 'date' ? 'date' : 'text'
  return (
    <form
      className="space-y-3"
      onSubmit={(event) => {
        event.preventDefault()
        apply()
      }}
    >
      <div className="flex items-center justify-between gap-2">
        <p className="min-w-0 truncate font-semibold text-[color:var(--color-text)]">Filter {label}</p>
        {loadValues && kind !== 'bool' && (
          <div className="flex shrink-0 overflow-hidden rounded-lg border border-[color:var(--color-border-strong)] text-xs" role="group" aria-label="Way to filter">
            {(['condition', 'values'] as const).map((m) => (
              <button
                key={m}
                type="button"
                aria-pressed={mode === m}
                onClick={() => {
                  setMode(m)
                  setError('')
                }}
                className={`px-2.5 py-1 ${mode === m ? 'bg-accent-dim font-semibold text-[color:var(--color-text)]' : 'text-[color:var(--color-text-muted)] hover:bg-muted'}`}
              >
                {m === 'condition' ? 'Condition' : 'Values'}
              </button>
            ))}
          </div>
        )}
      </div>

      {mode === 'condition' ? (
        <div className="space-y-2">
          <Select aria-label="Condition" value={op} onChange={(event) => setOp(event.target.value as FilterOp)}>
            {conditionOps.map((o) => (
              <option key={o} value={o}>
                {OP_LABEL[kind][o]}
              </option>
            ))}
          </Select>
          {takesValue(op) && (
            <Input
              autoFocus
              type={inputType}
              inputMode={kind === 'number' ? 'decimal' : undefined}
              value={value}
              maxLength={200}
              aria-label="Value"
              placeholder={kind === 'number' ? 'A number' : kind === 'date' ? '' : 'Text to look for'}
              onChange={(event) => setValue(event.target.value)}
            />
          )}
          {op === 'between' && (
            <Input type={inputType} inputMode={kind === 'number' ? 'decimal' : undefined} value={value2} aria-label="And" placeholder={kind === 'number' ? 'and a number' : ''} onChange={(event) => setValue2(event.target.value)} />
          )}
        </div>
      ) : (
        <div className="space-y-2">
          <Input value={contains} aria-label="Find a value" placeholder="Find a value" onChange={(event) => setContains(event.target.value)} />
          <div className="max-h-56 overflow-y-auto rounded-lg border border-[color:var(--color-border)]" role="group" aria-label="Values">
            {!list && !error && <p className="px-3 py-3 text-xs text-[color:var(--color-text-muted)]">Loading…</p>}
            {list && list.values.length === 0 && <p className="px-3 py-3 text-xs text-[color:var(--color-text-muted)]">Nothing is called that.</p>}
            {list?.values.map((item) => {
              const key = item.value ?? '\u0000empty'
              const checked = item.value === null ? withEmpty : picked.has(item.value)
              return (
                <label key={key} className="flex cursor-pointer items-center gap-2 px-3 py-1.5 hover:bg-muted">
                  <input type="checkbox" checked={checked} onChange={() => (item.value === null ? setWithEmpty((v) => !v) : toggle(item.value))} />
                  <span className="min-w-0 flex-1 truncate text-[color:var(--color-text)]" title={item.value ?? ''}>
                    {item.value ?? <em className="text-[color:var(--color-text-muted)]">(empty)</em>}
                  </span>
                  <span className="text-xs tabular-nums text-[color:var(--color-text-faint)]">{item.count}</span>
                </label>
              )
            })}
          </div>
          {list?.truncated && <p className="text-xs text-[color:var(--color-text-muted)]">Only the most common are listed. Type to find another.</p>}
          {picked.size + (withEmpty ? 1 : 0) > 0 && (
            <button type="button" className="text-xs text-accent hover:underline" onClick={() => (setPicked(new Set()), setWithEmpty(false))}>
              Untick all ({picked.size + (withEmpty ? 1 : 0)})
            </button>
          )}
        </div>
      )}

      {error && <p className="text-xs text-negative">{error}</p>}
      <div className="flex items-center justify-between gap-2">
        <Button variant="ghost" size="sm" type="button" onClick={onClear} disabled={!filter}>
          Clear
        </Button>
        <Button size="sm" type="submit">
          Apply
        </Button>
      </div>
    </form>
  )
}

/** The filters that are on, as chips above a table, each taken off with its ×. */
export function FilterChips({
  filters,
  labelOf,
  kindOf,
  onRemove,
  onClear,
}: {
  filters: ColumnFilter[]
  labelOf: (column: string) => string
  kindOf: (column: string) => FilterKind
  onRemove: (column: string) => void
  onClear: () => void
}) {
  const shown = filters.filter(isComplete)
  if (!shown.length) return null
  return (
    <div className="flex flex-wrap items-center gap-1.5" role="group" aria-label="Filters on this table">
      {shown.map((f) => (
        <span key={f.column} className="inline-flex max-w-full items-center gap-1 rounded-full bg-accent-dim py-0.5 pl-2.5 pr-1 text-xs font-medium text-[color:var(--color-text)]">
          <span className="truncate">{describeFilter(f, labelOf(f.column), kindOf(f.column))}</span>
          <button type="button" onClick={() => onRemove(f.column)} aria-label={`Remove the filter on ${labelOf(f.column)}`} className="rounded-full p-0.5 hover:bg-muted">
            <X className="h-3 w-3" />
          </button>
        </span>
      ))}
      {shown.length > 1 && (
        <button type="button" onClick={onClear} className="px-1 text-xs text-[color:var(--color-text-muted)] hover:text-[color:var(--color-text)] hover:underline">
          Clear all
        </button>
      )}
    </div>
  )
}
