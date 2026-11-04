import { useContext, useEffect, useState } from 'react'
import { ChevronRight, Download, RefreshCw, Search } from 'lucide-react'
import { DataTable } from './ui/DataTable'
import { encodeFilters, setFilter, type ColumnFilter, type FilterKind, type PickList } from '../tables/columnFilter'
import { WorkbenchCollapseContext } from './data/WorkbenchChrome'
import type { PreviewQuery } from '../api/client'

export type PreviewLimit = 3 | 10 | 50
export type ExportLimit = 100 | 'all'

export type PreviewPayload = {
  columns: string[]
  rows: Record<string, unknown>[]
  total: number
  matched?: number
  kinds?: Record<string, FilterKind>
}

const INLINE: { value: PreviewLimit; label: string }[] = [
  { value: 3, label: '3' },
  { value: 10, label: '10' },
  { value: 50, label: '50' },
]

const DOWNLOADS: { value: ExportLimit; label: string }[] = [
  { value: 100, label: '100' },
  { value: 'all', label: 'All' },
]

/**
 * Latest-N preview with full-table search and sort. 3 / 10 / 50 stay on the page.
 * 100 and All download Excel of the current filter, not just the visible rows.
 */
export function PreviewRecords({
  title,
  emptyMessage,
  load,
  download,
  values,
  reloadToken = 0,
  fill = false,
  onRowClick,
  rowHint,
  allColumns = false,
}: {
  title: string
  emptyMessage?: string
  load: (limit: PreviewLimit, query: PreviewQuery) => Promise<PreviewPayload>
  download: (limit: ExportLimit, query: PreviewQuery) => Promise<void>
  /** The values a column holds, for the pick list in its filter; without it the headers offer conditions only. */
  values?: (column: string, query: PreviewQuery, contains: string) => Promise<PickList>
  /** Bump after a write so the current page size reloads without resetting it. */
  reloadToken?: number
  fill?: boolean
  /** Opens the record a row shows. Rows become clickable when this is set. */
  onRowClick?: (row: Record<string, unknown>) => void
  rowHint?: string
  /** Show every column the server sends, audit timestamps included (the warehouse pages). */
  allColumns?: boolean
}) {
  const [limit, setLimit] = useState<PreviewLimit>(fill ? 10 : 3)
  const [q, setQ] = useState('')
  const [qDebounced, setQDebounced] = useState('')
  const [sort, setSort] = useState('')
  const [filters, setFilters] = useState<ColumnFilter[]>([])
  const [dir, setDir] = useState<'asc' | 'desc'>('desc')
  const [preview, setPreview] = useState<PreviewPayload | null>(null)
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(true)
  const [exporting, setExporting] = useState<ExportLimit | null>(null)
  const [note, setNote] = useState('')
  const collapsePreview = useContext(WorkbenchCollapseContext).collapsePreview

  useEffect(() => {
    const timer = window.setTimeout(() => setQDebounced(q.trim()), 350)
    return () => window.clearTimeout(timer)
  }, [q])

  const query: PreviewQuery = {
    q: qDebounced || undefined,
    sort: sort || undefined,
    dir: sort ? dir : undefined,
    f: encodeFilters(filters),
  }

  const refresh = (size: PreviewLimit) => {
    setBusy(true)
    setError('')
    load(size, query)
      .then(setPreview)
      .catch((e: Error) => setError(e.message))
      .finally(() => setBusy(false))
  }

  useEffect(() => {
    refresh(limit)
    // load is recreated when the dataset changes; the parent remounts via key.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [limit, reloadToken, qDebounced, sort, dir, filters])

  const cycleSort = (column: string) => {
    if (sort !== column) {
      setSort(column)
      setDir('asc')
      return
    }
    if (dir === 'asc') {
      setDir('desc')
      return
    }
    setSort('')
    setDir('desc')
  }

  const exportRows = async (size: ExportLimit) => {
    setError('')
    setNote('')
    setExporting(size)
    try {
      await download(size, query)
      const filtered = Boolean(qDebounced || sort || filters.length)
      setNote(
        size === 'all'
          ? filtered
            ? 'Downloaded every matching record as Excel.'
            : 'Downloaded every record as Excel.'
          : filtered
            ? 'Downloaded up to 100 matching records as Excel.'
            : 'Downloaded the latest 100 records as Excel.',
      )
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Download failed')
    } finally {
      setExporting(null)
    }
  }

  const shown = preview?.rows.length ?? 0
  const total = preview?.total ?? 0
  const matched = preview?.matched ?? total
  const searching = Boolean(qDebounced)

  const summary = (() => {
    if (!preview) return 'Latest records'
    if (searching) {
      return `Showing ${shown} of ${matched.toLocaleString()} matching “${qDebounced}” (${total.toLocaleString()} total)`
    }
    return total ? `Showing ${shown} of ${total.toLocaleString()} records` : 'Latest records'
  })()

  return (
    <div className={fill ? 'flex h-full min-h-0 w-full flex-col' : ''}>
      <div className="mb-3 flex flex-wrap items-start justify-between gap-3">
        <div>
          <h3 className="t-h3 text-[color:var(--color-text)]">{title}</h3>
          <p className="mt-0.5 text-xs text-[color:var(--color-text-muted)]">{summary}</p>
        </div>
        <div className="flex items-center gap-1">
          <button
            type="button"
            onClick={() => refresh(limit)}
            className="data-hot rounded-md p-2 text-[color:var(--color-text-faint)] hover:bg-muted hover:text-[color:var(--color-text)]"
            aria-label="Refresh preview"
          >
            <RefreshCw className={`h-4 w-4 ${busy ? 'animate-spin' : ''}`} />
          </button>
          {collapsePreview ? (
            <button
              type="button"
              onClick={collapsePreview}
              className="data-hot rounded-md p-2 text-[color:var(--color-text-faint)] hover:bg-muted hover:text-[color:var(--color-text)]"
              aria-label="Collapse records"
              title="Collapse records"
            >
              <ChevronRight className="h-4 w-4" />
            </button>
          ) : null}
        </div>
      </div>

      <div className="mb-3 flex flex-wrap items-center gap-x-4 gap-y-2">
        <label className="relative min-w-[12rem] flex-1">
          <Search className="pointer-events-none absolute left-2.5 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-[color:var(--color-text-faint)]" />
          <input
            type="search"
            value={q}
            onChange={(e) => setQ(e.target.value)}
            placeholder="Search all columns"
            className="w-full rounded-lg border border-[color:var(--color-border)] bg-surface py-1.5 pl-8 pr-3 text-sm text-[color:var(--color-text)] placeholder:text-[color:var(--color-text-faint)] focus:border-accent focus:ring-[3px] focus:ring-[color:var(--orion-ring)] focus:outline-none"
          />
        </label>
        <div className="flex items-center gap-1.5">
          <span className="text-[11px] font-medium uppercase tracking-wide text-[color:var(--color-text-faint)]">Show</span>
          <div className="flex rounded-lg border border-[color:var(--color-border)] bg-muted p-0.5">
            {INLINE.map((option) => (
              <button
                key={option.value}
                type="button"
                onClick={() => setLimit(option.value)}
                className={`data-hot rounded-md px-2.5 py-1 text-xs font-medium ${
                  limit === option.value
                    ? 'bg-surface text-[color:var(--color-text)] shadow-sm'
                    : 'text-[color:var(--color-text-muted)] hover:bg-surface hover:text-[color:var(--color-text)]'
                }`}
              >
                {option.label}
              </button>
            ))}
          </div>
        </div>
        <div className="flex items-center gap-1.5">
          <span className="text-[11px] font-medium uppercase tracking-wide text-[color:var(--color-text-faint)]">
            Excel
          </span>
          <div className="flex rounded-lg border border-[color:var(--color-border)] bg-muted p-0.5">
            {DOWNLOADS.map((option) => (
              <button
                key={option.value}
                type="button"
                disabled={exporting !== null}
                onClick={() => exportRows(option.value)}
                className="data-hot flex items-center gap-1 rounded-md px-2.5 py-1 text-xs font-medium text-[color:var(--color-text-muted)] hover:bg-surface hover:text-[color:var(--color-text)] disabled:opacity-50"
              >
                <Download className="h-3 w-3" />
                {exporting === option.value ? '…' : option.label}
              </button>
            ))}
          </div>
        </div>
      </div>

      {error && <p className="mb-2 text-xs text-negative">{error}</p>}
      {note && <p className="mb-2 text-xs text-accent">{note}</p>}

      {busy && !preview && (
        <div className={`flex items-center justify-center text-sm text-[color:var(--color-text-muted)] ${fill ? 'min-h-0 flex-1' : 'py-10'}`}>
          Loading records…
        </div>
      )}

      {preview && (
        <div className={fill ? 'min-h-0 w-full flex-1' : ''}>
          <DataTable
            columns={preview.columns}
            rows={preview.rows}
            compact
            fill={fill}
            maxHeight={fill ? undefined : limit > 3 ? '16rem' : undefined}
            emptyMessage={searching ? `No rows match “${qDebounced}”.` : emptyMessage}
            sort={sort}
            dir={dir}
            onSort={cycleSort}
            hot
            onRowClick={onRowClick}
            rowHint={rowHint}
            allColumns={allColumns}
            filters={filters}
            onFilter={(column, next) => setFilters((now) => setFilter(now, column, next))}
            kinds={preview.kinds}
            loadValues={values ? (column, contains) => values(column, { q: qDebounced || undefined, f: encodeFilters(filters) }, contains) : undefined}
          />
        </div>
      )}
    </div>
  )
}
