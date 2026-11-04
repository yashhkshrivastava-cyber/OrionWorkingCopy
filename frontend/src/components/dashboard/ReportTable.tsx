import { useEffect, useMemo, useRef, useState } from 'react'
import { ArrowDown, ArrowUp, ArrowUpDown, ChevronLeft, ChevronRight, Columns3, Download, Search } from 'lucide-react'
import type { CellFormat, TableBlock, TableColumn } from '../../types'
import { BillNumber } from '../billing/BillNumber'
import { Checkbox } from '../ui/Field'
import { isComplete, matchesFilter, setFilter, valuesFromRows, type ColumnFilter, type FilterKind, type PickList } from '../../tables/columnFilter'
import { ColumnFilterMenu, FilterChips } from '../../tables/ColumnFilterMenu'
import { downloadCsv } from './csv'
import { count, inr, inrFull } from './format'

type Row = Record<string, string | number>
type Sort = { key: string; dir: 'asc' | 'desc' }

function isBlank(value: unknown): boolean {
  return value === null || value === undefined || value === ''
}

function display(value: unknown, format: CellFormat, compact = false): string {
  if (isBlank(value)) return '—'
  if (format === 'money') return compact ? inr(Number(value)) : inrFull(Number(value))
  if (format === 'number') return count(Number(value))
  if (format === 'percent') return `${Number(value).toFixed(1)}%`
  return String(value)
}

/** Text, and bill numbers, which sort as text: 2026-27/9 before 2026-27/10. */
const textual = (format: CellFormat): boolean => format === 'text' || format === 'bill'

function compare(a: unknown, b: unknown, format: CellFormat): number {
  if (isBlank(a) && isBlank(b)) return 0
  if (isBlank(a)) return 1
  if (isBlank(b)) return -1
  if (textual(format)) return String(a).localeCompare(String(b), undefined, { numeric: true, sensitivity: 'base' })
  return Number(a) - Number(b)
}

const PAGE_SIZES = [10, 25, 50]

/**
 * Detail table for the dashboards: sortable, searchable, paged, with a sticky
 * header and a totals row. Rows can still act as cross-filters.
 *
 * Totals come from the server and cover every row the filters select. They are
 * shown only when the server says they are complete, and a search narrows them
 * to a subtotal of the rows on screen rather than leaving a misleading grand total.
 */
export function ReportTable({
  block,
  exportName,
  selected,
  onSelect,
  onOpen,
  emptyMessage = 'Nothing in this selection.',
  searchLabel = 'Search',
  hidden = [],
  defaultSort,
  pageSize = 10,
  negativeTone = false,
  compact = false,
  maxHeight = 420,
}: {
  block: TableBlock
  /** Used for the downloaded file name. */
  exportName: string
  selected?: string
  onSelect?: (code: string) => void
  /** Rows open a record instead of filtering the page. Takes the place of onSelect. */
  onOpen?: (code: string) => void
  emptyMessage?: string
  searchLabel?: string
  /** Column keys hidden until switched on from the Columns menu. */
  hidden?: string[]
  defaultSort?: Sort
  pageSize?: number
  /** Colour negative money red. Only where a negative really is bad news, not a sign convention. */
  negativeTone?: boolean
  /** Show money as lakh and crore. Exact rupees stay for tables meant for checking figures. */
  compact?: boolean
  maxHeight?: number
}) {
  const [sort, setSort] = useState<Sort | undefined>(defaultSort)
  const [query, setQuery] = useState('')
  const [page, setPage] = useState(0)
  const [size, setSize] = useState(pageSize)
  const [off, setOff] = useState<Set<string>>(() => new Set(hidden))
  const [columnsOpen, setColumnsOpen] = useState(false)
  const [filters, setFilters] = useState<ColumnFilter[]>([])
  const columnsRoot = useRef<HTMLDivElement>(null)

  // The Columns menu closes when something else is clicked or Esc is pressed.
  useEffect(() => {
    if (!columnsOpen) return
    const onPointer = (event: MouseEvent) => {
      if (columnsRoot.current && !columnsRoot.current.contains(event.target as Node)) setColumnsOpen(false)
    }
    const onKey = (event: KeyboardEvent) => {
      if (event.key === 'Escape') setColumnsOpen(false)
    }
    document.addEventListener('mousedown', onPointer)
    document.addEventListener('keydown', onKey)
    return () => {
      document.removeEventListener('mousedown', onPointer)
      document.removeEventListener('keydown', onKey)
    }
  }, [columnsOpen])

  const columns = useMemo(() => block.columns.filter((col) => !off.has(col.key)), [block.columns, off])
  const clickable = Boolean(onOpen || (block.filter_key && onSelect))
  const activate = (code: string) => (onOpen ? onOpen(code) : onSelect?.(code))

  const kindOf = (key: string): FilterKind => (textual(block.columns.find((col) => col.key === key)?.format ?? 'text') ? 'text' : 'number')
  const active = filters.filter(isComplete)
  const passes = (row: Row, only: ColumnFilter[]) => only.every((f) => matchesFilter(f, row[f.column], String(row[f.column] ?? ''), kindOf(f.column)))

  const view = useMemo(() => {
    const needle = query.trim().toLowerCase()
    const textKeys = block.columns.filter((col) => textual(col.format)).map((col) => col.key)
    let rows: Row[] = block.rows
    if (needle) {
      rows = rows.filter((row) => textKeys.some((key) => String(row[key] ?? '').toLowerCase().includes(needle)))
    }
    if (active.length) rows = rows.filter((row) => passes(row, active))
    if (sort) {
      const format = block.columns.find((col) => col.key === sort.key)?.format ?? 'text'
      const sign = sort.dir === 'asc' ? 1 : -1
      // A row may carry `<column>_sort` when the displayed text (a formatted date) does not sort correctly.
      const raw = (row: Row) => row[`${sort.key}_sort`] ?? row[sort.key]
      rows = [...rows].sort((a, b) => sign * compare(raw(a), raw(b), format))
    }
    return rows
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [block.rows, block.columns, query, sort, filters])

  const pages = Math.max(1, Math.ceil(view.length / size))
  const current = Math.min(page, pages - 1)
  const slice = view.slice(current * size, current * size + size)

  // Grand total when nothing is narrowed; otherwise a subtotal, and only if every row was loaded.
  const searching = query.trim().length > 0 || active.length > 0
  const totals: Record<string, number> | null = useMemo(() => {
    if (!searching) return block.totals ?? null
    if (block.truncated || !block.totals) return null
    const sums: Record<string, number> = {}
    for (const col of block.columns) {
      if (textual(col.format) || col.format === 'percent' || !(col.key in block.totals)) continue
      sums[col.key] = view.reduce((sum, row) => sum + (Number(row[col.key]) || 0), 0)
    }
    return sums
  }, [searching, block.totals, block.truncated, block.columns, view])

  const toggleSort = (key: string) => {
    setPage(0)
    setSort((prev) => {
      if (!prev || prev.key !== key) return { key, dir: 'desc' }
      return prev.dir === 'desc' ? { key, dir: 'asc' } : undefined
    })
  }

  const exportCsv = () => {
    const keys = block.columns.filter((col) => !off.has(col.key))
    downloadCsv(
      `${exportName}-${new Date().toISOString().slice(0, 10)}.csv`,
      keys.map((col) => col.label),
      view.map((row) => keys.map((col) => row[col.key])),
    )
  }

  const pickList = (key: string) => (contains: string): Promise<PickList> => {
    const others = active.filter((f) => f.column !== key)
    return Promise.resolve(valuesFromRows(others.length ? block.rows.filter((row) => passes(row, others)) : block.rows, key, contains))
  }

  if (!block.rows.length) {
    return (
      <div data-empty="true" className="px-3 py-3 text-xs text-[color:var(--color-text-faint)]">{emptyMessage}</div>
    )
  }

  const tone = (col: TableColumn, value: unknown): string => {
    if (negativeTone && col.format === 'money' && Number(value) < 0) return 'text-negative'
    return 'text-[color:var(--color-text-muted)]'
  }

  const first = columns[0]
  // The first money column gets a faint bar behind each figure, so the big ones read at a glance.
  const barKey = view.length >= 3 ? columns.find((col, index) => index > 0 && col.format === 'money')?.key : undefined
  const barMax = barKey ? Math.max(0, ...view.map((row) => Number(row[barKey]) || 0)) : 0
  const barStyle = (key: string, value: unknown) => {
    if (key !== barKey || !barMax) return undefined
    const share = Math.min(100, Math.max(0, ((Number(value) || 0) / barMax) * 100))
    if (share <= 0) return undefined
    const fill = 'color-mix(in srgb, var(--orion-accent) 13%, transparent)'
    return { backgroundImage: `linear-gradient(to left, ${fill} ${share}%, transparent ${share}%)` }
  }
  const from = view.length ? current * size + 1 : 0
  const to = Math.min(view.length, current * size + size)

  return (
    <div>
      <div className="flex flex-wrap items-center gap-2 px-3 pb-3">
        <label className="relative min-w-[12rem] flex-1 sm:max-w-xs">
          <span className="sr-only">{searchLabel}</span>
          <Search className="pointer-events-none absolute left-2.5 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-[color:var(--color-text-faint)]" />
          <input
            type="search"
            value={query}
            onChange={(event) => {
              setQuery(event.target.value)
              setPage(0)
            }}
            placeholder={searchLabel}
            className="w-full rounded-lg border border-[color:var(--color-border)] bg-surface py-1.5 pl-8 pr-2.5 text-xs text-[color:var(--color-text)] placeholder:text-[color:var(--color-text-faint)] focus:border-accent focus:ring-2 focus:ring-accent/20"
          />
        </label>

        <span className="text-[11px] text-[color:var(--color-text-faint)]" aria-live="polite">
          {searching ? `${view.length} of ${block.rows.length} rows` : `${block.rows.length} rows`}
          {block.truncated && ' (list is capped)'}
        </span>

        <div className="ml-auto flex items-center gap-1.5">
          {block.columns.length > 4 && (
            <div ref={columnsRoot} className="relative">
              <button
                type="button"
                aria-haspopup="true"
                aria-expanded={columnsOpen}
                onClick={() => setColumnsOpen((value) => !value)}
                className="flex items-center gap-1 rounded-lg border border-[color:var(--color-border)] px-2 py-1.5 text-xs text-[color:var(--color-text-muted)] hover:bg-muted"
              >
                <Columns3 className="h-3.5 w-3.5" aria-hidden="true" />
                Columns
                {off.size > 0 && <span className="rounded-full bg-accent-dim px-1.5 text-[10px] font-bold leading-4 text-accent">{block.columns.length - off.size}/{block.columns.length}</span>}
              </button>
              {columnsOpen && (
                <div role="group" aria-label="Columns to show" className="absolute right-0 z-20 mt-1 w-56 rounded-xl border border-[color:var(--color-border)] p-3 shadow-overlay" style={{ background: 'var(--orion-surface)' }}>
                  <div className="mb-2 flex items-center justify-between text-xs">
                    <span className="font-semibold text-[color:var(--color-text)]">Show these columns</span>
                    <span className="flex gap-3">
                      <button type="button" className="font-medium text-accent hover:underline" onClick={() => setOff(new Set())}>
                        All
                      </button>
                      <button type="button" className="font-medium text-accent hover:underline" onClick={() => setOff(new Set(block.columns.slice(1).map((col) => col.key)))}>
                        Only the first
                      </button>
                    </span>
                  </div>
                  <ul className="scroll-quiet max-h-64 space-y-1.5 overflow-y-auto">
                    {block.columns.map((col, index) => (
                      <li key={col.key} className={index === 0 ? 'opacity-60' : ''} title={index === 0 ? 'The first column is always shown' : undefined}>
                        <Checkbox
                          label={col.label}
                          checked={!off.has(col.key)}
                          onChange={(on) => {
                            if (index === 0) return
                            setOff((prev) => {
                              const next = new Set(prev)
                              if (on) next.delete(col.key)
                              else next.add(col.key)
                              return next
                            })
                          }}
                        />
                      </li>
                    ))}
                  </ul>
                </div>
              )}
            </div>
          )}
          <button
            type="button"
            onClick={exportCsv}
            title={block.truncated ? 'Exports the rows listed here; the list is capped' : 'Download these rows as CSV'}
            className="flex items-center gap-1 rounded-lg border border-[color:var(--color-border)] px-2 py-1.5 text-xs text-[color:var(--color-text-muted)] hover:bg-muted"
          >
            <Download className="h-3.5 w-3.5" aria-hidden="true" />
            Export
          </button>
        </div>
      </div>

      {active.length > 0 && (
        <div className="px-3 pb-3">
          <FilterChips
            filters={filters}
            labelOf={(key) => block.columns.find((col) => col.key === key)?.label ?? key}
            kindOf={kindOf}
            onRemove={(key) => setFilters((now) => setFilter(now, key, null))}
            onClear={() => setFilters([])}
          />
        </div>
      )}

      <div className="overflow-auto border-y border-[color:var(--color-border)]" style={{ maxHeight }}>
        <table className="w-full min-w-[560px] border-separate border-spacing-0 text-left text-sm">
          <thead>
            <tr>
              {columns.map((col) => {
                const sorted = sort?.key === col.key
                const Icon = !sorted ? ArrowUpDown : sort?.dir === 'asc' ? ArrowUp : ArrowDown
                return (
                  <th
                    key={col.key}
                    scope="col"
                    aria-sort={sorted ? (sort?.dir === 'asc' ? 'ascending' : 'descending') : 'none'}
                    className={`sticky top-0 z-10 border-b border-[color:var(--color-border)] bg-muted px-4 py-2 text-[11px] font-semibold uppercase tracking-wide text-[color:var(--color-text-muted)] ${
                      col.align === 'right' ? 'text-right' : ''
                    }`}
                  >
                    <span className={`inline-flex items-center gap-1 ${col.align === 'right' ? 'flex-row-reverse' : ''}`}>
                    <button
                      type="button"
                      onClick={() => toggleSort(col.key)}
                      className={`inline-flex items-center gap-1 uppercase tracking-wide hover:text-[color:var(--color-text)] ${
                        col.align === 'right' ? 'flex-row-reverse' : ''
                      }`}
                    >
                      {col.label}
                      <Icon className={`h-3 w-3 ${sorted ? 'text-accent' : 'opacity-40'}`} aria-hidden="true" />
                    </button>
                    <ColumnFilterMenu
                      column={col.key}
                      label={col.label}
                      kind={kindOf(col.key)}
                      filter={filters.find((f) => f.column === col.key)}
                      loadValues={textual(col.format) ? pickList(col.key) : undefined}
                      onChange={(next) => {
                        setPage(0)
                        setFilters((now) => setFilter(now, col.key, next))
                      }}
                    />
                    </span>
                  </th>
                )
              })}
            </tr>
          </thead>
          <tbody>
            {slice.length === 0 && (
              <tr>
                <td
                  colSpan={columns.length}
                  className="px-4 py-8 text-center text-sm text-[color:var(--color-text-faint)]"
                >
                  {query.trim() ? `No rows match “${query}”.` : 'No rows match these filters.'}
                </td>
              </tr>
            )}
            {slice.map((row, index) => {
              const code = String(row.code ?? `${current}-${index}`)
              const isSelected = clickable && selected === code
              const isDim = clickable && Boolean(selected) && !isSelected
              return (
                <tr
                  key={`${code}-${index}`}
                  onClick={clickable ? () => activate(code) : undefined}
                  className={`group ${clickable ? 'cursor-pointer' : ''} ${
                    isSelected ? 'bg-accent-dim/60' : clickable ? 'hover:bg-muted/70' : ''
                  } ${isDim ? 'opacity-50' : ''}`}
                >
                  {columns.map((col) => {
                    const value = row[col.key]
                    const lead = col.key === first.key
                    return (
                      <td
                        key={col.key}
                        style={barStyle(col.key, value)}
                        className={`border-b border-[color:var(--color-border)] px-4 py-2 ${
                          col.align === 'right' ? 'text-right tabular-nums' : ''
                        } ${lead ? 'font-medium text-[color:var(--color-text)]' : tone(col, value)}`}
                      >
                        {col.format === 'bill' && !isBlank(value) ? (
                          <BillNumber number={String(value)} code={typeof row.bill_code === 'string' ? row.bill_code : null} />
                        ) : lead && clickable ? (
                          <button
                            type="button"
                            aria-pressed={onOpen ? undefined : isSelected}
                            onClick={(event) => {
                              event.stopPropagation()
                              activate(code)
                            }}
                            title={String(value ?? '')}
                            className="max-w-[18rem] text-left leading-snug hover:text-accent focus-visible:underline"
                          >
                            {display(value, col.format, compact)}
                          </button>
                        ) : col.format === 'percent' && col.key === 'share' && !isBlank(value) ? (
                          <span className="inline-flex items-center justify-end gap-2">
                            <span className="hidden h-1.5 w-14 overflow-hidden rounded-full bg-muted sm:inline-block" aria-hidden="true">
                              <span
                                className="block h-full rounded-full bg-accent"
                                style={{ width: `${Math.min(100, Math.max(0, Number(value)))}%` }}
                              />
                            </span>
                            {display(value, col.format, compact)}
                          </span>
                        ) : (
                          <span title={textual(col.format) ? String(value ?? '') : undefined}>
                            {display(value, col.format, compact)}
                          </span>
                        )}
                      </td>
                    )
                  })}
                </tr>
              )
            })}
          </tbody>
          {totals && (
            <tfoot>
              <tr>
                {columns.map((col, index) => (
                  <td
                    key={col.key}
                    className={`sticky bottom-0 border-t border-[color:var(--color-border-strong)] bg-muted px-4 py-2 text-xs font-semibold text-[color:var(--color-text)] ${
                      col.align === 'right' ? 'text-right tabular-nums' : ''
                    }`}
                  >
                    {index === 0
                      ? searching
                        ? 'Subtotal (matching rows)'
                        : 'Total'
                      : col.key in totals
                        ? display(totals[col.key], col.format, compact)
                        : ''}
                  </td>
                ))}
              </tr>
            </tfoot>
          )}
        </table>
      </div>

      {view.length > PAGE_SIZES[0] && (
        <div className="flex flex-wrap items-center justify-between gap-2 px-3 pt-3 text-xs text-[color:var(--color-text-muted)]">
          <span className="tabular-nums" aria-live="polite">
            {from}–{to} of {view.length}
          </span>
          <div className="flex items-center gap-2">
            <label className="flex items-center gap-1.5">
              Rows
              <select
                value={size}
                onChange={(event) => {
                  setSize(Number(event.target.value))
                  setPage(0)
                }}
                className="rounded-md border border-[color:var(--color-border)] bg-surface px-1.5 py-1 text-xs"
              >
                {PAGE_SIZES.map((option) => (
                  <option key={option} value={option}>
                    {option}
                  </option>
                ))}
              </select>
            </label>
            <button
              type="button"
              onClick={() => setPage(current - 1)}
              disabled={current === 0}
              aria-label="Previous page"
              className="rounded-md border border-[color:var(--color-border)] p-1 hover:bg-muted disabled:opacity-40"
            >
              <ChevronLeft className="h-4 w-4" />
            </button>
            <button
              type="button"
              onClick={() => setPage(current + 1)}
              disabled={current >= pages - 1}
              aria-label="Next page"
              className="rounded-md border border-[color:var(--color-border)] p-1 hover:bg-muted disabled:opacity-40"
            >
              <ChevronRight className="h-4 w-4" />
            </button>
          </div>
        </div>
      )}
    </div>
  )
}
