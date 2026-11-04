import type { ComponentProps, MouseEvent } from 'react'
import { inNativeWindow, isAppPath, openInNewTab } from '../../navigation/openInNewTab'

/**
 * A link that opens another screen of Orion in a new tab, so the screen you are on (its filters, its scroll, what you were
 * reading) is still there when you come back. It is a real link: it can be copied, middle-clicked or opened from the keyboard.
 * In the native window, which has no tabs, it opens a second window instead (navigation/openInNewTab.ts).
 */
export function TabLink({ to, onClick, children, ...rest }: { to: string } & Omit<ComponentProps<'a'>, 'href' | 'target' | 'rel'>) {
  const handle = (event: MouseEvent<HTMLAnchorElement>) => {
    onClick?.(event)
    if (event.defaultPrevented) return
    // A plain click in the native window; a click with a modifier key keeps whatever the person meant.
    if (inNativeWindow() && isAppPath(to) && !event.ctrlKey && !event.metaKey && !event.shiftKey && event.button === 0) {
      event.preventDefault()
      openInNewTab(to)
    }
  }
  return (
    <a href={to} target="_blank" rel="noopener noreferrer" onClick={handle} {...rest}>
      {children}
    </a>
  )
}
