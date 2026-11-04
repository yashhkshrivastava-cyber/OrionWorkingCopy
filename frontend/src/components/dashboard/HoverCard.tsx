import { useCallback, useEffect, useId, useLayoutEffect, useRef, useState, type ReactNode } from 'react'
import { createPortal } from 'react-dom'

const GAP = 8
const EDGE = 8

/**
 * A small explanatory card on a trigger. Opens on hover or keyboard focus, and
 * toggles on tap, so it works with a mouse, a keyboard and a touch screen.
 *
 * The card is drawn in a portal and positioned from the trigger's box, so it is
 * never clipped by a neighbouring card and never runs off the edge of the window.
 */
export function HoverCard({
  trigger,
  label,
  children,
  width = 300,
  className = '',
}: {
  /** What is shown in place: an icon, a badge, a number. */
  trigger: ReactNode
  /** Accessible name for the trigger button. */
  label: string
  children: ReactNode
  width?: number
  className?: string
}) {
  const id = useId()
  const [open, setOpen] = useState(false)
  const [pos, setPos] = useState<{ left: number; top: number } | null>(null)
  const button = useRef<HTMLButtonElement>(null)
  const panel = useRef<HTMLDivElement>(null)
  const timer = useRef<number>(undefined)

  const show = useCallback(() => {
    window.clearTimeout(timer.current)
    timer.current = window.setTimeout(() => setOpen(true), 120)
  }, [])
  const hide = useCallback(() => {
    window.clearTimeout(timer.current)
    timer.current = window.setTimeout(() => setOpen(false), 140)
  }, [])

  useEffect(() => () => window.clearTimeout(timer.current), [])

  useLayoutEffect(() => {
    if (!open || !button.current || !panel.current) return
    const anchor = button.current.getBoundingClientRect()
    const height = panel.current.offsetHeight
    const wide = Math.min(width, window.innerWidth - EDGE * 2)
    let left = anchor.left + anchor.width / 2 - wide / 2
    left = Math.max(EDGE, Math.min(left, window.innerWidth - wide - EDGE))
    let top = anchor.bottom + GAP
    if (top + height > window.innerHeight - EDGE && anchor.top - GAP - height > EDGE) {
      top = anchor.top - GAP - height
    }
    setPos({ left, top })
  }, [open, width, children])

  useEffect(() => {
    if (!open) return
    const close = () => setOpen(false)
    const onKey = (event: KeyboardEvent) => {
      if (event.key === 'Escape') {
        setOpen(false)
        button.current?.focus()
      }
    }
    const onPointer = (event: PointerEvent) => {
      const target = event.target as Node
      if (!button.current?.contains(target) && !panel.current?.contains(target)) setOpen(false)
    }
    window.addEventListener('scroll', close, true)
    window.addEventListener('resize', close)
    document.addEventListener('keydown', onKey)
    document.addEventListener('pointerdown', onPointer)
    return () => {
      window.removeEventListener('scroll', close, true)
      window.removeEventListener('resize', close)
      document.removeEventListener('keydown', onKey)
      document.removeEventListener('pointerdown', onPointer)
    }
  }, [open])

  return (
    <>
      <button
        ref={button}
        type="button"
        aria-label={label}
        aria-describedby={open ? id : undefined}
        aria-expanded={open}
        onMouseEnter={show}
        onMouseLeave={hide}
        onFocus={show}
        onBlur={hide}
        onClick={() => {
          window.clearTimeout(timer.current)
          setOpen((value) => !value)
        }}
        className={`cursor-help rounded focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[color:var(--orion-accent)] ${className}`}
      >
        {trigger}
      </button>
      {open &&
        createPortal(
          <div
            ref={panel}
            id={id}
            role="tooltip"
            onMouseEnter={show}
            onMouseLeave={hide}
            style={{
              position: 'fixed',
              left: pos?.left ?? -9999,
              top: pos?.top ?? 0,
              width: Math.min(width, window.innerWidth - EDGE * 2),
              visibility: pos ? 'visible' : 'hidden',
            }}
            className="tip-surface z-[100] rounded-xl border p-3.5 text-left text-xs leading-relaxed text-[color:var(--color-text-muted)]"
          >
            {children}
          </div>,
          document.body,
        )}
    </>
  )
}
