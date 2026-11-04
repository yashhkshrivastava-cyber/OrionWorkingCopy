import { useEffect, useRef, type RefObject } from 'react'

const FOCUSABLE =
  'a[href], button:not([disabled]), input:not([disabled]):not([type="hidden"]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])'

/**
 * What a modal dialog or drawer owes the keyboard and a screen reader: the page behind it does not scroll, Escape
 * closes it, focus moves into it and stays inside it while Tab is pressed, and goes back to where it was when it
 * closes. `active` is whether it is on screen.
 */
export function useDialog(panel: RefObject<HTMLElement | null>, active: boolean, onClose: () => void) {
  const close = useRef(onClose)
  close.current = onClose

  useEffect(() => {
    if (!active) return
    const returnTo = document.activeElement as HTMLElement | null
    const previousOverflow = document.body.style.overflow
    document.body.style.overflow = 'hidden'

    const node = panel.current
    // Focus the first field or button inside, unless something already took focus there (an autoFocus input).
    if (node && !node.contains(document.activeElement)) {
      const first = node.querySelector<HTMLElement>('[data-autofocus], input:not([type="hidden"]), select, textarea')
      ;(first ?? node).focus({ preventScroll: true })
    }

    const onKey = (event: KeyboardEvent) => {
      if (event.key === 'Escape') {
        close.current()
        return
      }
      if (event.key !== 'Tab' || !panel.current) return
      const items = [...panel.current.querySelectorAll<HTMLElement>(FOCUSABLE)].filter((el) => el.offsetParent !== null || el === document.activeElement)
      if (items.length === 0) {
        event.preventDefault()
        return
      }
      const first = items[0]
      const last = items[items.length - 1]
      if (event.shiftKey && (document.activeElement === first || document.activeElement === panel.current)) {
        event.preventDefault()
        last.focus()
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault()
        first.focus()
      }
    }
    document.addEventListener('keydown', onKey)
    return () => {
      document.removeEventListener('keydown', onKey)
      document.body.style.overflow = previousOverflow
      if (returnTo && document.contains(returnTo)) returnTo.focus({ preventScroll: true })
    }
  }, [active, panel])
}
