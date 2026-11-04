import { useCallback, useState } from 'react'

const KEY = 'orion_bills_on_letterhead'

function stored(): boolean {
  try {
    return window.localStorage.getItem(KEY) === '1'
  } catch {
    return false
  }
}

/**
 * Whether this person prints bills and statements on the company letterhead. Remembered in this browser, so
 * the choice made on one bill is still set on the next. It only changes how a PDF is drawn, never the bill.
 */
export function useLetterheadChoice(): [boolean, (next: boolean) => void] {
  const [on, setOn] = useState(stored)
  const choose = useCallback((next: boolean) => {
    setOn(next)
    try {
      window.localStorage.setItem(KEY, next ? '1' : '0')
    } catch {
      /* private browsing: the choice lasts for this page only */
    }
  }, [])
  return [on, choose]
}

/** The PDF address for a bill or statement, on the letterhead when asked. `path` is the one under /billing. */
export function pdfPath(path: string, onLetterhead: boolean): string {
  return onLetterhead ? `${path}?letterhead=true` : path
}
