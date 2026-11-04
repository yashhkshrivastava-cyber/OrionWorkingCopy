import type { CellFormat, TableBlock } from '../../types'
import { BillNumber } from '../billing/BillNumber'
import { count, inr } from './format'

function render(value: string | number | undefined, format: CellFormat): string {
  if (value === null || value === undefined || value === '') return '—'
  if (format === 'money') return inr(Number(value))
  if (format === 'number') return count(Number(value))
  if (format === 'percent') return `${Number(value).toFixed(1)}%`
  return String(value)
}

const PLAIN = 'text-[color:var(--color-text-muted)]'
const GOOD = 'font-medium text-positive'
const WATCH = 'font-medium text-warning'
const BAD = 'font-medium text-negative'

/**
 * Colour the judgement columns so problem rows stand out. Beating a revenue
 * target is good news; beating a cost allowance is not, so the two read
 * differently even though both are percentages.
 */
function tone(key: string, value: string | number, format: CellFormat): string {
  const numeric = Number(value)
  if (key.includes('margin')) {
    if (numeric < 0) return BAD
    if (format === 'percent') return numeric >= 15 ? GOOD : numeric >= 5 ? PLAIN : WATCH
    return PLAIN
  }
  if (format !== 'percent') return PLAIN
  if (key.includes('attainment')) {
    if (numeric >= 100) return GOOD
    return numeric >= 75 ? PLAIN : WATCH
  }
  if (key.includes('utilisation')) {
    if (numeric > 100) return BAD
    return numeric >= 85 ? WATCH : PLAIN
  }
  return PLAIN
}

/**
 * Renders any table block the backend sends. When the block declares a
 * ``filter_key``, rows become filter toggles like the charts.
 */
export function DataGrid({
  block,
  selected,
  onSelect,
  emptyMessage = 'Nothing in this selection.',
}: {
  block: TableBlock
  selected?: string
  onSelect?: (code: string) => void
  emptyMessage?: string
}) {
  if (!block.rows.length) {
    return <div data-empty="true" className="px-3 py-3 text-xs text-[color:var(--color-text-faint)]">{emptyMessage}</div>
  }

  const clickable = Boolean(block.filter_key && onSelect)
  const first = block.columns[0]
  const bars =
    block.columns.length <= 3 && !block.columns.some((col) => col.key === 'share')
      ? block.columns.find((col) => col.format === 'money')
      : undefined

  const max = bars
    ? Math.max(...block.rows.map((row) => Math.abs(Number(row[bars.key]) || 0)), 1)
    : 0

  return (
    <div className="-mx-2 overflow-x-auto px-1 sm:mx-0">
      <table className="w-full min-w-[520px] text-left text-sm">
        <thead>
          <tr className="text-[11px] uppercase tracking-wide text-[color:var(--color-text-faint)]">
            {block.columns.map((col) => (
              <th
                key={col.key}
                className={`px-4 py-2 font-medium ${col.align === 'right' ? 'text-right' : ''}`}
              >
                {col.label}
              </th>
            ))}
            {bars && <th className="w-24 px-4 py-2 font-medium">Share</th>}
          </tr>
        </thead>
        <tbody>
          {block.rows.map((row, index) => {
            const code = String(row.code ?? index)
            const isSelected = clickable && selected === code
            const isDim = clickable && Boolean(selected) && !isSelected
            return (
              <tr
                key={`${code}-${index}`}
                onClick={clickable ? () => onSelect?.(code) : undefined}
                className={`border-t border-[color:var(--color-border)] transition-all duration-200 ${
                  clickable ? 'cursor-pointer' : ''
                } ${isSelected ? 'bg-accent-dim/60' : clickable ? 'hover:bg-muted/80 hover:shadow-[inset_3px_0_0_var(--orion-accent)]' : ''} ${
                  isDim ? 'opacity-45' : ''
                }`}
              >
                {block.columns.map((col) => (
                  <td
                    key={col.key}
                    className={`px-4 py-2.5 ${col.align === 'right' ? 'text-right tabular-nums' : ''} ${
                      col.key === first.key
                        ? 'font-medium text-[color:var(--color-text)]'
                        : tone(col.key, row[col.key], col.format)
                    }`}
                  >
                    {col.format === 'bill' && row[col.key] ? (
                      <BillNumber number={String(row[col.key])} />
                    ) : col.key === first.key ? (
                      <span className="block max-w-[16rem] whitespace-normal break-words leading-snug" title={String(row[col.key] ?? '')}>
                        {render(row[col.key], col.format)}
                      </span>
                    ) : (
                      render(row[col.key], col.format)
                    )}
                  </td>
                ))}
                {bars && (
                  <td className="px-4 py-2.5">
                    <div className="h-1.5 w-full overflow-hidden rounded-full bg-muted">
                      <div
                        className="h-full rounded-full bg-primary transition-all duration-500"
                        style={{ width: `${(Math.abs(Number(row[bars.key]) || 0) / max) * 100}%` }}
                      />
                    </div>
                  </td>
                )}
              </tr>
            )
          })}
        </tbody>
      </table>
    </div>
  )
}
