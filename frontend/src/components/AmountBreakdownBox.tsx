import { Field, Input } from './ui/Field'
import { MoneyInput } from './ui/MoneyInput'

function toNumber(value: unknown): number {
  if (value == null || value === '') return 0
  const n = Number(value)
  return Number.isFinite(n) ? n : 0
}

function roundMoney(value: number): number {
  return Math.round(value * 100) / 100
}

function parseNumber(raw: string): number | null {
  if (raw.trim() === '') return null
  const n = Number(raw)
  return Number.isFinite(n) ? n : null
}

function percentOf(amount: number, part: unknown): string {
  if (!amount) return ''
  return String(roundMoney((toNumber(part) / amount) * 100))
}

function displayAmount(value: unknown): string {
  if (value == null || value === '') return ''
  return String(value)
}

export function AmountBreakdownBox({
  values,
  onChange,
  totalOverridden,
  onTotalOverride,
  amountField = 'transaction_amount',
}: {
  values: Record<string, unknown>
  onChange: (key: string, value: unknown) => void
  totalOverridden: boolean
  onTotalOverride: (overridden: boolean) => void
  amountField?: string
}) {
  const amount = toNumber(values[amountField])
  const tax = toNumber(values.tax)
  const gst = toNumber(values.gst)
  const calculatedTotal = roundMoney(amount + tax + gst)

  const setAmount = (raw: string) => {
    onChange(amountField, parseNumber(raw))
  }

  const setTaxAmount = (raw: string) => {
    onChange('tax', parseNumber(raw))
  }

  const setGstAmount = (raw: string) => {
    onChange('gst', parseNumber(raw))
  }

  const setTaxPercent = (raw: string) => {
    const pct = parseNumber(raw)
    if (pct == null) {
      onChange('tax', null)
      return
    }
    onChange('tax', roundMoney((amount * pct) / 100))
  }

  const setGstPercent = (raw: string) => {
    const pct = parseNumber(raw)
    if (pct == null) {
      onChange('gst', null)
      return
    }
    onChange('gst', roundMoney((amount * pct) / 100))
  }

  return (
    <div className="sm:col-span-2 rounded-lg border border-warning/30 bg-warning-dim p-4">
      <p className="mb-3 text-sm font-semibold text-warning">Amount calculation</p>
      <div className="space-y-3">
        <div className="grid items-end gap-3 sm:grid-cols-[1fr_7rem_8rem]">
          <Field label="Amount">
            <MoneyInput value={displayAmount(values[amountField])} onChange={setAmount} />
          </Field>
          <p className="hidden pb-2 text-xs text-[color:var(--color-text-faint)] sm:block"> </p>
          <p className="hidden pb-2 text-xs text-[color:var(--color-text-faint)] sm:block"> </p>
        </div>

        <div className="grid items-end gap-3 sm:grid-cols-[1fr_7rem_8rem]">
          <p className="pb-2 text-sm font-medium text-[color:var(--color-text-muted)]">Tax added</p>
          <Field label="Percent">
            <div className="relative">
              <Input
                type="number"
                step="any"
                className="pr-7"
                value={percentOf(amount, values.tax)}
                onChange={(e) => setTaxPercent(e.target.value)}
              />
              <span className="pointer-events-none absolute right-2.5 top-1/2 -translate-y-1/2 text-sm text-[color:var(--color-text-muted)]">
                %
              </span>
            </div>
          </Field>
          <Field label="Amount">
            <MoneyInput value={displayAmount(values.tax)} onChange={setTaxAmount} />
          </Field>
        </div>

        <div className="grid items-end gap-3 sm:grid-cols-[1fr_7rem_8rem]">
          <p className="pb-2 text-sm font-medium text-[color:var(--color-text-muted)]">GST added</p>
          <Field label="Percent">
            <div className="relative">
              <Input
                type="number"
                step="any"
                className="pr-7"
                value={percentOf(amount, values.gst)}
                onChange={(e) => setGstPercent(e.target.value)}
              />
              <span className="pointer-events-none absolute right-2.5 top-1/2 -translate-y-1/2 text-sm text-[color:var(--color-text-muted)]">
                %
              </span>
            </div>
          </Field>
          <Field label="Amount">
            <MoneyInput value={displayAmount(values.gst)} onChange={setGstAmount} />
          </Field>
        </div>

        <div className="border-t border-warning/30 pt-3">
          <div className="grid items-end gap-3 sm:grid-cols-[1fr_7rem_8rem]">
            <p className="pb-2 text-sm font-semibold text-[color:var(--color-text)]">
              Amount after tax &amp; GST
            </p>
            <p className="hidden pb-2 sm:block" />
            <Field label="Total">
              <MoneyInput
                value={displayAmount(values.amount_after_tax_gst)}
                onChange={(raw) => {
                  onTotalOverride(true)
                  onChange('amount_after_tax_gst', parseNumber(raw))
                }}
              />
            </Field>
          </div>
          <p className="mt-2 text-xs text-[color:var(--color-text-muted)]">
            {amount.toLocaleString('en-IN')} + {tax.toLocaleString('en-IN')} tax + {gst.toLocaleString('en-IN')} GST ={' '}
            {calculatedTotal.toLocaleString('en-IN')}
            {totalOverridden ? (
              <>
                {' '}
                <button
                  type="button"
                  className="font-medium text-accent hover:underline"
                  onClick={() => onTotalOverride(false)}
                >
                  Use calculated total
                </button>
              </>
            ) : (
              ' · Edit percent or amount; the other updates automatically.'
            )}
          </p>
        </div>
      </div>
    </div>
  )
}
