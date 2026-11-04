import { useMemo, useState } from 'react'
import { ArrowDown, ArrowUp, ArrowUpDown } from 'lucide-react'
import { billColumn } from '../../billing/billLink'
import {
  isComplete,
  kindFromRows,
  matchesFilter,
  setFilter,
  valuesFromRows,
  type ColumnFilter,
  type FilterKind,
  type PickList,
} from '../../tables/columnFilter'
import { ColumnFilterMenu, FilterChips } from '../../tables/ColumnFilterMenu'
import { BillNumber } from '../billing/BillNumber'
import { LumenCell, figureColumns, pillColumns } from '../../lumen/cells'
import { useLumen } from '../../lumen/useLumen'

export function DataTable({
  columns,
  rows: allRows,
  emptyMessage = 'No records yet.',
  compact = false,
  maxHeight,
  fill = false,
  sort,
  dir,
  onSort,
  hot = false,
  onRowClick,
  rowHint,
  allColumns = false,
  filterable = false,
  filters: serverFilters,
  onFilter,
  kinds,
  loadValues,
}: {
  columns: string[]
  rows: Record<string, unknown>[]
  emptyMessage?: string
  compact?: boolean
  maxHeight?: string
  fill?: boolean
  sort?: string
  dir?: 'asc' | 'desc'
  onSort?: (column: string) => void
  hot?: boolean
  /** Makes each row a button, for opening the record it shows. */
  onRowClick?: (row: Record<string, unknown>) => void
  /** What clicking a row does, shown as its tooltip. */
  rowHint?: string
  /** Show every column. Without it the audit columns (timestamps, who created and changed) are left out. */
  allColumns?: boolean
  /** A filter on every column's header, applied to the rows in the page. */
  filterable?: boolean
  /** The filters on, when the rows are filtered elsewhere (on the server): with `onFilter`, the headers offer filters and report them. */
  filters?: ColumnFilter[]
  onFilter?: (column: string, next: ColumnFilter | null) => void
  /** What each column holds, when it is known (the server says); otherwise it is worked out from the rows. */
  kinds?: Record<string, FilterKind>
  /** The values of a column to pick from, when the rows in the page are not all of them. */
  loadValues?: (column: string, contains: string) => Promise<PickList>
}) {
  const lumen = useLumen()
  const [ownFilters, setOwnFilters] = useState<ColumnFilter[]>([])
  const remote = Boolean(onFilter)
  const filtering = remote || filterable
  const filters = remote ? (serverFilters ?? []) : ownFilters
  const change = (column: string, next: ColumnFilter | null) => (remote ? onFilter?.(column, next) : setOwnFilters((now) => setFilter(now, column, next)))
  const displayCols = allColumns
    ? columns
    : columns.filter((c) => (!c.includes('timestamp') && c !== 'created_by' && c !== 'last_updated_by') || c === 'record_status')
  const cell = compact ? 'px-3 py-1.5' : 'px-4 py-2.5'

  const kindOf = (column: string): FilterKind => kinds?.[column] ?? kindFromRows(allRows, column)
  const labelOf = (column: string) => column.replace(/_/g, ' ')
  const figures = useMemo(
    () => (lumen ? figureColumns(displayCols, allRows) : new Set<string>()),
    // eslint-disable-next-line react-hooks/exhaustive-deps -- displayCols is made from columns and allColumns each render
    [lumen, allRows, columns, allColumns],
  )
  const pills = useMemo(
    () => (lumen ? pillColumns(displayCols, allRows, Object.fromEntries(displayCols.map((c) => [c, kinds?.[c] ?? kindFromRows(allRows, c)]))) : new Set<string>()),
    // eslint-disable-next-line react-hooks/exhaustive-deps -- displayCols is made from columns and allColumns each render
    [lumen, allRows, kinds, columns, allColumns],
  )
  const active = filters.filter(isComplete)
  const shownRows = useMemo(
    () => (remote || !active.length ? allRows : allRows.filter((row) => active.every((f) => matchesFilter(f, row[f.column], String(row[f.column] ?? ''), kindOf(f.column))))),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [allRows, active.length, ownFilters, remote],
  )
  const pickList = (column: string) => (contains: string): Promise<PickList> => {
    if (loadValues) return loadValues(column, contains)
    const others = active.filter((f) => f.column !== column)
    const source = others.length ? allRows.filter((row) => others.every((f) => matchesFilter(f, row[f.column], String(row[f.column] ?? ''), kindOf(f.column)))) : allRows
    return Promise.resolve(valuesFromRows(source, column, contains))
  }

  if (!shownRows.length && !active.length) {
    return (
      <div
        className={`flex flex-col items-center justify-center rounded-lg border border-dashed border-[color:var(--color-border-strong)] bg-muted/50 text-center ${
          fill ? 'h-full min-h-[16rem]' : 'py-8'
        }`}
      >
        <p className="text-sm text-[color:var(--color-text-muted)]">{emptyMessage}</p>
      </div>
    )
  }

  return (
    <div className={`w-full overflow-hidden rounded-lg border border-[color:var(--color-border)] ${lumen ? 'lumen-table' : ''} ${fill ? 'flex h-full min-h-0 flex-col' : ''}`}>
      <div className={`overflow-auto ${fill ? 'min-h-0 flex-1' : ''}`} style={!fill && maxHeight ? { maxHeight } : undefined}>
        {active.length > 0 && (
          <div className="border-b border-[color:var(--color-border)] px-3 py-2">
            <FilterChips filters={filters} labelOf={labelOf} kindOf={kindOf} onRemove={(column) => change(column, null)} onClear={() => active.forEach((f) => change(f.column, null))} />
          </div>
        )}
        <table className="w-full min-w-full text-left text-sm">
          <thead className="sticky top-0 z-[1]">
            <tr className="border-b border-[color:var(--color-border)] bg-[color:var(--color-surface-hover)]">
              {displayCols.map((col) => {
                const sorted = sort === col
                const icon = !onSort ? null : sorted && dir === 'asc' ? (
                  <ArrowUp className="h-3 w-3" />
                ) : sorted && dir === 'desc' ? (
                  <ArrowDown className="h-3 w-3" />
                ) : (
                  <ArrowUpDown className="h-3 w-3 opacity-40" />
                )
                const label = col.replace(/_/g, ' ')
                return (
                  <th
                    key={col}
                    className={`${cell} whitespace-nowrap text-[11px] font-semibold uppercase tracking-wider text-[color:var(--color-text-faint)] ${lumen && (kindOf(col) === 'number' || figures.has(col)) ? 'text-right' : ''}`}
                    aria-sort={sorted ? (dir === 'asc' ? 'ascending' : 'descending') : 'none'}
                  >
                    <span className="inline-flex items-center gap-1">
                      {onSort ? (
                        <button
                          type="button"
                          onClick={() => onSort(col)}
                          className={`inline-flex items-center gap-1 uppercase tracking-wider transition-colors hover:text-[color:var(--color-text)] ${
                            sorted ? 'text-[color:var(--color-text)]' : ''
                          }`}
                        >
                          {label}
                          {icon}
                        </button>
                      ) : (
                        label
                      )}
                      {filtering && (
                        <ColumnFilterMenu
                          column={col}
                          label={label}
                          kind={kindOf(col)}
                          filter={filters.find((f) => f.column === col)}
                          loadValues={remote && !loadValues ? undefined : pickList(col)}
                          onChange={(next) => change(col, next)}
                        />
                      )}
                    </span>
                  </th>
                )
              })}
            </tr>
          </thead>
          <tbody>
            {shownRows.length === 0 && (
              <tr>
                <td colSpan={displayCols.length} className="px-4 py-8 text-center text-sm text-[color:var(--color-text-muted)]">
                  No row matches these filters.
                </td>
              </tr>
            )}
            {shownRows.map((row, i) => (
              <tr
                key={i}
                {...(onRowClick
                  ? {
                      onClick: () => onRowClick(row),
                      onKeyDown: (event: React.KeyboardEvent) => {
                        if (event.key === 'Enter') onRowClick(row)
                      },
                      tabIndex: 0,
                      title: rowHint,
                    }
                  : {})}
                className={`border-b border-[color:var(--color-border)] bg-surface transition-colors last:border-0 ${
                  onRowClick ? 'cursor-pointer' : ''
                } ${
                  hot
                    ? 'hover:bg-accent-dim/50 hover:shadow-[inset_3px_0_0_var(--orion-accent)]'
                    : 'hover:bg-[color:var(--color-surface-hover)]'
                }`}
              >
                {displayCols.map((col) => {
                  const text = String(row[col] ?? '—')
                  const bill = row[col] ? billColumn(col) : null
                  return (
                    <td
                      key={col}
                      className={`${cell} ${fill ? '' : 'max-w-[180px] truncate'} text-[color:var(--color-text)] ${lumen && (kindOf(col) === 'number' || figures.has(col)) ? 'text-right tabular-nums' : ''}`}
                      title={text}
                    >
                      {bill === 'number' ? <BillNumber number={text} /> : bill === 'code' ? <BillNumber code={text} /> : lumen ? <LumenCell value={row[col]} kind={kindOf(col)} pill={pills.has(col)} /> : text}
                    </td>
                  )
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  )
}

export function LoadingState({ message = 'Loading…' }: { message?: string }) {
  return (
    <div className="flex flex-col items-center justify-center gap-3 py-20">
      <div className="h-6 w-6 animate-spin rounded-full border-2 border-[color:var(--color-border)] border-t-[color:var(--color-accent)]" />
      <p className="text-sm text-[color:var(--color-text-muted)]">{message}</p>
    </div>
  )
}
