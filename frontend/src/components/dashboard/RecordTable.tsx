import { useCallback, useEffect, useRef, useState } from 'react'
import { TabLink } from '../ui/TabLink'
import { ArrowDown, ArrowUp, ChevronLeft, ChevronRight, Download, ExternalLink, Search } from 'lucide-react'
import type { CellFormat, RecordPage } from '../../types'
import { encodeFilters, setFilter, type ColumnFilter, type FilterKind } from '../../tables/columnFilter'
import { ColumnFilterMenu, FilterChips } from '../../tables/ColumnFilterMenu'
import { BillNumber } from '../billing/BillNumber'
import { downloadCsv } from './csv'
import { count, inrFull } from './format'

export type RecordQuery = { q?: string; f?: string; sort?: string; dir?: 'asc' | 'desc'; page?: number; size?: number; export?: boolean }

function show(value: unknown, format: CellFormat): string {
  if (value === null || value === undefined || value === '') return '—'
  if (format === 'money') return inrFull(Number(value))
  if (format === 'number') return count(Number(value))
  if (format === 'percent') return `${Number(value).toFixed(1)}%`
  return String(value)
}

const PAGE_SIZE = 25

/**
 * The rows behind a figure: sorted, searched and paged on the server, so a set of thousands stays quick, with a total row
 * over everything that matches and an export of all of it. `load` fetches a page; `resetKey` changes when the set or its
 * filters do, which starts again from the top.
 */
export function RecordTable({
  load,
  resetKey,
  fileName,
  onData,
}: {
  load: (query: RecordQuery) => Promise<RecordPage>
  resetKey: string
  fileName: string
  onData?: (page: RecordPage | null) => void
}) {
  const [data, setData] = useState<RecordPage | null>(null)
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  const [query, setQuery] = useState('')
  const [needle, setNeedle] = useState('')
  const [sort, setSort] = useState<{ key?: string; dir?: 'asc' | 'desc' }>({})
  const [filters, setFilters] = useState<ColumnFilter[]>([])
  const encoded = encodeFilters(filters)
  const [page, setPage] = useState(1)
  const request = useRef(0)
  const loader = useRef(load)
  loader.current = load

  useEffect(() => {
    setQuery('')
    setNeedle('')
    setSort({})
    setFilters([])
    setPage(1)
    setData(null)
    setError('')
    onData?.(null)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [resetKey])

  useEffect(() => {
    const timer = window.setTimeout(() => {
      setNeedle(query)
      setPage(1)
    }, 300)
    return () => window.clearTimeout(timer)
  }, [query])

  useEffect(() => {
    const id = ++request.current
    setBusy(true)
    loader
      .current({ q: needle, f: encoded, sort: sort.key, dir: sort.dir, page, size: PAGE_SIZE })
      .then((result) => {
        if (id !== request.current) return
        setData(result)
        setError('')
        onData?.(result)
      })
      .catch((e: Error) => id === request.current && setError(e.message))
      .finally(() => id === request.current && setBusy(false))
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [resetKey, needle, sort.key, sort.dir, page, encoded])

  const toggleSort = useCallback(
    (key: string) => {
      setPage(1)
      setSort((current) => {
        const active = current.key ?? data?.sort.key
        const dir = current.dir ?? data?.sort.dir
        if (active === key) return { key, dir: dir === 'asc' ? 'desc' : 'asc' }
        return { key, dir: 'desc' }
      })
    },
    [data],
  )

  const exportAll = async () => {
    if (!data) return
    try {
      const all = await loader.current({ q: needle, f: encoded, sort: sort.key, dir: sort.dir, export: true })
      downloadCsv(
        `${fileName}-${new Date().toISOString().slice(0, 10)}.csv`,
        all.columns.map((c) => c.label),
        all.rows.map((row) => all.columns.map((c) => (row[c.key] ?? '') as string | number)),
      )
    } catch (e) {
      setError((e as Error).message)
    }
  }

  const pages = data ? Math.max(1, Math.ceil(data.total / data.size)) : 1
  const canFilter = data?.filterable !== false
  // Money, counts and percentages are numbers; the rest is text (a date is read as its text, "2026-04" finds April).
  const kindOf = (key: string): FilterKind => (data && ['money', 'number', 'percent'].includes(data.columns.find((c) => c.key === key)?.format ?? '') ? 'number' : 'text')
  const labelOf = (key: string) => data?.columns.find((c) => c.key === key)?.label ?? key
  const change = (key: string, next: ColumnFilter | null) => {
    setPage(1)
    setFilters((now) => setFilter(now, key, next))
  }
  const activeSort = data?.sort
  const rowLink = (row: Record<string, string | number | null>) =>
    data?.link && row._id ? data.link.replace('{id}', encodeURIComponent(String(row._id))) : null

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center gap-2">
        <label className="relative min-w-[12rem] flex-1">
          <span className="sr-only">Search these records</span>
          <Search className="pointer-events-none absolute left-2.5 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-[color:var(--color-text-faint)]" />
          <input
            type="search"
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            placeholder="Search names, cases, bills…"
            className="h-9 w-full rounded-lg border border-[color:var(--color-border-strong)] bg-surface pl-8 pr-3 text-sm text-[color:var(--color-text)] outline-none focus:border-[color:var(--color-accent)]"
          />
        </label>
        <button
          type="button"
          onClick={() => void exportAll()}
          disabled={!data || data.total === 0}
          className="flex h-9 items-center gap-1.5 rounded-lg border border-[color:var(--color-border-strong)] bg-surface px-3 text-xs font-medium text-[color:var(--color-text)] hover:bg-muted disabled:opacity-50"
        >
          <Download className="h-3.5 w-3.5" aria-hidden="true" />
          Export CSV
        </button>
      </div>

      {canFilter && filters.length > 0 && (
        <FilterChips filters={filters} labelOf={labelOf} kindOf={kindOf} onRemove={(key) => change(key, null)} onClear={() => (setFilters([]), setPage(1))} />
      )}

      {error && (
        <p role="alert" className="rounded-lg border border-negative/30 bg-negative-dim px-3 py-2 text-sm text-[color:var(--color-text)]">
          {error}
        </p>
      )}

      <div className={`overflow-x-auto rounded-xl border border-[color:var(--color-border)] bg-surface transition-opacity ${busy ? 'opacity-60' : ''}`}>
        {!data && !error ? (
          <div className="shimmer m-3 h-64 rounded-lg bg-muted" aria-busy="true" />
        ) : data && data.rows.length === 0 && !filters.length ? (
          <p className="px-6 py-12 text-center text-sm text-[color:var(--color-text-muted)]">Nothing matches these filters.</p>
        ) : (
          data && (
            <table className="w-full text-sm">
              <thead className="sticky top-0 bg-surface">
                <tr className="border-b border-[color:var(--color-border)] text-left text-xs text-[color:var(--color-text-muted)]">
                  {data.columns.map((col) => {
                    const isSorted = activeSort?.key === col.key
                    return (
                      <th
                        key={col.key}
                        scope="col"
                        aria-sort={isSorted ? (activeSort?.dir === 'asc' ? 'ascending' : 'descending') : 'none'}
                        className={`whitespace-nowrap px-3 py-2 font-medium ${col.align === 'right' ? 'text-right' : ''}`}
                      >
                        <span className={`inline-flex items-center gap-1 ${col.align === 'right' ? 'flex-row-reverse' : ''}`}>
                        <button
                          type="button"
                          onClick={() => toggleSort(col.key)}
                          className={`inline-flex items-center gap-1 hover:text-[color:var(--color-text)] ${col.align === 'right' ? 'flex-row-reverse' : ''}`}
                        >
                          {col.label}
                          {isSorted && (activeSort?.dir === 'asc' ? <ArrowUp className="h-3 w-3" /> : <ArrowDown className="h-3 w-3" />)}
                        </button>
                        {canFilter && (
                          <ColumnFilterMenu column={col.key} label={col.label} kind={kindOf(col.key)} filter={filters.find((f) => f.column === col.key)} onChange={(next) => change(col.key, next)} />
                        )}
                        </span>
                      </th>
                    )
                  })}
                  {data.link && <th className="w-8" />}
                </tr>
              </thead>
              <tbody>
                {data.rows.length === 0 && (
                  <tr>
                    <td colSpan={data.columns.length + (data.link ? 1 : 0)} className="px-6 py-10 text-center text-sm text-[color:var(--color-text-muted)]">
                      No record matches these column filters.
                    </td>
                  </tr>
                )}
                {data.rows.map((row, index) => {
                  const link = rowLink(row)
                  return (
                    <tr key={String(row._id ?? index)} className="border-t border-[color:var(--color-border)] hover:bg-muted/50">
                      {data.columns.map((col) => (
                        <td key={col.key} className={`px-3 py-2 text-[color:var(--color-text)] ${col.align === 'right' ? 'text-right tabular-nums' : ''}`}>
                          {col.format === 'bill' && row[col.key] ? <BillNumber number={String(row[col.key])} /> : show(row[col.key], col.format)}
                        </td>
                      ))}
                      {data.link && (
                        <td className="pr-3 text-right">
                          {link && (
                            <TabLink to={link} aria-label="Open this record (in a new tab)" className="text-[color:var(--color-text-faint)] hover:text-accent">
                              <ExternalLink className="h-3.5 w-3.5" />
                            </TabLink>
                          )}
                        </td>
                      )}
                    </tr>
                  )
                })}
              </tbody>
              {Object.keys(data.totals).length > 0 && (
                <tfoot>
                  <tr className="border-t-2 border-[color:var(--color-border-strong)] bg-muted/60 font-semibold">
                    {data.columns.map((col, index) => (
                      <td key={col.key} className={`px-3 py-2 ${col.align === 'right' ? 'text-right tabular-nums' : ''}`}>
                        {index === 0 && !(col.key in data.totals) ? 'Total, all matching' : col.key in data.totals ? show(data.totals[col.key], col.format) : ''}
                      </td>
                    ))}
                    {data.link && <td />}
                  </tr>
                </tfoot>
              )}
            </table>
          )
        )}
      </div>

      {data && data.total > data.size && (
        <div className="flex items-center justify-between gap-2 text-xs text-[color:var(--color-text-muted)]">
          <span>
            {(data.page - 1) * data.size + 1}–{Math.min(data.page * data.size, data.total)} of {count(data.total)}
          </span>
          <div className="flex items-center gap-1">
            <button
              type="button"
              onClick={() => setPage((p) => Math.max(1, p - 1))}
              disabled={page <= 1}
              aria-label="Previous page"
              className="rounded-lg border border-[color:var(--color-border-strong)] p-1.5 hover:bg-muted disabled:opacity-40"
            >
              <ChevronLeft className="h-4 w-4" />
            </button>
            <span className="px-2 tabular-nums">
              Page {page} of {pages}
            </span>
            <button
              type="button"
              onClick={() => setPage((p) => Math.min(pages, p + 1))}
              disabled={page >= pages}
              aria-label="Next page"
              className="rounded-lg border border-[color:var(--color-border-strong)] p-1.5 hover:bg-muted disabled:opacity-40"
            >
              <ChevronRight className="h-4 w-4" />
            </button>
          </div>
        </div>
      )}
      {data?.truncated && <p className="text-xs text-warning">The export holds the first 20,000 rows. Narrow the filters to get the rest.</p>}
    </div>
  )
}
