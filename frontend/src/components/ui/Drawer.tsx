import { useId, useRef, type ReactNode } from 'react'
import { createPortal } from 'react-dom'
import { X } from 'lucide-react'
import { useDialog } from '../../hooks/useDialog'
import { usePresence } from '../../hooks/usePresence'

/**
 * A panel that slides in from the right over the page, for looking at one thing in depth without losing your place.
 * Escape, the backdrop and the close button all dismiss it. Focus stays inside it while it is open.
 */
export function Drawer({
  open,
  title,
  subtitle,
  badge,
  children,
  footer,
  onClose,
}: {
  open: boolean
  title: string
  subtitle?: ReactNode
  badge?: ReactNode
  children: ReactNode
  footer?: ReactNode
  onClose: () => void
}) {
  const { present, leaving } = usePresence(open)
  const panel = useRef<HTMLDivElement>(null)
  const titleId = useId()
  useDialog(panel, open, onClose)

  if (!present) return null

  return createPortal(
    <div className="fixed inset-0 z-[80]">
      <button
        type="button"
        tabIndex={-1}
        aria-label="Close panel"
        className={`${leaving ? 'backdrop-out' : 'backdrop-in'} absolute inset-0 bg-scrim backdrop-blur-[2px]`}
        onClick={onClose}
      />
      <div
        ref={panel}
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        tabIndex={-1}
        className={`${leaving ? 'drawer-right-out' : 'drawer-right-in'} absolute inset-y-0 right-0 flex w-[min(60rem,100vw)] flex-col border-l border-[color:var(--color-border)] bg-[color:var(--color-bg)] shadow-overlay outline-none`}
      >
        <header className="flex items-start justify-between gap-4 border-b border-[color:var(--color-border)] bg-surface px-5 py-4 sm:px-6">
          <div className="min-w-0">
            <div className="flex flex-wrap items-center gap-2.5">
              <h2 id={titleId} className="t-h2">
                {title}
              </h2>
              {badge}
            </div>
            {subtitle && <div className="t-small mt-1 text-[color:var(--color-text-muted)]">{subtitle}</div>}
          </div>
          <button
            type="button"
            onClick={onClose}
            aria-label="Close"
            className="interactive -mr-1 rounded-lg p-2 text-[color:var(--color-text-faint)] hover:bg-muted hover:text-[color:var(--color-text)]"
          >
            <X className="h-4 w-4" />
          </button>
        </header>
        <div className="min-h-0 flex-1 overflow-y-auto px-5 py-5 sm:px-6">{children}</div>
        {footer && (
          <footer className="flex flex-wrap items-center justify-end gap-2 border-t border-[color:var(--color-border)] bg-surface px-5 py-3 sm:px-6">
            {footer}
          </footer>
        )}
      </div>
    </div>,
    document.body,
  )
}
