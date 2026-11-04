import { useEffect, useState } from 'react'

/** How long the theme's "fast" motion lasts, in ms (0 when motion is reduced). */
function fastDuration(): number {
  const raw = getComputedStyle(document.documentElement).getPropertyValue('--orion-dur-fast').trim()
  const value = parseFloat(raw)
  if (Number.isNaN(value)) return 140
  return raw.endsWith('ms') ? value : value * 1000
}

/**
 * Lets something that appears and disappears (a dialog, a drawer, a menu) play its leaving animation before it is
 * removed. `present` is whether to render it; `leaving` is whether to give it the "out" classes. With reduced motion
 * the duration is 0, so it goes at once.
 */
export function usePresence(open: boolean): { present: boolean; leaving: boolean } {
  const [present, setPresent] = useState(open)

  useEffect(() => {
    if (open) {
      setPresent(true)
      return
    }
    const wait = fastDuration()
    if (wait <= 0) {
      setPresent(false)
      return
    }
    const timer = window.setTimeout(() => setPresent(false), wait + 20)
    return () => window.clearTimeout(timer)
  }, [open])

  return { present: open || present, leaving: !open && present }
}
