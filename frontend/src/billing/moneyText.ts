/**
 * The text side of a money field, with no React in it so it can be checked on its own (`npm run check:money`): the Indian commas, reducing what was
 * typed or pasted to a plain number, and the amount in words.
 */
import { amountInWords } from './rupeeWords'

/** 1234567 -> "12,34,567": the Indian grouping (the last three digits, then twos). */
export function groupIndian(digits: string): string {
  const whole = digits.replace(/^0+(?=\d)/, '')
  if (whole.length <= 3) return whole
  return `${whole.slice(0, -3).replace(/\B(?=(\d{2})+(?!\d))/g, ',')},${whole.slice(-3)}`
}

/** What was typed or pasted, reduced to a plain number: digits, one point, at most `decimals` places, a minus only if allowed. No commas. */
export function cleanAmount(text: string, decimals: number, allowNegative: boolean): string {
  let s = text.replace(/[^\d.-]/g, '')
  const negative = allowNegative && s.startsWith('-')
  s = s.replace(/-/g, '')
  const dot = s.indexOf('.')
  let whole = dot === -1 ? s : s.slice(0, dot)
  const fraction = dot === -1 || decimals === 0 ? null : s.slice(dot + 1).replace(/\./g, '').slice(0, decimals)
  whole = whole.replace(/^0+(?=\d)/, '')
  if (whole === '' && fraction !== null) whole = '0'
  return `${negative ? '-' : ''}${whole}${fraction === null ? '' : `.${fraction}`}`
}

/** A plain number shown with its commas, however the person is part way through typing it ("1,234." stays "1,234."). */
export function showAmount(raw: string): string {
  const found = /^(-?)(\d*)(\.\d*)?$/.exec(raw)
  if (!found) return raw
  return `${found[1]}${groupIndian(found[2])}${found[3] ?? ''}`
}

/** The amount in words, or null when nothing (or nothing sensible) is typed. `scale` is what one unit typed is worth in rupees (100000 for a field in lakh). */
export function wordsOfAmount(raw: string, scale = 1): string | null {
  const found = /^(-?)(\d+)(?:\.(\d*))?$/.exec(raw)
  if (!found) return null
  const fraction = found[3] ?? ''
  const paise = (BigInt(found[2] + fraction) * BigInt(scale) * 100n) / 10n ** BigInt(fraction.length)
  const text = amountInWords(paise / 100n, Number(paise % 100n))
  return found[1] && paise > 0n ? `Minus ${text}` : text
}
