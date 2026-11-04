import { useId, useRef, type ReactNode } from 'react'
import { createPortal } from 'react-dom'
import { X } from 'lucide-react'
import { useDialog } from '../../hooks/useDialog'
import { usePresence } from '../../hooks/usePresence'

/**
 * A dialog. It arrives and leaves with a short fade and rise (not at all with reduced motion), keeps keyboard focus
 * inside while it is open, and gives focus back to what opened it when it closes.
 */
export function Modal({
  open,
  title,
  children,
  footer,
  onClose,
  size = 'md',
}: {
  open: boolean
  title: string
  children: ReactNode
  footer?: ReactNode
  onClose: () => void
  size?: 'md' | 'xl' | '2xl'
}) {
  const { present, leaving } = usePresence(open)
  const panel = useRef<HTMLDivElement>(null)
  const titleId = useId()
  useDialog(panel, open, onClose)

  if (!present) return null

  return createPortal(
    <div className="fixed inset-0 z-[80] flex items-end justify-center p-3 sm:items-center sm:p-6">
      <button
        type="button"
        tabIndex={-1}
        aria-label="Close dialog"
        className={`${leaving ? 'backdrop-out' : 'backdrop-in'} absolute inset-0 bg-scrim backdrop-blur-[3px]`}
        onClick={onClose}
      />
      <div
        ref={panel}
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        tabIndex={-1}
        className={`${leaving ? 'modal-out' : 'modal-in'} overlay relative z-10 flex w-full flex-col overflow-hidden rounded-2xl border border-[color:var(--color-border)] outline-none ${
          size === '2xl'
            ? 'max-h-[min(52rem,calc(100dvh-2rem))] max-w-6xl'
            : size === 'xl'
              ? 'max-h-[min(48rem,calc(100dvh-2rem))] max-w-3xl'
              : 'max-h-[min(36rem,calc(100dvh-2rem))] max-w-lg'
        }`}
      >
        <div className="flex items-start justify-between gap-3 border-b border-[color:var(--color-border)] px-5 py-4">
          <h2 id={titleId} className="t-h2">
            {title}
          </h2>
          <button
            type="button"
            onClick={onClose}
            className="interactive -mr-1 rounded-lg p-1.5 text-[color:var(--color-text-faint)] hover:bg-muted hover:text-[color:var(--color-text)]"
            aria-label="Close"
          >
            <X className="h-4 w-4" />
          </button>
        </div>
        <div className="min-h-0 flex-1 overflow-y-auto px-5 py-4">{children}</div>
        {footer && (
          <div className="flex flex-wrap justify-end gap-2 border-t border-[color:var(--color-border)] px-5 py-4">
            {footer}
          </div>
        )}
      </div>
    </div>,
    document.body,
  )
}
