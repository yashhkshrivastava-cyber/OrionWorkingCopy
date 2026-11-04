/** How the Bank screens write money and days. Indian digit grouping, always two decimals for an amount a person may check against a statement. */

const RUPEES = new Intl.NumberFormat('en-IN', { style: 'currency', currency: 'INR', minimumFractionDigits: 2, maximumFractionDigits: 2 })

/** ₹1,23,456.00 (and -₹1,234.50 for less than nothing). */
export const money = (value: number | null | undefined): string => (value === null || value === undefined ? '—' : RUPEES.format(value))

/** An amount as typed: a plain number of rupees and at most two paise. NaN when it is not one. */
export const amountOf = (text: string): number => (/^\d+(\.\d{1,2})?$/.test(text.trim()) ? Number(text.trim()) : Number.NaN)

const DAY = new Intl.DateTimeFormat('en-IN', { day: 'numeric', month: 'short', year: 'numeric' })
const MONTH = new Intl.DateTimeFormat('en-IN', { month: 'short', year: 'numeric' })

/** "12 Apr 2026" from 2026-04-12. A date is read as the day it names, not shifted by the time zone. */
export function day(iso: string | null | undefined): string {
  if (!iso) return '—'
  const [y, m, d] = iso.slice(0, 10).split('-').map(Number)
  return DAY.format(new Date(y, m - 1, d))
}

/** "Apr 2026" from 2026-04-01. */
export function month(iso: string): string {
  const [y, m] = iso.slice(0, 7).split('-').map(Number)
  return MONTH.format(new Date(y, m - 1, 1))
}

/** Today as YYYY-MM-DD in the person's own day. */
export function todayIso(): string {
  const now = new Date()
  return `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, '0')}-${String(now.getDate()).padStart(2, '0')}`
}

/** The day `count` days from today, as YYYY-MM-DD. */
export function daysFromToday(count: number): string {
  const when = new Date()
  when.setDate(when.getDate() + count)
  return `${when.getFullYear()}-${String(when.getMonth() + 1).padStart(2, '0')}-${String(when.getDate()).padStart(2, '0')}`
}
