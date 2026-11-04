import { useMemo, useState } from 'react'
import { ArrowDown, ArrowUp, ChevronLeft, ChevronRight, ClipboardCopy, Download, Search } from 'lucide-react'
import type { SqlResultSet } from '../../types'
import { isComplete, matchesFilter, setFilter, valuesFromRows, type ColumnFilter, type FilterKind, type PickList } from '../../tables/columnFilter'
import { ColumnFilterMenu, FilterChips } from '../../tables/ColumnFilterMenu'
import { downloadCsv } from '../dashboard/csv'
import { Button } from '../ui/Button'
import { Modal } from '../ui/Modal'

type Cell = string | number | boolean | null

const PAGE = 100

/** What a column holds, from its database type, so its filter offers the right conditions. */
function kindOfType(type: string): FilterKind {
  if (/^(smallint|integer|bigint|numeric|decimal|real|double precision|money|oid)/.test(type)) return 'number'
  if (/^(date|timestamp)/.test(type)) return 'date'
  if (type === 'boolean') return 'bool'
  return 'text'
}

const shown = (value: Cell): string => (value === null ? '' : String(value))

function compare(a: Cell, b: Cell, kind: FilterKind): number {
  if (a === null && b === null) return 0
  if (a === null) return 1
  if (b === null) return -1
  if (kind === 'number') return Number(a) - Number(b)
  return String(a).localeCompare(String(b), undefined, { numeric: true, sensitivity: 'base' })
}

const toTsv = (columns: string[], rows: Cell[][]) => [columns.join('\t'), ...rows.map((row) => row.map((v) => shown(v).replace(/[\t\n\r]+/g, ' ')).join('\t'))].join('\n')

/**
 * The rows a statement returned: sorted and filtered in the page (a funnel in each header, as on every table), searched, paged, copied (a cell, a row,
 * everything) and downloaded. A row opens in a panel of its own, which is how a row of many columns is read. The answer to EXPLAIN is shown as the plan.
 */
export function SqlResultGrid({ result, onExportAll }: { result: SqlResultSet; onExportAll?: () => void }) {
  const columns = useMemo(() => result.columns ?? [], [result.columns])
  const all = useMemo(() => (result.rows ?? []) as Cell[][], [result.rows])
  const [sort, setSort] = useState<{ index: number; dir: 'asc' | 'desc' } | null>(null)
  const [filters, setFilters] = useState<ColumnFilter[]>([])
  const [query, setQuery] = useState('')
  const [page, setPage] = useState(0)
  const [picked, setPicked] = useState<{ row: number; col: number } | null>(null)
  const [record, setRecord] = useState<number | null>(null)
  const [copied, setCopied] = useState('')

  const kinds = useMemo(() => columns.map((c) => kindOfType(c.type)), [columns])
  const active = filters.filter(isComplete)
  const indexOf = (name: string) => columns.findIndex((c) => c.name === name)

  const view = useMemo(() => {
    let rows = all.map((cells, id) => ({ cells, id }))
    const needle = query.trim().toLowerCase()
    if (needle) rows = rows.filter(({ cells }) => cells.some((v) => shown(v).toLowerCase().includes(needle)))
    for (const f of active) {
      const at = indexOf(f.column)
      if (at >= 0) rows = rows.filter(({ cells }) => matchesFilter(f, cells[at], shown(cells[at]), kinds[at]))
    }
    if (sort) {
      const sign = sort.dir === 'asc' ? 1 : -1
      rows = [...rows].sort((a, b) => sign * compare(a.cells[sort.index], b.cells[sort.index], kinds[sort.index]))
    }
    return rows
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [all, query, filters, sort, kinds, columns])

  const pages = Math.max(1, Math.ceil(view.length / PAGE))
  const current = Math.min(page, pages - 1)
  const slice = view.slice(current * PAGE, current * PAGE + PAGE)
  const names = columns.map((c) => c.name)

  const copy = async (text: string, what: string) => {
    try {
      await navigator.clipboard.writeText(text)
      setCopied(what)
      window.setTimeout(() => setCopied(''), 1500)
    } catch {
      setCopied('Copy was blocked by the browser')
    }
  }

  const pickList = (index: number) => (contains: string): Promise<PickList> => {
    const others = active.filter((f) => f.column !== columns[index].name)
    const rows = all
      .filter((cells) => others.every((f) => matchesFilter(f, cells[indexOf(f.column)], shown(cells[indexOf(f.column)]), kinds[indexOf(f.column)])))
      .map((cells) => ({ v: cells[index] }))
    return Promise.resolve(valuesFromRows(rows, 'v', contains))
  }

  // EXPLAIN: one column of text lines, which read as a plan, not as a table.
  if (columns.length === 1 && columns[0].name === 'QUERY PLAN') {
    const text = all.map((row) => shown(row[0])).join('\n')
    return (
      <div className="relative h-full overflow-auto p-3">
        <Button variant="secondary" size="sm" className="absolute right-4 top-3" onClick={() => void copy(text, 'Plan copied')}>
          <ClipboardCopy className="h-4 w-4" /> {copied || 'Copy plan'}
        </Button>
        <pre className="whitespace-pre-wrap font-mono text-xs leading-relaxed text-[color:var(--color-text)]">{text}</pre>
      </div>
    )
  }

  return (
    <div className="flex h-full min-h-0 flex-col">
      <div className="flex flex-wrap items-center gap-2 border-b border-[color:var(--color-border)] px-3 py-1.5">
        <label className="relative min-w-[10rem] max-w-xs flex-1">
          <span className="sr-only">Search these rows</span>
          <Search className="pointer-events-none absolute left-2.5 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-[color:var(--color-text-faint)]" />
          <input
            type="search"
            value={query}
            onChange={(event) => {
              setQuery(event.target.value)
              setPage(0)
            }}
            placeholder="Search these rows"
            className="w-full rounded-lg border border-[color:var(--color-border)] bg-surface py-1 pl-8 pr-2 text-xs text-[color:var(--color-text)] placeholder:text-[color:var(--color-text-faint)] focus:border-accent"
          />
        </label>
        <span className="text-[11px] text-[color:var(--color-text-muted)]" aria-live="polite">
          {view.length === all.length ? `${all.length.toLocaleString('en-IN')} rows` : `${view.length.toLocaleString('en-IN')} of ${all.length.toLocaleString('en-IN')} rows`}
          {result.truncated ? ' (the limit was reached: there are more)' : ''}
        </span>
        <div className="ml-auto flex items-center gap-1">
          <Button variant="ghost" size="sm" onClick={() => void copy(toTsv(names, view.map((r) => r.cells)), 'Copied')} title="Copy the rows shown, to paste into a spreadsheet">
            <ClipboardCopy className="h-4 w-4" /> {copied || 'Copy'}
          </Button>
          <Button variant="ghost" size="sm" onClick={() => downloadCsv(`query-${new Date().toISOString().slice(0, 10)}.csv`, names, view.map((r) => r.cells.map((v) => v ?? '') as (string | number)[]))} title="Download the rows shown as CSV">
            <Download className="h-4 w-4" /> CSV
          </Button>
          {onExportAll && result.truncated && (
            <Button variant="ghost" size="sm" onClick={onExportAll} title="Run the query again and download up to 100,000 rows">
              <Download className="h-4 w-4" /> All rows
            </Button>
          )}
        </div>
      </div>
      {active.length > 0 && (
        <div className="border-b border-[color:var(--color-border)] px-3 py-1.5">
          <FilterChips
            filters={filters}
            labelOf={(c) => c}
            kindOf={(c) => kinds[indexOf(c)] ?? 'text'}
            onRemove={(c) => setFilters((now) => setFilter(now, c, null))}
            onClear={() => setFilters([])}
          />
        </div>
      )}
      <div className="min-h-0 flex-1 overflow-auto">
        <table className="w-max min-w-full border-separate border-spacing-0 text-left text-xs">
          <thead>
            <tr>
              <th className="sticky left-0 top-0 z-20 border-b border-r border-[color:var(--color-border)] bg-muted px-2 py-1.5 text-right font-normal text-[color:var(--color-text-faint)]">#</th>
              {columns.map((col, index) => {
                const sorted = sort?.index === index
                return (
                  <th key={`${col.name}-${index}`} className="sticky top-0 z-10 border-b border-[color:var(--color-border)] bg-muted px-3 py-1.5 font-semibold text-[color:var(--color-text)]" aria-sort={sorted ? (sort?.dir === 'asc' ? 'ascending' : 'descending') : 'none'}>
                    <span className="inline-flex items-center gap-1">
                      <button type="button" className="inline-flex items-center gap-1 hover:text-accent" onClick={() => setSort((s) => (s?.index === index ? (s.dir === 'asc' ? { index, dir: 'desc' } : null) : { index, dir: 'asc' }))}>
                        {col.name}
                        {sorted && (sort?.dir === 'asc' ? <ArrowUp className="h-3 w-3" /> : <ArrowDown className="h-3 w-3" />)}
                      </button>
                      <ColumnFilterMenu
                        column={col.name}
                        label={col.name}
                        kind={kinds[index]}
                        filter={filters.find((f) => f.column === col.name)}
                        loadValues={kinds[index] === 'number' ? undefined : pickList(index)}
                        onChange={(next) => {
                          setPage(0)
                          setFilters((now) => setFilter(now, col.name, next))
                        }}
                      />
                    </span>
                    <span className="block text-[10px] font-normal text-[color:var(--color-text-faint)]">{col.type}</span>
                  </th>
                )
              })}
            </tr>
          </thead>
          <tbody>
            {slice.length === 0 && (
              <tr>
                <td colSpan={columns.length + 1} className="px-4 py-8 text-center text-[color:var(--color-text-muted)]">
                  {all.length === 0 ? 'The query returned no rows.' : 'No row matches.'}
                </td>
              </tr>
            )}
            {slice.map(({ cells, id }, rowIndex) => (
              <tr key={id} className="hover:bg-muted/60" onDoubleClick={() => setRecord(id)}>
                <td className="sticky left-0 z-[1] border-b border-r border-[color:var(--color-border)] bg-surface px-2 py-1 text-right tabular-nums text-[color:var(--color-text-faint)]">{current * PAGE + rowIndex + 1}</td>
                {cells.map((value, colIndex) => {
                  const kind = kinds[colIndex]
                  const isPicked = picked?.row === id && picked.col === colIndex
                  const text = shown(value)
                  const looksJson = typeof value === 'string' && /^[[{]/.test(value)
                  return (
                    <td
                      key={colIndex}
                      onClick={() => setPicked({ row: id, col: colIndex })}
                      onKeyDown={(event) => {
                        if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === 'c') void copy(text, 'Copied')
                      }}
                      tabIndex={isPicked ? 0 : -1}
                      title={text.length > 40 ? text : undefined}
                      className={`max-w-[28rem] truncate border-b border-[color:var(--color-border)] px-3 py-1 ${kind === 'number' ? 'text-right tabular-nums' : ''} ${looksJson ? 'font-mono' : ''} ${isPicked ? 'bg-accent-dim outline outline-1 outline-accent' : ''}`}
                    >
                      {value === null ? <span className="italic text-[color:var(--color-text-faint)]">NULL</span> : kind === 'bool' ? String(value) : text}
                    </td>
                  )
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {pages > 1 && (
        <div className="flex items-center justify-between gap-2 border-t border-[color:var(--color-border)] px-3 py-1 text-xs text-[color:var(--color-text-muted)]">
          <span>
            {(current * PAGE + 1).toLocaleString('en-IN')}–{Math.min(view.length, current * PAGE + PAGE).toLocaleString('en-IN')} of {view.length.toLocaleString('en-IN')}
          </span>
          <div className="flex items-center gap-1">
            <Button variant="ghost" size="sm" disabled={current === 0} onClick={() => setPage(current - 1)} aria-label="Previous page">
              <ChevronLeft className="h-4 w-4" />
            </Button>
            <span className="tabular-nums">
              {current + 1} / {pages}
            </span>
            <Button variant="ghost" size="sm" disabled={current >= pages - 1} onClick={() => setPage(current + 1)} aria-label="Next page">
              <ChevronRight className="h-4 w-4" />
            </Button>
          </div>
        </div>
      )}
      <Modal open={record !== null} title={record === null ? '' : `Row ${record + 1}`} size="xl" onClose={() => setRecord(null)}>
        {record !== null && (
          <dl className="grid gap-x-6 gap-y-2 text-sm sm:grid-cols-[minmax(8rem,14rem)_1fr]">
            {columns.map((col, index) => (
              <div key={`${col.name}-${index}`} className="contents">
                <dt className="font-medium text-[color:var(--color-text-muted)]">
                  {col.name} <span className="text-[10px] font-normal text-[color:var(--color-text-faint)]">{col.type}</span>
                </dt>
                <dd className="break-words font-mono text-xs text-[color:var(--color-text)]">{all[record][index] === null ? <em className="text-[color:var(--color-text-faint)]">NULL</em> : String(all[record][index])}</dd>
              </div>
            ))}
          </dl>
        )}
      </Modal>
    </div>
  )
}
