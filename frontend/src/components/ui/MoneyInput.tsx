import { useEffect, useId, useLayoutEffect, useRef, useState, type InputHTMLAttributes } from 'react'
import { cleanAmount, showAmount, wordsOfAmount } from '../../billing/moneyText'
import { Input } from './Field'

const same = (a: string, b: string) => (a === '' || b === '' ? a === b : Number(a) === Number(b))

/**
 * A field for money. What is typed shows with its Indian commas as it is typed (1,23,456.50), and under it the amount in words, kept up to date. The value
 * the page holds is the plain number (no commas), so a page that checks or sends "1250.75" does not change.
 *
 * `value` may be a string or a number. `scale` makes the words say what the amount really is when the field counts in something bigger than a rupee (100000 for
 * "₹ lakh"). `allowNegative` is for balances that can be an overdraft. `words={false}` leaves the words out where there is truly no room.
 */
export function MoneyInput({
  value,
  onChange,
  decimals = 2,
  scale = 1,
  allowNegative = false,
  words = true,
  className = '',
  ...rest
}: {
  value: string | number | null | undefined
  onChange: (raw: string) => void
  decimals?: number
  scale?: number
  allowNegative?: boolean
  words?: boolean
} & Omit<InputHTMLAttributes<HTMLInputElement>, 'value' | 'onChange' | 'type' | 'inputMode'>) {
  const external = value === null || value === undefined ? '' : String(value)
  const [text, setText] = useState(() => cleanAmount(external, decimals, allowNegative))
  const input = useRef<HTMLInputElement>(null)
  const caret = useRef<number | null>(null)
  const wordsId = useId()

  // Something other than typing changed the value (a total worked out, a form opened again): show it. "12." and 12 are the same number, so a point being typed is kept.
  useEffect(() => {
    setText((current) => (same(current, external) ? current : cleanAmount(external, decimals, allowNegative)))
  }, [external, decimals, allowNegative])

  const shown = showAmount(text)

  // Put the cursor back after the same digit it was after, once the commas have moved.
  useLayoutEffect(() => {
    const wanted = caret.current
    caret.current = null
    if (wanted === null || !input.current || document.activeElement !== input.current) return
    let position = shown.length
    if (wanted === 0) position = 0
    else {
      let seen = 0
      for (let index = 0; index < shown.length; index += 1) {
        if (/[\d.-]/.test(shown[index])) seen += 1
        if (seen === wanted) {
          position = index + 1
          break
        }
      }
    }
    input.current.setSelectionRange(position, position)
  }, [shown])

  const sentence = words ? wordsOfAmount(text, scale) : null

  /** What the field now holds as text (with its commas, wherever the cursor is in it): keep the plain number, and remember which digit the cursor follows. */
  const change = (display: string, cursor: number) => {
    const next = cleanAmount(display, decimals, allowNegative)
    const before = display.slice(0, cursor).replace(/[^\d.-]/g, '').length
    if (showAmount(next) !== display || shown !== display) caret.current = before
    setText(next)
    onChange(next)
  }

  return (
    <>
      <Input
        {...rest}
        ref={input}
        type="text"
        inputMode={decimals > 0 ? 'decimal' : 'numeric'}
        autoComplete="off"
        value={shown}
        aria-describedby={sentence ? wordsId : rest['aria-describedby']}
        className={`tabular-nums ${className}`}
        onChange={(event) => {
          const element = event.target
          change(element.value, element.selectionStart ?? element.value.length)
        }}
        onKeyDown={(event) => {
          rest.onKeyDown?.(event)
          const element = event.currentTarget
          const at = element.selectionStart ?? 0
          if (event.defaultPrevented || at !== element.selectionEnd) return
          // Backspace just after a comma (or Delete just before one) takes out the digit beside it, instead of doing nothing and throwing the cursor to the end.
          if (event.key === 'Backspace' && element.value[at - 1] === ',') {
            event.preventDefault()
            change(element.value.slice(0, at - 2) + element.value.slice(at), at - 2)
          } else if (event.key === 'Delete' && element.value[at] === ',') {
            event.preventDefault()
            change(element.value.slice(0, at) + element.value.slice(at + 2), at)
          }
        }}
      />
      {sentence && (
        <p id={wordsId} className="t-caption mt-1 break-words text-[color:var(--color-text-muted)]">
          {sentence}
        </p>
      )}
    </>
  )
}
