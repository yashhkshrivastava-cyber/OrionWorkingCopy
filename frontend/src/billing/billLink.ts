/** Where a bill is, and how to spot a bill number in text. */

/** The bill's own page. `code` is the bill's code (BILL-0012), not the number printed on it. */
export const billPath = (code: string): string => `/utility/billing/${encodeURIComponent(code)}`

/**
 * An address that finds a bill by the number printed on it (2026-27/202) and then shows it. Used where only the number is known:
 * a dashboard table, an answer from the Copilot. It is an ordinary address, so it can be opened in a new tab before anything has
 * been looked up.
 */
export const billByNumberPath = (number: string): string => `/utility/billing/find?number=${encodeURIComponent(number)}`

/** What a table shows for "no value" (a dash, nothing): not a bill number, so not a link. */
export const isBlankBill = (value: string | null | undefined): boolean => !value || /^[\s–—-]*$/.test(value)

/** Financial year, a slash and a sequence: 2026-27/202. The number of a bill is never reused, so this names one bill for ever. */
export const BILL_NUMBER = /\b(\d{4}-\d{2}\/\d{1,7})\b/g

/**
 * Which of a record table's columns holds a bill: the number printed on the bill (`bill_number`) or the bill's own code (`bill_code`,
 * on a revenue entry). The generic tables are told nothing about their columns but the names, so the names are what decides.
 */
export function billColumn(column: string): 'number' | 'code' | null {
  if (column === 'bill_number' || column === 'bill_no') return 'number'
  if (column === 'bill_code') return 'code'
  return null
}

/** Text cut into plain pieces and bill numbers, in order, so a sentence can show each number as a link. */
export function splitBillNumbers(text: string): { text: string; bill: boolean }[] {
  const pieces: { text: string; bill: boolean }[] = []
  let last = 0
  for (const match of text.matchAll(BILL_NUMBER)) {
    const at = match.index ?? 0
    // 2026-27/Q1 or a date like 2026-27/10/05 is not a bill number: the number must end there.
    const after = text[at + match[0].length]
    if (after === '/' || (after !== undefined && /[\d-]/.test(after))) continue
    if (at > last) pieces.push({ text: text.slice(last, at), bill: false })
    pieces.push({ text: match[0], bill: true })
    last = at + match[0].length
  }
  if (last < text.length) pieces.push({ text: text.slice(last), bill: false })
  return pieces
}
