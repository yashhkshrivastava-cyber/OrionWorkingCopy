import { Plus, Trash2 } from 'lucide-react'
import { MAX_LINE_COLUMNS, SKIP_KEYS, daysInMonth, money, type LineInput, type SkipKey } from '../../billing/billCalc'
import { SUMMARY_LABELS, UNIT_SETUP, standardLabel } from '../../billing/billLayout'
import { wordsOfAmount } from '../../billing/moneyText'
import type { LineSetup } from '../../types'
import { Button } from '../ui/Button'
import { Checkbox, Input } from '../ui/Field'
import { MoneyInput } from '../ui/MoneyInput'
import { Segmented } from '../ui/Segmented'

const BASES: { id: LineSetup['basis']; label: string }[] = [
  { id: 'unit', label: 'Quantity × rate' },
  { id: 'daily', label: 'Daily rate × days' },
  { id: 'monthly', label: 'Monthly rate × days' },
]

/** The name a column has on this bill: the one the bill chose, else the standard one. */
export const nameOf = (setup: LineSetup, key: 'particulars' | 'qty' | 'rate' | 'days' | 'amount') =>
  setup.labels[key] || standardLabel(key, setup.basis)

const caption = 'mb-0.5 block truncate text-[11px] font-medium text-[color:var(--color-text-muted)]'

/**
 * The boxes of one line after its description: the bill's own columns, then quantity, rate, days (a day-based bill) and what the line
 * comes to. Each is named as the bill names its column. Used by both layouts of the editor.
 */
export function LineFields({
  index,
  line,
  setup,
  amount,
  onChange,
}: {
  index: number
  line: LineInput
  setup: LineSetup
  amount: number | null
  onChange: (patch: Partial<LineInput>) => void
}) {
  const dayBased = setup.basis !== 'unit'
  const ready = amount !== null && Boolean(line.rate) && (dayBased ? Boolean(line.days) || setup.basis === 'monthly' : Boolean(line.qty))
  const typing = line.manual !== undefined // the amount is being entered by hand
  const entered = typing && line.manual !== '' ? Number(line.manual) : null
  const differs = entered !== null && amount !== null && Math.abs(entered - amount) >= 0.005
  const skip = line.skip ?? []
  return (
    <div className="space-y-1">
      <div className="flex flex-wrap items-end gap-2">
        {setup.columns.map((column) => (
          <label key={column.key} className="w-28">
            <span className={caption}>{column.label}</span>
            <Input
              aria-label={`Line ${index + 1} ${column.label}`}
              maxLength={80}
              value={line.fields?.[column.key] ?? ''}
              onChange={(e) => onChange({ fields: { ...line.fields, [column.key]: e.target.value } })}
            />
          </label>
        ))}
        <label className="w-24">
          <span className={caption}>{nameOf(setup, 'qty')}</span>
          <Input
            aria-label={`Line ${index + 1} ${nameOf(setup, 'qty')}`}
            inputMode="decimal"
            className="text-right"
            value={line.qty}
            onChange={(e) => onChange({ qty: e.target.value })}
          />
        </label>
        <label className="w-28">
          <span className={caption}>{nameOf(setup, 'rate')}</span>
          <MoneyInput
            aria-label={`Line ${index + 1} ${nameOf(setup, 'rate')}`}
            className="text-right"
            words={false}
            value={line.rate}
            onChange={(raw) => onChange({ rate: raw })}
          />
        </label>
        {dayBased && (
          <label className="w-24">
            <span className={caption}>{nameOf(setup, 'days')}</span>
            <Input
              aria-label={`Line ${index + 1} ${nameOf(setup, 'days')}`}
              inputMode="decimal"
              className="text-right"
              placeholder={setup.basis === 'monthly' ? 'Whole month' : ''}
              value={line.days ?? ''}
              onChange={(e) => onChange({ days: e.target.value })}
            />
          </label>
        )}
        <div className="ml-auto min-w-[7.5rem]">
          <span className={caption}>{nameOf(setup, 'amount')}</span>
          {typing ? (
            <MoneyInput
              aria-label={`Line ${index + 1} ${nameOf(setup, 'amount')}, entered`}
              className="text-right"
              words={false}
              value={line.manual}
              onChange={(raw) => onChange({ manual: raw })}
            />
          ) : (
            <span
              className={`block rounded-full px-3 py-2 text-right text-sm font-semibold tabular-nums ${ready ? 'bg-accent-dim text-accent' : 'bg-muted text-[color:var(--color-text-faint)]'}`}
            >
              {ready && amount !== null ? `₹ ${money(amount)}` : '₹ —'}
            </span>
          )}
        </div>
      </div>
      <div className="flex flex-wrap items-center justify-end gap-x-4 gap-y-1 text-xs text-[color:var(--color-text-muted)]">
        {setup.charge_by_line && (
          <span className="mr-auto flex flex-wrap items-center gap-x-3 gap-y-1">
            Part of:
            {SKIP_KEYS.map((key: SkipKey) => (
              <Checkbox
                key={key}
                label={SUMMARY_LABELS[key]}
                checked={!skip.includes(key)}
                onChange={(counted) => onChange({ skip: counted ? skip.filter((k) => k !== key) : [...skip, key] })}
              />
            ))}
          </span>
        )}
        {typing ? (
          <button type="button" className="underline hover:text-[color:var(--color-text)]" onClick={() => onChange({ manual: undefined })}>
            Use the calculated amount{amount !== null ? ` (₹ ${money(amount)})` : ''}
          </button>
        ) : (
          <button type="button" className="underline hover:text-[color:var(--color-text)]" onClick={() => onChange({ manual: '' })}>
            Enter the amount myself
          </button>
        )}
      </div>
      {differs && (
        <p className="text-right text-xs text-warning">
          This does not match the quantity, rate and days (₹ {money(amount as number)}). It will be saved as entered: ₹ {money(entered as number)}.
        </p>
      )}
      {line.rate && wordsOfAmount(line.rate) && (
        <p className="text-right text-xs text-[color:var(--color-text-muted)]">{nameOf(setup, 'rate')}: {wordsOfAmount(line.rate)}</p>
      )}
    </div>
  )
}

/** How this bill's lines are worked out and laid out: the basis, the days, a total row, the names of the columns and its own columns. */
export function LineSetupEditor({ setup, month, onChange }: { setup: LineSetup; month: string; onChange: (next: LineSetup) => void }) {
  const set = (patch: Partial<LineSetup>) => onChange({ ...setup, ...patch })
  const setLabel = (key: keyof LineSetup['labels'], value: string) => set({ labels: { ...setup.labels, [key]: value } })
  const addColumn = () => {
    let n = 1
    while (setup.columns.some((column) => column.key === `c${n}`)) n += 1
    set({ columns: [...setup.columns, { key: `c${n}`, label: '' }] })
  }
  const dayBased = setup.basis !== 'unit'
  const named = Object.values(setup.labels).some(Boolean) || setup.columns.length > 0 || setup.totals_row || setup.basis !== UNIT_SETUP.basis
  const keys: ('particulars' | 'qty' | 'rate' | 'days' | 'amount')[] = dayBased ? ['particulars', 'qty', 'rate', 'days', 'amount'] : ['particulars', 'qty', 'rate', 'amount']

  return (
    <details className="rounded-lg border border-[color:var(--color-border)] p-3" open={named}>
      <summary className="cursor-pointer text-sm font-semibold text-[color:var(--color-text)]">
        How the lines are worked out
        <span className="ml-2 text-xs font-normal text-[color:var(--color-text-muted)]">
          {BASES.find((basis) => basis.id === setup.basis)?.label}
          {setup.columns.length ? `, ${setup.columns.length} extra column${setup.columns.length > 1 ? 's' : ''}` : ''}
        </span>
      </summary>
      <div className="mt-3 space-y-4">
        <div className="space-y-1.5">
          <Segmented label="How a line's amount is worked out" value={setup.basis} options={BASES} onChange={(basis) => set({ basis })} />
          {setup.basis === 'unit' && <p className="text-xs text-[color:var(--color-text-muted)]">Amount = quantity × rate.</p>}
          {setup.basis === 'daily' && <p className="text-xs text-[color:var(--color-text-muted)]">Amount = rate per day × days (× the quantity, if ticked below).</p>}
          {setup.basis === 'monthly' && (
            <p className="text-xs text-[color:var(--color-text-muted)]">
              Amount = monthly rate × days ÷ days in the month (× the quantity, if ticked below). Leave the days empty for the whole month.
            </p>
          )}
        </div>
        {dayBased && (
          <div className="space-y-2">
            <Checkbox
              label="Multiply by the quantity too (for example persons × daily wage × days)"
              checked={setup.qty_multiplies}
              onChange={(qty_multiplies) => set({ qty_multiplies })}
            />
            {setup.basis === 'monthly' && (
              <label className="flex items-center gap-2 text-sm text-[color:var(--color-text)]">
                Days in the month
                <Input
                  className="w-20 text-right"
                  inputMode="numeric"
                  aria-label="Days in the month"
                  placeholder={String(daysInMonth(month))}
                  value={setup.month_days ?? ''}
                  onChange={(e) => set({ month_days: e.target.value.trim() ? Math.min(31, Number(e.target.value.replace(/\D/g, '')) || 0) || null : null })}
                />
                <span className="text-xs text-[color:var(--color-text-muted)]">empty: the actual days of the month</span>
              </label>
            )}
          </div>
        )}
        <Checkbox
          label="Some lines are left out of EPFO, ESIC or service charges (each line then shows what it is part of)"
          checked={setup.charge_by_line}
          onChange={(charge_by_line) => set({ charge_by_line })}
        />

        <div>
          <p className="mb-1.5 text-xs font-medium text-[color:var(--color-text-muted)]">
            Extra columns. Each line gets a box for them and they print between the particulars and the quantity.
          </p>
          <div className="space-y-2">
            {setup.columns.map((column, index) => (
              <div key={column.key} className="flex items-center gap-2">
                <Input
                  className="min-w-0 flex-1"
                  aria-label={`Extra column ${index + 1} name`}
                  placeholder="Name, for example Area"
                  maxLength={30}
                  value={column.label}
                  onChange={(e) => set({ columns: setup.columns.map((other, i) => (i === index ? { ...other, label: e.target.value } : other)) })}
                />
                <button
                  type="button"
                  aria-label={`Remove column ${column.label || index + 1}`}
                  onClick={() => set({ columns: setup.columns.filter((_, i) => i !== index) })}
                  className="rounded p-1.5 text-[color:var(--color-text-faint)] hover:bg-muted hover:text-negative"
                >
                  <Trash2 className="h-4 w-4" />
                </button>
              </div>
            ))}
          </div>
          <Button variant="secondary" size="sm" className="mt-2" disabled={setup.columns.length >= MAX_LINE_COLUMNS} onClick={addColumn}>
            <Plus className="h-4 w-4" /> Add a column
          </Button>
        </div>

        <div>
          <p className="mb-1.5 text-xs font-medium text-[color:var(--color-text-muted)]">Column names on the bill. Leave one empty to keep its usual name.</p>
          <div className="grid gap-2 sm:grid-cols-2">
            {keys.map((key) => (
              <label key={key} className="block">
                <span className={caption}>{standardLabel(key, setup.basis)}</span>
                <Input
                  aria-label={`Name of the ${standardLabel(key, setup.basis)} column`}
                  maxLength={30}
                  placeholder={standardLabel(key, setup.basis)}
                  value={setup.labels[key] ?? ''}
                  onChange={(e) => setLabel(key, e.target.value)}
                />
              </label>
            ))}
          </div>
          <p className="mb-1.5 mt-3 text-xs font-medium text-[color:var(--color-text-muted)]">Names of the rows of the totals.</p>
          <div className="grid gap-2 sm:grid-cols-2">
            {(Object.keys(SUMMARY_LABELS) as (keyof typeof SUMMARY_LABELS)[]).map((key) => (
              <label key={key} className="block">
                <span className={caption}>{SUMMARY_LABELS[key]}</span>
                <Input
                  aria-label={`Name of the ${SUMMARY_LABELS[key]} row`}
                  maxLength={30}
                  placeholder={SUMMARY_LABELS[key]}
                  value={setup.labels[key] ?? ''}
                  onChange={(e) => setLabel(key, e.target.value)}
                />
              </label>
            ))}
          </div>
        </div>
      </div>
    </details>
  )
}
