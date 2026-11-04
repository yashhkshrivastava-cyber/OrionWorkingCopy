import { useEffect, useLayoutEffect, useRef, useState, type ReactNode } from 'react'
import { createPortal } from 'react-dom'
import { Copy, CornerUpLeft, Forward, Pencil, Pin, PinOff, RotateCcw, Trash2, X } from 'lucide-react'
import type { ChatMessage } from '../../types'

export const QUICK_REACTIONS = ['👍', '❤️', '😂', '😮', '🙏', '✅']

export type MessageMenuTarget = { message: ChatMessage; x: number; y: number }

type Props = {
  target: MessageMenuTarget
  mine: boolean
  pinned: boolean
  onClose: () => void
  onReact: (emoji: string) => void
  onReply: () => void
  onCopy: () => void
  onForward: () => void
  onPin: () => void
  onEdit: () => void
  onDelete: () => void
  onRetry: () => void
  onDiscard: () => void
}

function Item({
  icon,
  children,
  onClick,
  danger = false,
}: {
  icon: ReactNode
  children: ReactNode
  onClick: () => void
  danger?: boolean
}) {
  return (
    <button
      type="button"
      role="menuitem"
      onClick={onClick}
      className={`interactive flex w-full items-center gap-2.5 rounded-lg px-2.5 py-2 text-left text-sm focus-visible:outline-2 focus-visible:outline-[color:var(--color-accent)] ${
        danger ? 'text-negative hover:bg-negative-dim' : 'text-[color:var(--color-text)] hover:bg-muted'
      }`}
    >
      <span className="shrink-0 opacity-75" aria-hidden="true">
        {icon}
      </span>
      {children}
    </button>
  )
}

/**
 * What can be done with one message, opened by right-click, long-press, the ⋯ button or the context-menu key. It lists
 * only what is allowed: you can edit and delete your own messages, a message that failed to send can be retried.
 */
export function MessageMenu({ target, mine, pinned, onClose, onReact, onReply, onCopy, onForward, onPin, onEdit, onDelete, onRetry, onDiscard }: Props) {
  const root = useRef<HTMLDivElement>(null)
  const [place, setPlace] = useState<{ left: number; top: number }>({ left: target.x, top: target.y })
  const [confirming, setConfirming] = useState(false)
  const { message } = target
  const failed = message.pending?.state === 'failed'
  const sending = message.pending?.state === 'sending'
  const deleted = Boolean(message.deleted)
  const canEdit = mine && !deleted && !message.pending && Boolean(message.body) && !message.forwarded
  const hasText = Boolean(message.body)

  useLayoutEffect(() => {
    const box = root.current?.getBoundingClientRect()
    if (!box) return
    const margin = 8
    const left = Math.min(Math.max(margin, target.x), window.innerWidth - box.width - margin)
    const top = target.y + box.height + margin > window.innerHeight ? Math.max(margin, target.y - box.height) : target.y
    setPlace({ left, top })
  }, [target.x, target.y])

  useEffect(() => {
    const first = root.current?.querySelector<HTMLElement>('[role="menuitem"], [data-quick]')
    first?.focus()
    const onKey = (event: KeyboardEvent) => {
      if (event.key === 'Escape') {
        event.preventDefault()
        onClose()
        return
      }
      if (event.key !== 'ArrowDown' && event.key !== 'ArrowUp') return
      const items = [...(root.current?.querySelectorAll<HTMLElement>('[role="menuitem"], [data-quick]') ?? [])]
      if (!items.length) return
      event.preventDefault()
      const at = items.indexOf(document.activeElement as HTMLElement)
      const step = event.key === 'ArrowDown' ? 1 : -1
      items[(at + step + items.length) % items.length].focus()
    }
    const onPointer = (event: PointerEvent) => {
      if (!root.current?.contains(event.target as Node)) onClose()
    }
    document.addEventListener('keydown', onKey)
    document.addEventListener('pointerdown', onPointer)
    window.addEventListener('blur', onClose)
    return () => {
      document.removeEventListener('keydown', onKey)
      document.removeEventListener('pointerdown', onPointer)
      window.removeEventListener('blur', onClose)
    }
  }, [onClose])

  const run = (action: () => void) => () => {
    onClose()
    action()
  }

  return createPortal(
    <div
      ref={root}
      role="menu"
      aria-label="Message actions"
      style={{ left: place.left, top: place.top }}
      className="overlay pop-in fixed z-[80] w-56 rounded-xl border border-[color:var(--color-border)] p-1.5 shadow-overlay"
    >
      {!deleted && !message.pending && (
        <div className="mb-1 flex items-center justify-between rounded-lg bg-muted px-1 py-0.5" role="group" aria-label="React">
          {QUICK_REACTIONS.map((emoji) => (
            <button
              key={emoji}
              type="button"
              data-quick
              onClick={run(() => onReact(emoji))}
              aria-label={`React with ${emoji}`}
              className="interactive rounded-md p-1 text-lg leading-none hover:scale-110 focus-visible:outline-2 focus-visible:outline-[color:var(--color-accent)]"
            >
              {emoji}
            </button>
          ))}
        </div>
      )}
      {failed && (
        <>
          <Item icon={<RotateCcw className="h-4 w-4" />} onClick={run(onRetry)}>
            Try sending again
          </Item>
          <Item icon={<X className="h-4 w-4" />} onClick={run(onDiscard)} danger>
            Discard this message
          </Item>
        </>
      )}
      {!failed && !sending && !deleted && (
        <>
          <Item icon={<CornerUpLeft className="h-4 w-4" />} onClick={run(onReply)}>
            Reply
          </Item>
          {hasText && (
            <Item icon={<Copy className="h-4 w-4" />} onClick={run(onCopy)}>
              Copy text
            </Item>
          )}
          <Item icon={<Forward className="h-4 w-4" />} onClick={run(onForward)}>
            Forward
          </Item>
          <Item icon={pinned ? <PinOff className="h-4 w-4" /> : <Pin className="h-4 w-4" />} onClick={run(onPin)}>
            {pinned ? 'Unpin' : 'Pin to this chat'}
          </Item>
          {canEdit && (
            <Item icon={<Pencil className="h-4 w-4" />} onClick={run(onEdit)}>
              Edit
            </Item>
          )}
          {mine &&
            (confirming ? (
              <Item icon={<Trash2 className="h-4 w-4" />} onClick={run(onDelete)} danger>
                Delete for both of you?
              </Item>
            ) : (
              <Item icon={<Trash2 className="h-4 w-4" />} onClick={() => setConfirming(true)} danger>
                Delete
              </Item>
            ))}
        </>
      )}
      {sending && <p className="px-2.5 py-2 text-xs text-[color:var(--color-text-muted)]">Sending…</p>}
      {deleted && <p className="px-2.5 py-2 text-xs text-[color:var(--color-text-muted)]">This message was deleted.</p>}
    </div>,
    document.body,
  )
}
