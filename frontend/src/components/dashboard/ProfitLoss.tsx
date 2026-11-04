import type { TableBlock } from '../../types'

const rupees = (value: number) => `${value < 0 ? '−' : ''}₹ ${Math.abs(value).toLocaleString('en-IN', { maximumFractionDigits: 0 })}`

/**
 * The profit and loss statement: revenue, direct cost, contribution margin, head office, operating profit, and (for someone with Bank access) what the bank book adds below it.
 * The rows come from the server in order, each with a kind: a line, a subtotal, a total (a result), a memo (shown, not added in) or a note (a sentence). Nothing is worked out here.
 */
export function ProfitLoss({ block }: { block: TableBlock }) {
  return (
    <table className="w-full text-sm" aria-label="Profit and loss">
      <thead>
        <tr className="border-b border-[color:var(--color-border)] text-left text-xs text-[color:var(--color-text-muted)]">
          <th scope="col" className="py-1.5 pr-3 font-medium">Line</th>
          <th scope="col" className="py-1.5 px-3 text-right font-medium">Amount</th>
          <th scope="col" className="py-1.5 pl-3 text-right font-medium">% of revenue</th>
        </tr>
      </thead>
      <tbody>
        {block.rows.map((row, index) => {
          const kind = String(row.kind)
          const label = String(row.label)
          if (kind === 'note') {
            return (
              <tr key={index}>
                <td colSpan={3} className="pt-2 text-xs text-[color:var(--color-text-muted)]">
                  {label}
                </td>
              </tr>
            )
          }
          const amount = Number(row.amount)
          const share = row.pct === '' ? '' : `${Number(row.pct).toFixed(1)}%`
          const strong = kind === 'total'
          const sub = kind === 'subtotal'
          const memo = kind === 'memo'
          return (
            <tr
              key={index}
              className={[
                strong ? 'border-t border-[color:var(--color-border)] bg-[color:var(--color-surface-hover)] font-semibold' : '',
                sub ? 'border-t border-dashed border-[color:var(--color-border)] font-medium' : '',
                memo ? 'italic text-[color:var(--color-text-muted)]' : '',
              ].join(' ')}
            >
              <th scope="row" className={`py-1.5 pr-3 text-left ${strong ? 'font-semibold' : sub ? 'font-medium' : 'font-normal'}`} style={{ paddingLeft: `${Number(row.indent) * 1.25}rem` }} title={String(row.note || '') || undefined}>
                {label}
              </th>
              <td className={`px-3 py-1.5 text-right tabular-nums ${strong && amount < 0 ? 'text-negative' : ''}`}>{rupees(amount)}</td>
              <td className="py-1.5 pl-3 text-right tabular-nums text-[color:var(--color-text-muted)]">{memo ? '' : share}</td>
            </tr>
          )
        })}
      </tbody>
    </table>
  )
}
