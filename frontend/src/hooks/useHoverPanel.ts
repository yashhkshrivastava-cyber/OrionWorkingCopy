import { useCallback, useEffect, useId, useLayoutEffect, useRef, useState, type RefObject } from 'react'

const GAP = 8
const EDGE = 8

/**
 * Where a card that follows a trigger goes, and when it is open: on hover or keyboard focus after a short pause (so passing over a
 * column of numbers does not flash a card for each), kept open while the pointer is on the card itself, closed by Escape, a click
 * elsewhere, scrolling or resizing. The card sits below the trigger, or above when there is no room, and never runs off the window.
 * `HoverCard` does the same for a button; this one is for any trigger, such as a link.
 */
export function useHoverPanel<T extends HTMLElement>(width: number) {
  const id = useId()
  const [open, setOpen] = useState(false)
  const [pos, setPos] = useState<{ left: number; top: number; maxHeight: number } | null>(null)
  const anchor = useRef<T>(null)
  const panel = useRef<HTMLDivElement>(null)
  const timer = useRef<number>(undefined)

  const show = useCallback(() => {
    window.clearTimeout(timer.current)
    timer.current = window.setTimeout(() => setOpen(true), 220)
  }, [])
  const hide = useCallback(() => {
    window.clearTimeout(timer.current)
    timer.current = window.setTimeout(() => setOpen(false), 160)
  }, [])
  const close = useCallback(() => {
    window.clearTimeout(timer.current)
    setOpen(false)
  }, [])

  useEffect(() => () => window.clearTimeout(timer.current), [])

  useLayoutEffect(() => {
    const place = () => {
      if (!anchor.current || !panel.current) return
      const box = anchor.current.getBoundingClientRect()
      const height = panel.current.offsetHeight
      const wide = Math.min(width, window.innerWidth - EDGE * 2)
      let left = box.left + box.width / 2 - wide / 2
      left = Math.max(EDGE, Math.min(left, window.innerWidth - wide - EDGE))
      // Below the trigger if the card fits there, else above, else on whichever side has more room, and then it scrolls inside itself.
      const room = { below: window.innerHeight - box.bottom - GAP - EDGE, above: box.top - GAP - EDGE }
      const below = height <= room.below || (height > room.above && room.below >= room.above)
      const maxHeight = Math.max(120, below ? room.below : room.above)
      const shown = Math.min(height, maxHeight)
      setPos({ left, top: below ? box.bottom + GAP : box.top - GAP - shown, maxHeight })
    }
    if (!open || !panel.current) return
    place()
    // The card grows when what it shows arrives, so it is placed again each time it changes size.
    const watcher = new ResizeObserver(place)
    watcher.observe(panel.current)
    return () => watcher.disconnect()
  }, [open, width])

  useEffect(() => {
    if (!open) return
    const onKey = (event: KeyboardEvent) => {
      if (event.key === 'Escape') {
        setOpen(false)
        anchor.current?.focus()
      }
    }
    const onPointer = (event: PointerEvent) => {
      const target = event.target as Node
      if (!anchor.current?.contains(target) && !panel.current?.contains(target)) setOpen(false)
    }
    // Scrolling the page closes the card; scrolling inside the card (a long one) must not.
    const away = () => setOpen(false)
    const awayOnScroll = (event: Event) => {
      if (!panel.current?.contains(event.target as Node)) setOpen(false)
    }
    window.addEventListener('scroll', awayOnScroll, true)
    window.addEventListener('resize', away)
    document.addEventListener('keydown', onKey)
    document.addEventListener('pointerdown', onPointer)
    return () => {
      window.removeEventListener('scroll', awayOnScroll, true)
      window.removeEventListener('resize', away)
      document.removeEventListener('keydown', onKey)
      document.removeEventListener('pointerdown', onPointer)
    }
  }, [open])

  return { id, open, pos, anchor: anchor as RefObject<T>, panel, show, hide, close }
}
