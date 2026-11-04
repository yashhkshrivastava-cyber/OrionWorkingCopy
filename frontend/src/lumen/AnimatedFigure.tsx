import { useCountUp } from './useCountUp'

/**
 * A figure as text ("₹1.92 Cr", "13.5%", "130") whose number counts up when it arrives, keeping everything around the number as it was
 * (the rupee sign, the unit, the commas, the decimals). Screen readers get the final text at once.
 */
export function AnimatedFigure({ text }: { text: string }) {
  const found = /-?\d[\d,]*(\.\d+)?/.exec(text)
  const target = found ? Number(found[0].replace(/,/g, '')) : Number.NaN
  const decimals = found?.[1] ? found[1].length - 1 : 0
  const scale = 10 ** decimals
  const counted = useCountUp(Number.isFinite(target) ? Math.round(target * scale) : 0)
  if (!found || !Number.isFinite(target)) return <>{text}</>
  const shown = counted / scale
  const body = found[0].includes(',')
    ? shown.toLocaleString('en-IN', { minimumFractionDigits: decimals, maximumFractionDigits: decimals })
    : shown.toFixed(decimals)
  return (
    <>
      <span className="sr-only">{text}</span>
      <span aria-hidden="true">
        {text.slice(0, found.index)}
        {body}
        {text.slice(found.index + found[0].length)}
      </span>
    </>
  )
}
