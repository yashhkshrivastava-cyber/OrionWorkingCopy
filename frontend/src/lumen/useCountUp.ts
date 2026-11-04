import { useEffect, useState } from 'react'

/** A number that counts up to its value when it first appears (and again when it changes), so a figure feels like it arrived. */
export function useCountUp(target: number, duration = 700): number {
  const [value, setValue] = useState(0)
  useEffect(() => {
    const root = document.documentElement
    if (root.dataset.motion === 'reduced' || window.matchMedia?.('(prefers-reduced-motion: reduce)').matches) {
      setValue(target)
      return
    }
    let frame = 0
    const start = performance.now()
    const tick = (now: number) => {
      const t = Math.min(1, (now - start) / duration)
      setValue(Math.round(target * (1 - Math.pow(1 - t, 3))))
      if (t < 1) frame = requestAnimationFrame(tick)
    }
    frame = requestAnimationFrame(tick)
    return () => cancelAnimationFrame(frame)
  }, [target, duration])
  return value
}
