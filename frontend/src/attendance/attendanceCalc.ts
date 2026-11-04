/**
 * What a line of an attendance register comes to before anyone changes it: the days at the rate for a day, plus the extra, less the deduction, never below
 * nothing. The server (`attendance.calculated_amount`) is the authority; this is the live figure on the screen, and the two are checked against the same
 * figures (`backend/tests/attendance_vectors.json`, `npm run check:attendance`, `test_attendance.py`). Whole units are used throughout so that no rounding
 * of binary fractions can make the two disagree: the rate is kept to four decimals, the days to one, the money to paise.
 */

const units = (text: string | number | null | undefined, places: number): number => {
  const value = typeof text === 'number' ? text : Number(String(text ?? '').replace(/,/g, '').trim())
  return Number.isFinite(value) ? Math.round(value * 10 ** places) : 0
}

/** The amount for a line as text with two decimals ("12800.00"). Anything that is not a number counts as nothing. */
export function calculatedAmount(
  rate: string | number | null | undefined,
  days: string | number | null | undefined,
  extra: string | number | null | undefined,
  deduction: string | number | null | undefined,
): string {
  // rate (x10^4) times days (x10^1) is in x10^5; the extra and the deduction (x10^2) are brought to x10^5.
  const total = units(rate, 4) * units(days, 1) + (units(extra, 2) - units(deduction, 2)) * 1000
  const paise = total <= 0 ? 0 : Math.floor((total + 500) / 1000)
  const whole = Math.floor(paise / 100)
  return `${whole}.${String(paise % 100).padStart(2, '0')}`
}

/** "2026-10" -> "October 2026". */
export function monthName(month: string): string {
  const [year, number] = month.split('-').map(Number)
  if (!year || !number) return month
  return new Date(year, number - 1, 1).toLocaleDateString('en-IN', { month: 'long', year: 'numeric' })
}

/** The number of days in a "YYYY-MM" month. */
export function daysInMonth(month: string): number {
  const [year, number] = month.split('-').map(Number)
  return year && number ? new Date(year, number, 0).getDate() : 30
}

/** This month as "YYYY-MM", in the browser's calendar. */
export function thisMonth(): string {
  const now = new Date()
  return `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, '0')}`
}
