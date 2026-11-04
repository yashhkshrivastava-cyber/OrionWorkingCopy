import type { TableBlock } from '../../types'
import { Empty } from './CategoryBar'

/** Cell colour for a percentage: rose below zero, a quiet neutral near the middle, teal as it gets healthier. */
function shade(value: number, good: number): string {
  if (value < 0) {
    const strength = Math.min(1, Math.abs(value) / 15)
    return `color-mix(in srgb, var(--orion-s-neg) ${Math.round(18 + strength * 45)}%, transparent)`
  }
  const strength = Math.min(1, value / good)
  return `color-mix(in srgb, var(--orion-s-primary) ${Math.round(8 + strength * 52)}%, transparent)`
}

/**
 * A grid of percentages, one row per business line and one column per year, shaded by how healthy each is.
 * Reading across a row shows a line improving or sliding; down a column shows which lines carry the year.
 * Clicking a row label filters the page to that line.
 */
export function Heatmap({
  block,
  selected,
  onSelect,
  good = 20,
  emptyMessage = 'Nothing in this selection.',
}: {
  block: TableBlock
  selected?: string
  onSelect?: (code: string) => void
  /** The percentage at which a cell is as green as it gets. */
  good?: number
  emptyMessage?: string
}) {
  if (!block.rows.length) return <Empty height={160} message={emptyMessage} />
  const [labelCol, ...valueCols] = block.columns
  const clickable = Boolean(block.filter_key && onSelect)

  return (
    <div className="overflow-x-auto px-3 pb-2">
      <table className="w-full border-separate border-spacing-1 text-xs">
        <thead>
          <tr>
            <th className="px-2 py-1 text-left font-medium text-[color:var(--color-text-muted)]">{labelCol.label}</th>
            {valueCols.map((col) => (
              <th key={col.key} className="px-2 py-1 text-center font-medium text-[color:var(--color-text-muted)]">
                {col.label}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {block.rows.map((row) => {
            const code = String(row.code ?? row[labelCol.key])
            const dim = selected && selected !== code
            return (
              <tr key={code} className={dim ? 'opacity-40' : ''}>
                <th scope="row" className="max-w-[12rem] truncate px-2 py-1 text-left font-medium text-[color:var(--color-text)]">
                  {clickable ? (
                    <button type="button" onClick={() => onSelect?.(code)} className="max-w-full truncate text-left hover:text-accent hover:underline">
                      {String(row[labelCol.key])}
                    </button>
                  ) : (
                    String(row[labelCol.key])
                  )}
                </th>
                {valueCols.map((col) => {
                  const value = row[col.key]
                  const has = value !== null && value !== undefined && value !== ''
                  return (
                    <td
                      key={col.key}
                      className="rounded-md px-2 py-2 text-center font-semibold tabular-nums text-[color:var(--color-text)]"
                      style={{ background: has ? shade(Number(value), good) : 'var(--color-muted, transparent)' }}
                      title={has ? `${row[labelCol.key]}, ${col.label}: ${Number(value).toFixed(1)}%` : 'No revenue'}
                    >
                      {has ? `${Number(value).toFixed(0)}%` : '–'}
                    </td>
                  )
                })}
              </tr>
            )
          })}
        </tbody>
      </table>
    </div>
  )
}
