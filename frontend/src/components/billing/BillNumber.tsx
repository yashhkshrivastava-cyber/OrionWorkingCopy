import { createPortal } from 'react-dom'
import { billByNumberPath, billPath, isBlankBill } from '../../billing/billLink'
import { useBillCard } from '../../billing/useBillCard'
import { useAuth } from '../../context/AuthContext'
import { useHoverPanel } from '../../hooks/useHoverPanel'
import { TabLink } from '../ui/TabLink'
import { BillCardView } from './BillCardView'

const WIDTH = 340

/**
 * A bill number, wherever one is shown. Point at it (or tab to it) and a card says everything about the bill; click it and the bill
 * opens in a new tab, so the screen you were on is still there.
 *
 * Give `number` (2026-27/202), or `code` (BILL-0012) when that is what the screen has. Somebody who may not see bills gets the plain
 * number: the card and the link would only answer "you may not".
 */
export function BillNumber({
  number,
  code,
  className = '',
  inherit = false,
  children,
}: {
  number?: string | null
  code?: string | null
  className?: string
  /** Keep the surrounding text colour (a chat bubble, which has a background of its own) instead of the accent. */
  inherit?: boolean
  children?: React.ReactNode
}) {
  const { user } = useAuth()
  const label = children ?? number ?? code ?? ''
  const allowed = Boolean(user?.can_billing) && (!isBlankBill(number) || Boolean(code))
  const target = code ? billPath(code) : number ? billByNumberPath(number) : ''
  const panel = useHoverPanel<HTMLAnchorElement>(WIDTH)
  const shown = useBillCard({ number, code }, allowed && panel.open)

  if (!allowed) return <span className={className}>{label}</span>

  return (
    <>
      <TabLink
        ref={panel.anchor}
        to={target}
        aria-describedby={panel.open ? panel.id : undefined}
        onMouseEnter={panel.show}
        onMouseLeave={panel.hide}
        onFocus={panel.show}
        onBlur={panel.hide}
        // Opening the bill must not also select or open the table row this number is in.
        onClick={(event) => {
          event.stopPropagation()
          panel.close()
        }}
        className={`rounded underline-offset-2 ${inherit ? 'underline hover:opacity-80' : 'text-accent hover:underline'} focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[color:var(--orion-accent)] ${className}`}
      >
        {label}
      </TabLink>
      {panel.open &&
        createPortal(
          <div
            ref={panel.panel}
            id={panel.id}
            role="tooltip"
            onMouseEnter={panel.show}
            onMouseLeave={panel.hide}
            style={{ position: 'fixed', left: panel.pos?.left ?? -9999, top: panel.pos?.top ?? 0, width: Math.min(WIDTH, window.innerWidth - 16), visibility: panel.pos ? 'visible' : 'hidden', maxHeight: panel.pos?.maxHeight }}
            className="tip-surface z-[100] overflow-y-auto rounded-xl border p-3.5 text-left"
          >
            {shown.state === 'ready' ? (
              <BillCardView card={shown.card} />
            ) : shown.state === 'missing' ? (
              <p className="text-xs text-[color:var(--color-text-muted)]">There is no bill {number ?? code}.</p>
            ) : shown.state === 'error' ? (
              <p className="text-xs text-negative">Could not load this bill: {shown.message}</p>
            ) : (
              <p className="text-xs text-[color:var(--color-text-muted)]" aria-live="polite">
                Loading bill {number ?? code}…
              </p>
            )}
          </div>,
          document.body,
        )}
    </>
  )
}
