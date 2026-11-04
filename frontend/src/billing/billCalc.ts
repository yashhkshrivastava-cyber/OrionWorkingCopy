/**
 * Bill arithmetic for the live preview. It follows the rules in backend/app/billing.py
 * exactly, and uses integers (paise) rather than floats so that a half-paisa rounds the
 * same way here as it does on the server. The server recalculates when a bill is saved.
 */

import type { LineSetup } from '../types'
import { UNIT_SETUP } from './billLayout'

/** The server's limits (backend/app/billing.py). Beyond them it refuses to save, so the preview must refuse too and say so. */
export const MAX_LINES = 30
export const MAX_EXTRA_CHARGES = 6
const MAX_QTY_THOUSANDTHS = 1_000_000n * 1000n
const MAX_RATE_PAISE = 100_000_000n * 100n
const MAX_DAYS_HUNDREDTHS = 100_000n * 100n
const MAX_AMOUNT_PAISE = 10_000_000_000n * 100n
export const MAX_LINE_COLUMNS = 5

export type BillRates = {
  epf_pct: string
  esic_pct: string
  service_pct: string
  cgst_pct: string
  sgst_pct: string
}

export const DEFAULT_RATES: BillRates = {
  epf_pct: '13',
  esic_pct: '3.25',
  service_pct: '10',
  cgst_pct: '9',
  sgst_pct: '9',
}

/** The charges a line can be left out of: its amount then is not part of what the percentage is taken of. */
export const SKIP_KEYS = ['epf', 'esic', 'service'] as const
export type SkipKey = (typeof SKIP_KEYS)[number]

/** The figures a person can enter instead of the calculated one, and their names. */
export const MANUAL_NAMES = {
  epf_amount: 'EPFO',
  esic_amount: 'ESIC',
  service_amount: 'Service charges',
  cgst_amount: 'CGST',
  sgst_amount: 'SGST',
} as const
export type ManualKey = keyof typeof MANUAL_NAMES
export type ManualInput = Partial<Record<ManualKey, string>>

/**
 * One line as typed. `days` is used on a day-based bill, `fields` holds the values of the bill's own columns (by column key),
 * `manual` is the amount entered instead of the worked-out one, and `skip` lists the charges the line is left out of.
 */
export type LineInput = {
  particulars: string
  qty: string
  rate: string
  days?: string
  fields?: Record<string, string>
  manual?: string
  skip?: SkipKey[]
}

/** A charge the user named: a percentage of the lines total, or a fixed amount. */
export type ExtraInput = { label: string; kind: 'pct' | 'amount'; value: string }

export type ExtraFigure = { label: string; kind: 'pct' | 'amount'; value: number; amount: number }

export type BillLineFigure = {
  particulars: string
  qty: string | null
  rate: number | null
  days?: string | null
  fields?: Record<string, string>
  skip?: SkipKey[]
  /** The amount was entered; `auto_amount` is what the quantity, rate and days came to (null when they were not all given). */
  manual?: boolean
  auto_amount?: number | null
  amount: number
}

export type BillFigures = {
  lines: BillLineFigure[]
  lines_total: number
  epf_amount: number
  esic_amount: number
  sub_total: number
  service_amount: number
  extra_charges: ExtraFigure[]
  taxable_total: number
  cgst_amount: number
  sgst_amount: number
  round_off: number
  grand_total: number
  /** The figures that were entered, with what the calculation gave: the warning for a figure that does not match. */
  manual_figures: Partial<Record<ManualKey, { value: number; auto: number }>>
  /** What the calculation gives for each of them, entered or not, and the lines each charge is taken of. */
  auto: Record<ManualKey, number>
  bases: Record<SkipKey, number>
}

/** "3.25" -> 325n at scale 2. More digits than the scale round half up. Null if it is not a plain number. */
function scaled(value: string, scale: number): bigint | null {
  const text = value.trim()
  if (!/^\d*\.?\d*$/.test(text) || text === '' || text === '.') return null
  const [whole, fraction = ''] = text.split('.')
  const digits = (whole || '0') + fraction.padEnd(scale, '0').slice(0, scale)
  let result = BigInt(digits)
  if (fraction.length > scale && fraction.charCodeAt(scale) >= 53) result += 1n // '5'
  return result
}

/** True when the number, as typed and before any rounding, is more than `limit`. 100.004 is over 100 even though it rounds to 100.00. */
function exceeds(value: string, limit: bigint): boolean {
  const [whole, fraction = ''] = value.trim().split('.')
  const units = BigInt(whole || '0')
  return units > limit || (units === limit && /[1-9]/.test(fraction))
}

function halfUp(numerator: bigint, denominator: bigint): bigint {
  return (numerator + denominator / 2n) / denominator
}

const toRupees = (paise: bigint): number => Number(paise) / 100

export type CalcResult =
  | { ok: true; figures: BillFigures }
  | { ok: false; reason: string; figures: BillFigures | null }

function pct(base: bigint, rate: string): bigint | null {
  const hundredths = scaled(rate || '0', 2)
  if (hundredths === null || exceeds(rate || '0', 100n)) return null
  return halfUp(base * hundredths, 10000n)
}

/** Days in a month ('2026-10'): what a monthly rate is divided by unless the bill names a number. */
export function daysInMonth(month: string): number {
  const [year, number] = month.split('-').map(Number)
  return year && number ? new Date(year, number, 0).getDate() : 30
}

/** The days a monthly rate is divided by on this bill. */
export const monthDaysOf = (setup: LineSetup, month: string): number => setup.month_days || daysInMonth(month)

/**
 * One line's worked-out amount in paise, the same as clean_lines in backend/app/billing.py: quantity x rate; or rate x days, times
 * the quantity when the bill counts it; a monthly rate is divided by the days of the month. Null while a number it needs is not there.
 */
function linePaise(line: LineInput, setup: LineSetup, monthDays: number): bigint | null {
  const qty = scaled(line.qty, 3)
  const rate = scaled(line.rate, 2)
  if (rate === null) return null
  if (setup.basis === 'unit') return qty === null ? null : halfUp(qty * rate, 1000n)
  const needsQty = setup.qty_multiplies
  if (needsQty && qty === null) return null
  const days = line.days?.trim() ? scaled(line.days, 2) : setup.basis === 'monthly' ? BigInt(monthDays) * 100n : null
  if (days === null) return null
  const share = setup.basis === 'monthly' ? BigInt(monthDays) : 1n
  return needsQty ? halfUp((qty as bigint) * rate * days, 100_000n * share) : halfUp(rate * days, 100n * share)
}

const refuse = (reason: string): CalcResult => ({ ok: false, reason, figures: null })

export function calculate(
  lines: LineInput[],
  rates: BillRates,
  extras: ExtraInput[] = [],
  setup: LineSetup = UNIT_SETUP,
  month = '',
  manual: ManualInput = {},
): CalcResult {
  const rows: BillLineFigure[] = []
  let total = 0n
  const base: Record<SkipKey, bigint> = { epf: 0n, esic: 0n, service: 0n }
  const monthDays = monthDaysOf(setup, month)
  const unit = setup.basis === 'unit'
  const needsQty = unit || setup.qty_multiplies

  for (let index = 0; index < lines.length; index += 1) {
    const line = lines[index]
    const values = setup.columns.map((column) => (line.fields?.[column.key] ?? '').split(/\s+/).filter(Boolean).join(' ').slice(0, 80))
    const hasManual = (line.manual ?? '').trim() !== ''
    const blank =
      !line.particulars.trim() && !line.qty.trim() && !line.rate.trim() && !(line.days ?? '').trim() && !hasManual && !values.some(Boolean)
    if (blank) continue
    const number = index + 1
    if (!line.particulars.trim()) return refuse(`Line ${number} needs a description.`)
    const typed = hasManual ? scaled(line.manual ?? '', 2) : null
    if (hasManual && (typed === null || typed > MAX_AMOUNT_PAISE)) return refuse(`Line ${number} amount must be a number.`)
    let qty: bigint | null = null
    if (line.qty.trim() || (needsQty && !hasManual)) {
      qty = scaled(line.qty, 3)
      if (qty === null || (needsQty && qty <= 0n && !hasManual)) return refuse(`Line ${number} needs a quantity.`)
      if (qty > MAX_QTY_THOUSANDTHS) return refuse(`Line ${number} quantity is too large.`)
    }
    let rate: bigint | null = null
    if (line.rate.trim() || !hasManual) {
      rate = scaled(line.rate, 2)
      if (rate === null) return refuse(`Line ${number} needs a rate.`)
      if (rate > MAX_RATE_PAISE) return refuse(`Line ${number} rate is out of range.`)
    }
    const daysGiven = (line.days ?? '').trim() !== ''
    if (!unit && (daysGiven || (setup.basis === 'daily' && !hasManual))) {
      const days = scaled(line.days ?? '', 2)
      if (days === null || days <= 0n || days > MAX_DAYS_HUNDREDTHS) return refuse(`Line ${number} needs the number of days.`)
    }
    const auto = linePaise(line, setup, monthDays)
    const amount = typed ?? auto
    if (amount === null) return refuse(`Line ${number} needs a quantity and a rate.`)
    total += amount
    const skip = SKIP_KEYS.filter((key) => line.skip?.includes(key))
    for (const key of SKIP_KEYS) if (!skip.includes(key)) base[key] += amount
    const figure: BillLineFigure = {
      particulars: line.particulars.trim(),
      qty: qty === null ? null : line.qty.trim(),
      rate: rate === null ? null : toRupees(rate),
      amount: toRupees(amount),
    }
    if (!unit) figure.days = daysGiven ? (line.days ?? '').trim() : setup.basis === 'monthly' && rate !== null ? String(monthDays) : null
    if (setup.columns.length) figure.fields = Object.fromEntries(setup.columns.map((column, at) => [column.key, values[at]]))
    if (skip.length) figure.skip = skip
    if (typed !== null) {
      figure.manual = true
      figure.auto_amount = auto === null ? null : toRupees(auto)
    }
    rows.push(figure)
  }
  if (!rows.length) return refuse(unit ? 'Add at least one line with a quantity and a rate.' : 'Add at least one line with a rate and days.')
  if (rows.length > MAX_LINES) return refuse(`A bill can have at most ${MAX_LINES} lines.`)

  // Figures entered instead of calculated ones.
  const entered: Partial<Record<ManualKey, bigint>> = {}
  for (const key of Object.keys(MANUAL_NAMES) as ManualKey[]) {
    const text = manual[key] ?? ''
    if (!text.trim()) continue
    const value = scaled(text, 2)
    if (value === null || value > MAX_AMOUNT_PAISE) return refuse(`${MANUAL_NAMES[key]} amount must be a number.`)
    entered[key] = value
  }

  const epfAuto = pct(base.epf, rates.epf_pct)
  const esicAuto = pct(base.esic, rates.esic_pct)
  if (epfAuto === null || esicAuto === null) return refuse('Percentages must be numbers between 0 and 100.')
  const epf = entered.epf_amount ?? epfAuto
  const esic = entered.esic_amount ?? esicAuto
  // The service charge is of the lines that are part of it, and, if the bill says so, of the EPFO and ESIC as well (as they stand).
  const serviceBase = base.service + (setup.service_on === 'lines_epf_esic' ? epf + esic : 0n)
  const serviceAuto = pct(serviceBase, rates.service_pct)
  if (serviceAuto === null) return refuse('Percentages must be numbers between 0 and 100.')
  const service = entered.service_amount ?? serviceAuto
  const subTotal = total + epf + esic

  // Extra charges: a row with no name and no value is ignored, like a blank line.
  const extraFigures: ExtraFigure[] = []
  let extraTotal = 0n
  for (let index = 0; index < extras.length; index += 1) {
    const extra = extras[index]
    const label = extra.label.trim().replace(/\s+/g, ' ')
    if (!label && !extra.value.trim()) continue
    if (!label) return refuse(`Extra charge ${index + 1} needs a name.`)
    const value = scaled(extra.value || '0', 2)
    const limit = extra.kind === 'pct' ? 100n : 100_000_000n
    if (value === null || exceeds(extra.value || '0', limit)) {
      return refuse(`Extra charge '${label}' needs a number${extra.kind === 'pct' ? ' between 0 and 100' : ''}.`)
    }
    const amount = extra.kind === 'pct' ? halfUp(total * value, 10000n) : value
    extraTotal += amount
    extraFigures.push({ label: label.slice(0, 60), kind: extra.kind, value: toRupees(value), amount: toRupees(amount) })
  }
  if (extraFigures.length > MAX_EXTRA_CHARGES) return refuse(`A bill can have at most ${MAX_EXTRA_CHARGES} extra charges.`)
  const taxable = subTotal + service + extraTotal
  const cgstAuto = pct(taxable, rates.cgst_pct)
  const sgstAuto = pct(taxable, rates.sgst_pct)
  if (cgstAuto === null || sgstAuto === null) return refuse('Percentages must be numbers between 0 and 100.')
  const cgst = entered.cgst_amount ?? cgstAuto
  const sgst = entered.sgst_amount ?? sgstAuto
  const exact = taxable + cgst + sgst
  const grand = halfUp(exact, 100n) * 100n

  const auto: Record<ManualKey, bigint> = {
    epf_amount: epfAuto,
    esic_amount: esicAuto,
    service_amount: serviceAuto,
    cgst_amount: cgstAuto,
    sgst_amount: sgstAuto,
  }
  const manualFigures: BillFigures['manual_figures'] = {}
  for (const key of Object.keys(entered) as ManualKey[]) manualFigures[key] = { value: toRupees(entered[key] as bigint), auto: toRupees(auto[key]) }

  return {
    ok: true,
    figures: {
      lines: rows,
      lines_total: toRupees(total),
      epf_amount: toRupees(epf),
      esic_amount: toRupees(esic),
      sub_total: toRupees(subTotal),
      service_amount: toRupees(service),
      extra_charges: extraFigures,
      taxable_total: toRupees(taxable),
      cgst_amount: toRupees(cgst),
      sgst_amount: toRupees(sgst),
      round_off: toRupees(grand - exact),
      grand_total: toRupees(grand),
      manual_figures: manualFigures,
      auto: {
        epf_amount: toRupees(epfAuto),
        esic_amount: toRupees(esicAuto),
        service_amount: toRupees(serviceAuto),
        cgst_amount: toRupees(cgstAuto),
        sgst_amount: toRupees(sgstAuto),
      },
      bases: { epf: toRupees(base.epf), esic: toRupees(base.esic), service: toRupees(serviceBase) },
    },
  }
}

/** Indian digit grouping with two decimals: 9,19,149.00 */
export function money(value: number): string {
  return value.toLocaleString('en-IN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })
}

/** Financial year (April to March) a date falls in, named by the year it starts. */
export function fyStartYear(day: Date): number {
  return day.getMonth() >= 3 ? day.getFullYear() : day.getFullYear() - 1
}

/** What one line's quantity, rate and days come to, or null while a number it needs is not a valid number yet (an amount entered by hand is not counted). */
export function lineAmount(line: LineInput, setup: LineSetup = UNIT_SETUP, month = ''): number | null {
  const paise = linePaise(line, setup, monthDaysOf(setup, month))
  return paise === null ? null : toRupees(paise)
}
