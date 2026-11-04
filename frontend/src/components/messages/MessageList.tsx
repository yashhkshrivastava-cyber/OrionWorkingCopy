import { Fragment, useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from 'react'
import { ArrowDown, Loader2 } from 'lucide-react'
import type { ChatMessage, ChatPeer } from '../../types'
import { CallLine } from './CallLine'
import { SystemLine } from './SystemLine'
import { MessageBubble } from './MessageBubble'
import { continues, dayLabel, sameDay } from './format'

type Props = {
  messages: ChatMessage[]
  meId: number
  peer: ChatPeer | null
  peerRead: number
  /** The id the person had read up to when they opened this conversation. Messages after it are "new". */
  readMark: number
  hasMore: boolean
  loadingOlder: boolean
  reachesLatest: boolean
  loading: boolean
  pinnedIds: Set<number>
  typing: boolean
  /** In a group: the names of the people (by id) and who is typing. */
  group?: boolean
  names?: Map<number, string>
  typingLabel?: string
  /** Ask to scroll to a message and mark it; `nonce` makes asking for the same one twice work. */
  target: { id: number; nonce: number } | null
  onLoadOlder: () => void
  onJumpToLatest: () => void
  onAtBottom: (atBottom: boolean) => void
  onMenu: (message: ChatMessage, x: number, y: number) => void
  onReact: (message: ChatMessage, emoji: string) => void
  onReply: (message: ChatMessage) => void
  onJump: (messageId: number) => void
  onOpenMedia: (message: ChatMessage, localUrl?: string) => void
  onRetry: (messageId: number) => void
  onDiscard: (messageId: number) => void
  empty: React.ReactNode
}

const NEAR = 90
const FAR = 320

function Separator({ children }: { children: React.ReactNode }) {
  return (
    <div className="my-3 flex items-center gap-3 text-[11px] font-medium text-[color:var(--color-text-faint)]" role="separator">
      <span className="h-px flex-1 bg-[color:var(--color-border)]" />
      <span className="rounded-full bg-muted px-2.5 py-0.5">{children}</span>
      <span className="h-px flex-1 bg-[color:var(--color-border)]" />
    </div>
  )
}

function Skeleton() {
  const rows = [
    ['w-48', false],
    ['w-64', true],
    ['w-40', false],
    ['w-56', true],
    ['w-72', false],
  ] as const
  return (
    <div className="space-y-3 px-4 py-4" aria-busy="true" aria-label="Loading messages">
      {rows.map(([width, mine], index) => (
        <div key={index} className={`flex ${mine ? 'justify-end' : 'justify-start'}`}>
          <div className={`skeleton h-10 rounded-2xl ${width}`} />
        </div>
      ))}
    </div>
  )
}

/**
 * The messages of one conversation, with the scrolling done properly: it opens at the first new message (or the end), stays
 * put while you read older ones, offers a way back to the latest and a count of what arrived meanwhile, and keeps your place
 * when earlier messages load above.
 */
export function MessageList({
  messages,
  meId,
  peer,
  peerRead,
  readMark,
  hasMore,
  loadingOlder,
  reachesLatest,
  loading,
  pinnedIds,
  typing,
  group = false,
  names,
  typingLabel,
  target,
  onLoadOlder,
  onJumpToLatest,
  onAtBottom,
  onMenu,
  onReact,
  onReply,
  onJump,
  onOpenMedia,
  onRetry,
  onDiscard,
  empty,
}: Props) {
  const scroller = useRef<HTMLDivElement>(null)
  const opened = useRef(false)
  const lastId = useRef(0)
  const firstId = useRef(0)
  const heightBefore = useRef(0)
  const near = useRef(true)
  const [far, setFar] = useState(false)
  const [fresh, setFresh] = useState(0)
  const [flash, setFlash] = useState<number | null>(null)
  const peerName = group ? 'someone' : peer?.display_name || 'them'

  const unreadId = useMemo(
    () => messages.find((m) => m.id > 0 && m.id > readMark && m.sender_id !== meId && !m.deleted && !m.system)?.id ?? null,
    [messages, readMark, meId],
  )
  const unreadCount = useMemo(
    () => (unreadId ? messages.filter((m) => m.id >= unreadId && m.id > 0 && m.sender_id !== meId && !m.deleted && !m.system).length : 0),
    [messages, unreadId, meId],
  )

  const toBottom = useCallback((smooth: boolean) => {
    const el = scroller.current
    if (!el) return
    el.scrollTo({ top: el.scrollHeight, behavior: smooth ? 'smooth' : 'auto' })
  }, [])

  // Opening: land on the first unread message, otherwise on the newest.
  useLayoutEffect(() => {
    const el = scroller.current
    if (!el || opened.current || !messages.length) return
    opened.current = true
    if (unreadId) {
      const marker = el.querySelector<HTMLElement>('[data-unread-marker]')
      if (marker) {
        el.scrollTop = Math.max(0, marker.offsetTop - 12)
      } else toBottom(false)
    } else toBottom(false)
    lastId.current = messages[messages.length - 1].id
    firstId.current = messages[0].id
    near.current = el.scrollHeight - el.scrollTop - el.clientHeight < NEAR
    onAtBottom(near.current)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [messages.length > 0])

  // Something was added at the end, or loaded above.
  useLayoutEffect(() => {
    const el = scroller.current
    if (!el || !opened.current || !messages.length) return
    const newest = messages[messages.length - 1]
    const oldest = messages[0].id
    if (oldest < firstId.current && firstId.current > 0 && oldest > 0) {
      // Earlier messages arrived above: keep what the person was looking at where it was.
      el.scrollTop += el.scrollHeight - heightBefore.current
    }
    firstId.current = oldest > 0 ? oldest : firstId.current
    const grew = newest.id > lastId.current || (newest.id < 0 && newest.id !== lastId.current)
    if (grew) {
      const mine = newest.sender_id === meId
      if (mine || near.current) toBottom(true)
      else setFresh((n) => n + 1)
      lastId.current = newest.id
    }
    heightBefore.current = el.scrollHeight
  }, [messages, meId, toBottom])

  // Scrolling to a message that was asked for (a search result, a pinned message, a quoted reply).
  useEffect(() => {
    if (!target) return
    const el = scroller.current?.querySelector<HTMLElement>(`[data-message-id="${target.id}"]`)
    if (!el) return
    el.scrollIntoView({ block: 'center', behavior: 'smooth' })
    setFlash(target.id)
    const timer = window.setTimeout(() => setFlash(null), 1800)
    return () => window.clearTimeout(timer)
  }, [target, messages.length])

  const onScroll = () => {
    const el = scroller.current
    if (!el) return
    const distance = el.scrollHeight - el.scrollTop - el.clientHeight
    const isNear = distance < NEAR
    if (isNear !== near.current) {
      near.current = isNear
      onAtBottom(isNear)
    }
    if (isNear) setFresh(0)
    setFar(distance > FAR)
    if (el.scrollTop < 240 && hasMore && !loadingOlder) {
      heightBefore.current = el.scrollHeight
      onLoadOlder()
    }
  }

  // If the page is not tall enough to scroll, there is nothing to trigger loading older messages: load another page.
  useEffect(() => {
    const el = scroller.current
    if (el && opened.current && hasMore && !loadingOlder && el.scrollHeight <= el.clientHeight + 4) {
      heightBefore.current = el.scrollHeight
      onLoadOlder()
    }
  }, [messages.length, hasMore, loadingOlder, onLoadOlder])

  const now = new Date()
  const items = messages.map((message, index) => {
    const previous = messages[index - 1]
    const next = messages[index + 1]
    const day = !previous || !sameDay(new Date(previous.created_timestamp), new Date(message.created_timestamp))
    return (
      <Fragment key={message.id}>
        {day && <Separator>{dayLabel(message.created_timestamp, now)}</Separator>}
        {message.id === unreadId && (
          <div data-unread-marker className="my-3 flex items-center gap-3 text-[11px] font-semibold text-accent" role="separator">
            <span className="h-px flex-1 bg-[color:var(--color-accent)]/40" />
            <span>
              {unreadCount} new {unreadCount === 1 ? 'message' : 'messages'}
            </span>
            <span className="h-px flex-1 bg-[color:var(--color-accent)]/40" />
          </div>
        )}
        {message.system ? (
          <SystemLine message={message} />
        ) : message.call ? (
          <CallLine message={message} meId={meId} peerName={peerName} canCall={Boolean(peer) && !group} />
        ) : (
        <MessageBubble
          message={message}
          mine={message.sender_id === meId}
          meId={meId}
          peerRead={peerRead}
          runStart={day || !continues(previous, message)}
          runEnd={!continues(message, next)}
          pinned={pinnedIds.has(message.id)}
          flash={flash === message.id}
          peerName={peerName}
          group={group}
          names={names}
          onMenu={onMenu}
          onReact={onReact}
          onReply={onReply}
          onJump={onJump}
          onOpenMedia={onOpenMedia}
          onRetry={onRetry}
          onDiscard={onDiscard}
        />
        )}
      </Fragment>
    )
  })

  return (
    <div className="relative min-h-0 flex-1">
      <div
        ref={scroller}
        onScroll={onScroll}
        className="scroll-quiet absolute inset-0 overflow-y-auto overscroll-contain px-3 py-3 sm:px-5"
        role="log"
        aria-live="polite"
        aria-label="Messages"
      >
        {loadingOlder && (
          <div className="flex justify-center py-2 text-[color:var(--color-text-faint)]" aria-label="Loading earlier messages">
            <Loader2 className="h-4 w-4 animate-spin" />
          </div>
        )}
        {!hasMore && messages.length > 0 && (
          <p className="pb-2 pt-1 text-center text-[11px] text-[color:var(--color-text-faint)]">This is the start of the conversation</p>
        )}
        {loading && messages.length === 0 ? <Skeleton /> : messages.length === 0 ? empty : items}
        {typing && (
          <div className="mt-3 flex justify-start" aria-live="polite">
            <div className="flex items-center gap-1 rounded-2xl rounded-bl-md bg-muted px-3 py-2.5" role="status" aria-label={`${typingLabel || peerName} is typing`}>
              {[0, 1, 2].map((dot) => (
                <span
                  key={dot}
                  className="h-1.5 w-1.5 animate-pulse rounded-full bg-[color:var(--color-text-faint)]"
                  style={{ animationDelay: `${dot * 180}ms` }}
                />
              ))}
            </div>
          </div>
        )}
      </div>

      {(far || !reachesLatest || fresh > 0) && (
        <button
          type="button"
          onClick={() => {
            if (!reachesLatest) onJumpToLatest()
            else toBottom(true)
            setFresh(0)
          }}
          className="interactive pop-in absolute bottom-3 right-4 flex items-center gap-1.5 rounded-full border border-[color:var(--color-border)] bg-surface px-3 py-2 text-xs font-medium text-[color:var(--color-text)] shadow-overlay hover:bg-muted"
        >
          <ArrowDown className="h-4 w-4 text-accent" aria-hidden="true" />
          {fresh > 0 ? `${fresh} new ${fresh === 1 ? 'message' : 'messages'}` : 'Latest messages'}
        </button>
      )}
    </div>
  )
}
