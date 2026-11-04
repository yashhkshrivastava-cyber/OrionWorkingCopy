import { useEffect, useState, type ReactNode } from 'react'
import { createPortal } from 'react-dom'
import { api } from '../../api/client'
import type { LetterheadDesign } from '../../types'

const mm = (value: number) => `${value}mm`

// The letterhead is the same for everyone and changes rarely, so one copy is shared by every page that draws it.
let shared: LetterheadDesign | null = null
const listeners = new Set<(design: LetterheadDesign) => void>()

/** Replaces the shared letterhead, for the page that just changed it. */
export function setLetterheadDesign(design: LetterheadDesign) {
  shared = design
  listeners.forEach((listener) => listener(design))
}

/** The company letterhead: where its two strips sit and where their images are. */
export function useLetterheadDesign() {
  const [design, setDesign] = useState<LetterheadDesign | null>(shared)
  const [error, setError] = useState('')

  useEffect(() => {
    listeners.add(setDesign)
    // Asked again on every mount, so a letterhead someone else changed is picked up.
    api
      .letterheadDesign()
      .then(setLetterheadDesign)
      .catch((e: Error) => setError(e.message))
    return () => {
      listeners.delete(setDesign)
    }
  }, [])

  return { design, error }
}

function stripStyle(design: LetterheadDesign, part: 'header' | 'footer') {
  const { settings, layout } = design
  return part === 'header'
    ? { top: mm(settings.header_top_mm), left: mm(settings.side_mm), width: mm(layout.strip_width_mm), height: mm(layout.header_height_mm) }
    : { bottom: mm(settings.footer_bottom_mm), left: mm(settings.side_mm), width: mm(layout.strip_width_mm), height: mm(layout.footer_height_mm) }
}

/**
 * An A4 page carrying the letterhead, on screen. Whatever is inside sits where the text will print.
 * A strip that will not be printed (for paper that already has the letterhead) is shown faintly, so the room
 * it keeps is still visible.
 */
export function LetterheadSheet({
  design,
  showHeader = true,
  showFooter = true,
  children,
  className = '',
}: {
  design: LetterheadDesign
  showHeader?: boolean
  showFooter?: boolean
  children?: ReactNode
  className?: string
}) {
  const { settings, layout, page } = design
  return (
    <div
      className={`relative mx-auto shrink-0 bg-white shadow-[0_8px_30px_rgba(15,23,42,0.12)] ${className}`}
      style={{
        width: mm(page.width_mm),
        minHeight: mm(page.height_mm),
        paddingTop: mm(layout.top_space_mm),
        paddingBottom: mm(layout.bottom_space_mm),
        paddingLeft: mm(settings.body_left_mm),
        paddingRight: mm(settings.body_right_mm),
      }}
    >
      {(['header', 'footer'] as const).map((part) => {
        const printed = part === 'header' ? showHeader : showFooter
        return (
          <img
            key={part}
            src={design[part].url}
            alt=""
            draggable={false}
            className={`pointer-events-none absolute select-none ${printed ? '' : 'opacity-15 grayscale'}`}
            style={stripStyle(design, part)}
          />
        )
      })}
      {children}
    </div>
  )
}

/**
 * Prints its children on the letterhead and then calls `onDone`. Mount it only while printing.
 *
 * The strips are fixed, which a browser repeats on every printed page, and the text sits in a table whose
 * header and footer rows are empty spacers of the strips' height, which are also repeated, so text on any
 * page stays clear of both. The page margin is set to zero for the print and put back after.
 */
export function LetterheadPrint({
  design,
  title,
  showHeader = true,
  showFooter = true,
  children,
  onDone,
}: {
  design: LetterheadDesign
  /** The name offered when the print is saved as a PDF. */
  title: string
  showHeader?: boolean
  showFooter?: boolean
  children: ReactNode
  onDone: () => void
}) {
  const [host] = useState(() => {
    const element = document.createElement('div')
    element.className = 'lh-print-root'
    return element
  })

  useEffect(() => {
    document.body.appendChild(host)
    document.body.classList.add('lh-printing')
    const pageRule = document.createElement('style')
    pageRule.textContent = '@page { size: A4; margin: 0; }'
    document.head.appendChild(pageRule)
    const previousTitle = document.title
    document.title = title

    let finished = false
    let fallback = 0
    const finish = () => {
      if (finished) return
      finished = true
      window.clearTimeout(fallback)
      window.removeEventListener('afterprint', finish)
      onDone()
    }

    // Print once the strips are ready to draw, or after two seconds if one cannot be.
    const images = Array.from(host.querySelectorAll('img'))
    const ready = Promise.all(images.map((image) => image.decode().catch(() => undefined)))
    const timeout = new Promise((resolve) => window.setTimeout(resolve, 2000))
    Promise.race([ready, timeout]).then(() => {
      if (finished) return
      window.addEventListener('afterprint', finish)
      // If the browser never reports the print as over, clear up anyway so later prints are not affected.
      fallback = window.setTimeout(finish, 10 * 60 * 1000)
      window.print()
    })

    return () => {
      finished = true
      window.clearTimeout(fallback)
      window.removeEventListener('afterprint', finish)
      document.title = previousTitle
      pageRule.remove()
      document.body.classList.remove('lh-printing')
      host.remove()
    }
    // The job is fixed for the life of this component: it is mounted to print once.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [host])

  const { settings, layout } = design
  return createPortal(
    <>
      {showHeader && <img className="lh-print-strip" src={design.header.url} alt="" style={stripStyle(design, 'header')} />}
      {showFooter && <img className="lh-print-strip" src={design.footer.url} alt="" style={stripStyle(design, 'footer')} />}
      <table className="lh-print-table">
        <thead>
          <tr>
            <td>
              <div style={{ height: mm(layout.top_space_mm) }} />
            </td>
          </tr>
        </thead>
        <tfoot>
          <tr>
            <td>
              <div style={{ height: mm(layout.bottom_space_mm) }} />
            </td>
          </tr>
        </tfoot>
        <tbody>
          <tr>
            <td style={{ paddingLeft: mm(settings.body_left_mm), paddingRight: mm(settings.body_right_mm) }}>{children}</td>
          </tr>
        </tbody>
      </table>
    </>,
    host,
  )
}
