/**
 * Open an address of this app in a new tab, leaving the screen the person is on exactly as it is.
 *
 * In a browser that is an ordinary new tab. In the native Orion window (the desktop shortcut) there are no tabs, and the window
 * library either sends a "new tab" to the system browser, where nobody is signed in, or loads it over the current screen, which is the
 * problem. So the native window offers a bridge (`desktop/orion_windows.py`) that opens a second Orion window sharing the same
 * sign-in, and that is used when it is there.
 */

declare global {
  interface Window {
    pywebview?: { api?: { open_window?: (path: string) => Promise<unknown> } }
  }
}

/** Only an address inside this app: a path from the root, never another site (`//host`) or a script. */
export function isAppPath(path: string): boolean {
  return path.startsWith('/') && !path.startsWith('//') && !path.includes('\\') && !/[\r\n]/.test(path)
}

function nativeBridge() {
  const open = window.pywebview?.api?.open_window
  return typeof open === 'function' ? open : null
}

/** True inside the native window, where a link cannot simply be left to open a tab. */
export const inNativeWindow = (): boolean => nativeBridge() !== null

export function openInNewTab(path: string): void {
  if (!isAppPath(path)) return
  const open = nativeBridge()
  if (open) {
    void window.pywebview?.api?.open_window?.(path)
    return
  }
  window.open(path, '_blank', 'noopener')
}
