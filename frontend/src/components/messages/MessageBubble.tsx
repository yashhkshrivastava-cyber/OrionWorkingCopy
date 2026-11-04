import { memo, useEffect, useMemo, useRef, type KeyboardEvent, type MouseEvent, type PointerEvent } from 'react'
import { AlertCircle, Check, CheckCheck, Clock, CornerUpLeft, Download, FileText, Forward, MoreHorizontal, Pencil, Play } from 'lucide-react'
import type { ChatMessage } from '../../types'
import { clock, fileSize, fullTime, linkify, senderTone } from './format'
import { splitBillNumbers } from '../../billing/billLink'
import { BillNumber } from '../billing/BillNumber'
import { VoiceNote } from './VoiceNote'

type Props = {
  message: ChatMessage
  mine: boolean
  /** Where the person's own messages have been read up to by the other person. */
  peerRead: number
  runStart: boolean
  runEnd: boolean
  pinned: boolean
  flash: boolean
  /** The other person's name, for "replying to". */
  peerName: string
  /** In a group: who said what is shown above each run of messages. */
  group?: boolean
  names?: Map<number, string>
  onMenu: (message: ChatMessage, x: number, y: number) => void
  onReact: (message: ChatMessage, emoji: string) => void
  onReply: (message: ChatMessage) => void
  onJump: (messageId: number) => void
  onOpenMedia: (message: ChatMessage, localUrl?: string) => void
  onRetry: (messageId: number) => void
  onDiscard: (messageId: number) => void
  meId: number
}

const QUICK = ['👍', '❤️', '😂', '😮', '🙏']

const EMOJI_ONLY = /^(?:\p{Extended_Pictographic}[️‍]*|\s)+$/u

function Ticks({ message, peerRead }: { message: ChatMessage; peerRead: number }) {
  if (message.pending?.state === 'sending') return <Clock className="h-3 w-3" aria-label="Sending" />
  if (message.pending?.state === 'failed') return <AlertCircle className="h-3 w-3" aria-label="Not sent" />
  if (message.id <= peerRead) return <CheckCheck className="h-3.5 w-3.5 text-[color:var(--color-on-primary)]" aria-label="Read" />
  return <Check className="h-3.5 w-3.5 opacity-80" aria-label="Sent" />
}

/**
 * One message. It shows what was said, what it replies to, any file, its reactions and (for your own) whether it was
 * sent and read. Right-click, long-press or the ⋯ button open the menu; the context-menu key does too.
 */
function Bubble({
  message,
  mine,
  peerRead,
  runStart,
  runEnd,
  pinned,
  flash,
  peerName,
  group = false,
  names,
  meId,
  onMenu,
  onReact,
  onReply,
  onJump,
  onOpenMedia,
  onRetry,
  onDiscard,
}: Props) {
  const press = useRef<number | null>(null)
  const pending = message.pending
  const deleted = Boolean(message.deleted)
  const failed = pending?.state === 'failed'
  const localFile = pending?.file ?? null
  const localUrl = useMemo(() => (localFile && localFile.type.startsWith('image/') ? URL.createObjectURL(localFile) : undefined), [localFile])
  useEffect(() => () => (localUrl ? URL.revokeObjectURL(localUrl) : undefined), [localUrl])
  // A voice note that is still being sent can already be played from the recording.
  const localAudio = useMemo(() => (localFile && localFile.type.startsWith('audio/') ? URL.createObjectURL(localFile) : undefined), [localFile])
  useEffect(() => () => (localAudio ? URL.revokeObjectURL(localAudio) : undefined), [localAudio])
  const pieces = useMemo(() => linkify(message.body), [message.body])
  const big = Boolean(message.body) && message.body.length <= 12 && EMOJI_ONLY.test(message.body) && !message.media_kind && !message.reply_to

  const senderName = names?.get(message.sender_id) ?? message.sender_name ?? peerName
  const openAt = (x: number, y: number) => onMenu(message, x, y)
  const openFromButton = (event: MouseEvent<HTMLButtonElement>) => {
    const box = event.currentTarget.getBoundingClientRect()
    openAt(mine ? box.left - 170 : box.left, box.bottom + 4)
  }

  const onPointerDown = (event: PointerEvent) => {
    if (event.pointerType !== 'touch') return
    press.current = window.setTimeout(() => {
      press.current = null
      openAt(event.clientX, event.clientY)
    }, 480)
  }
  const cancelPress = () => {
    if (press.current) window.clearTimeout(press.current)
    press.current = null
  }
  const onKeyDown = (event: KeyboardEvent<HTMLDivElement>) => {
    if (event.target !== event.currentTarget) return
    if (event.key === 'ContextMenu' || (event.shiftKey && event.key === 'F10')) {
      event.preventDefault()
      const box = event.currentTarget.getBoundingClientRect()
      openAt(box.left + 24, box.bottom - 8)
    }
  }

  const radius = mine
    ? `rounded-2xl ${runStart ? '' : 'rounded-tr-md'} ${runEnd ? '' : 'rounded-br-md'}`
    : `rounded-2xl ${runStart ? '' : 'rounded-tl-md'} ${runEnd ? '' : 'rounded-bl-md'}`
  const tone = deleted
    ? 'border border-dashed border-[color:var(--color-border-strong)] bg-transparent text-[color:var(--color-text-faint)]'
    : failed
      ? 'border border-negative/50 bg-negative-dim text-[color:var(--color-text)]'
      : mine
        ? 'bg-primary text-on-primary'
        : 'bg-muted text-[color:var(--color-text)]'
  const subtle = mine && !deleted && !failed ? 'text-on-primary/75' : 'text-[color:var(--color-text-faint)]'
  const mediaUrl = message.media_url || undefined

  return (
    <div
      className={`group relative flex ${mine ? 'justify-end' : 'justify-start'} ${runStart ? 'mt-3' : 'mt-0.5'} ${message.pending ? 'opacity-90' : ''}`}
      data-message-id={message.id}
    >
      {!deleted && !pending && (
        <div
          className={`chat-hover-bar mt-1 flex shrink-0 items-center gap-0.5 self-start rounded-full border border-[color:var(--color-border)] bg-surface p-1 opacity-0 shadow-card transition-opacity focus-within:opacity-100 group-hover:opacity-100 max-md:hidden ${
            mine ? 'order-first mr-1.5' : 'order-last ml-1.5'
          }`}
        >
          {QUICK.map((emoji) => (
            <button
              key={emoji}
              type="button"
              onClick={() => onReact(message, emoji)}
              aria-label={`React with ${emoji}`}
              className="interactive rounded-full px-1.5 py-1 text-base leading-none transition-transform hover:scale-125 hover:bg-muted"
            >
              {emoji}
            </button>
          ))}
          <span className="mx-0.5 h-5 w-px bg-[color:var(--color-border)]" aria-hidden="true" />
          <button
            type="button"
            onClick={() => onReply(message)}
            aria-label="Reply"
            title="Reply"
            className="interactive rounded-full p-1.5 text-[color:var(--color-text-muted)] hover:bg-muted hover:text-[color:var(--color-text)]"
          >
            <CornerUpLeft className="h-4 w-4" />
          </button>
          <button
            type="button"
            onClick={openFromButton}
            aria-label="More actions"
            title="More"
            aria-haspopup="menu"
            className="interactive rounded-full p-1.5 text-[color:var(--color-text-muted)] hover:bg-muted hover:text-[color:var(--color-text)]"
          >
            <MoreHorizontal className="h-4 w-4" />
          </button>
        </div>
      )}

      <div className={`flex min-w-0 max-w-[82%] flex-col md:max-w-[38rem] ${mine ? 'items-end' : 'items-start'}`}>
        {group && !mine && runStart && !deleted && <span className={`mb-0.5 px-1 text-xs font-bold ${senderTone(message.sender_id)}`}>{senderName}</span>}
        <div
          role="group"
          tabIndex={0}
          aria-label={`${mine ? 'You' : senderName}, ${fullTime(message.created_timestamp)}${deleted ? ', deleted' : ''}`}
          onContextMenu={(event) => {
            event.preventDefault()
            openAt(event.clientX, event.clientY)
          }}
          onPointerDown={onPointerDown}
          onPointerUp={cancelPress}
          onPointerLeave={cancelPress}
          onPointerCancel={cancelPress}
          onPointerMove={cancelPress}
          onKeyDown={onKeyDown}
          title={fullTime(message.created_timestamp)}
          className={`chat-bubble ${mine && !deleted && !failed ? 'chat-bubble-mine' : ''} relative min-w-0 max-w-full select-text overflow-hidden px-4 py-2.5 text-[15px] leading-[1.45] shadow-[0_1px_1px_rgba(0,0,0,0.04)] outline-none focus-visible:ring-2 focus-visible:ring-[color:var(--color-accent)] ${radius} ${tone} ${
            flash ? 'ring-2 ring-[color:var(--color-accent)] ring-offset-2 ring-offset-[color:var(--color-bg)]' : ''
          }`}
        >
          {pinned && !deleted && (
            <p className={`mb-0.5 text-[10px] font-medium uppercase tracking-wide ${subtle}`}>Pinned</p>
          )}
          {message.forwarded && !deleted && (
            <p className={`mb-1 flex items-center gap-1 text-[11px] italic ${subtle}`}>
              <Forward className="h-3 w-3" aria-hidden="true" />
              Forwarded
            </p>
          )}
          {message.reply_to && !deleted && (
            <button
              type="button"
              onClick={() => message.reply_to && onJump(message.reply_to.id)}
              className={`mb-1.5 block w-full min-w-0 rounded-lg border-l-[3px] px-2 py-1 text-left text-xs ${
                mine ? 'border-on-primary/70 bg-on-primary/15' : 'border-[color:var(--color-accent)] bg-[color:var(--color-text)]/[0.06]'
              }`}
            >
              <span className={`block truncate font-semibold ${mine ? 'text-on-primary' : 'text-accent'}`}>
                {message.reply_to.sender_id === meId ? 'You' : (message.reply_to.sender_id !== null && names?.get(message.reply_to.sender_id)) || peerName}
              </span>
              <span className={`block truncate ${message.reply_to.deleted ? 'italic' : ''} ${mine ? 'text-on-primary/85' : 'text-[color:var(--color-text-muted)]'}`}>
                {message.reply_to.deleted
                  ? 'Message deleted'
                  : message.reply_to.body ||
                    (message.reply_to.media_kind === 'image' ? 'Photo' : message.reply_to.media_kind === 'video' ? 'Video' : message.reply_to.media_kind === 'audio' ? 'Voice note' : message.reply_to.media_name || 'File')}
              </span>
            </button>
          )}

          {deleted ? (
            <p className="italic">This message was deleted</p>
          ) : (
            <>
              {message.media_kind === 'image' && (mediaUrl || localUrl) && (
                <button type="button" onClick={() => onOpenMedia(message, localUrl)} className="mb-1 block max-w-full overflow-hidden rounded-xl" aria-label={`Open photo ${message.media_name ?? ''}`}>
                  <img src={localUrl || mediaUrl} alt={message.media_name || 'Photo'} loading="lazy" className="max-h-72 max-w-full cursor-zoom-in rounded-xl object-cover" />
                </button>
              )}
              {message.media_kind === 'video' && mediaUrl && (
                <div className="relative mb-1">
                  <video src={mediaUrl} controls preload="metadata" className="max-h-72 w-full rounded-xl bg-black" />
                  <Play className="pointer-events-none absolute left-2 top-2 h-4 w-4 text-white/80" aria-hidden="true" />
                </div>
              )}
              {message.media_kind === 'video' && !mediaUrl && (
                <div className={`mb-1 flex items-center gap-2 rounded-lg px-2 py-2 text-xs ${mine ? 'bg-on-primary/15' : 'bg-[color:var(--color-text)]/10'}`}>
                  <Play className="h-4 w-4" aria-hidden="true" />
                  <span className="truncate">{message.media_name || 'Video'}</span>
                </div>
              )}
              {message.media_kind === 'audio' && (
                <VoiceNote
                  url={mediaUrl || localAudio}
                  durationMs={message.media_duration_ms}
                  waveform={message.media_waveform}
                  mine={mine && !failed}
                  label={`Voice note from ${mine ? 'you' : peerName}`}
                />
              )}
              {message.media_kind === 'file' && (
                <a
                  href={mediaUrl}
                  download={message.media_name || undefined}
                  onClick={(event) => !mediaUrl && event.preventDefault()}
                  className={`mb-1 flex min-w-[10rem] max-w-full items-center gap-2.5 rounded-lg px-2.5 py-2 text-xs no-underline ${
                    mine && !failed ? 'bg-on-primary/15 text-on-primary' : 'bg-[color:var(--color-text)]/10 text-[color:var(--color-text)]'
                  }`}
                >
                  <FileText className="h-5 w-5 shrink-0" aria-hidden="true" />
                  <span className="min-w-0 flex-1">
                    <span className="block truncate font-medium">{message.media_name || 'File'}</span>
                    {message.media_size ? <span className="block opacity-75">{fileSize(message.media_size)}</span> : null}
                  </span>
                  {mediaUrl && <Download className="h-4 w-4 shrink-0 opacity-80" aria-label="Download" />}
                </a>
              )}
              {message.body && (
                <p className={`whitespace-pre-wrap break-words ${big ? 'text-3xl leading-tight' : ''}`}>
                  {pieces.map((piece, index) =>
                    piece.href ? (
                      <a key={index} href={piece.href} target="_blank" rel="noopener noreferrer" className="underline underline-offset-2 hover:opacity-80">
                        {piece.text}
                      </a>
                    ) : (
                      <span key={index}>
                        {splitBillNumbers(piece.text).map((part, at) => (part.bill ? <BillNumber key={at} number={part.text} inherit /> : part.text))}
                      </span>
                    ),
                  )}
                </p>
              )}
            </>
          )}

          {pending?.state === 'sending' && typeof pending.progress === 'number' && (
            <div className="mt-1.5 h-1 overflow-hidden rounded-full bg-on-primary/25" role="progressbar" aria-valuenow={Math.round(pending.progress * 100)} aria-valuemin={0} aria-valuemax={100} aria-label="Uploading">
              <div className="h-full rounded-full bg-on-primary transition-[width] duration-150" style={{ width: `${Math.round(pending.progress * 100)}%` }} />
            </div>
          )}

          {(runEnd || pending || message.edited_timestamp) && (
            <p className={`mt-1 flex items-center justify-end gap-1 text-[11px] ${subtle}`}>
              {message.edited_timestamp && !deleted && (
                <span className="inline-flex items-center gap-0.5" title={`Edited ${fullTime(message.edited_timestamp)}`}>
                  <Pencil className="h-2.5 w-2.5" aria-hidden="true" />
                  edited
                </span>
              )}
              <span>{clock(message.created_timestamp)}</span>
              {mine && !deleted && <Ticks message={message} peerRead={peerRead} />}
            </p>
          )}
        </div>

        {failed && (
          <p className="mt-1 flex items-center gap-2 text-xs text-negative" role="alert">
            <span className="truncate">{pending?.error || 'Not sent'}</span>
            <button type="button" onClick={() => onRetry(message.id)} className="font-semibold underline underline-offset-2">
              Retry
            </button>
            <button type="button" onClick={() => onDiscard(message.id)} className="underline underline-offset-2">
              Discard
            </button>
          </p>
        )}

        {!deleted && (message.reactions?.length ?? 0) > 0 && (
          <div className={`-mt-1.5 flex flex-wrap gap-1 ${mine ? 'justify-end pr-2' : 'pl-2'}`}>
            {message.reactions!.map((reaction) => {
              const mineToo = reaction.user_ids.includes(meId)
              return (
                <button
                  key={reaction.emoji}
                  type="button"
                  onClick={() => onReact(message, reaction.emoji)}
                  aria-pressed={mineToo}
                  aria-label={`${reaction.emoji} ${reaction.user_ids.length}${mineToo ? ', you reacted. Remove your reaction' : '. Add your reaction'}`}
                  className={`interactive inline-flex items-center gap-1 rounded-full border px-1.5 py-0.5 text-xs shadow-card ${
                    mineToo
                      ? 'border-[color:var(--color-accent)] bg-accent-dim text-accent'
                      : 'border-[color:var(--color-border)] bg-surface text-[color:var(--color-text)] hover:border-[color:var(--color-border-strong)]'
                  }`}
                >
                  <span>{reaction.emoji}</span>
                  {reaction.user_ids.length > 1 && <span className="tabular-nums">{reaction.user_ids.length}</span>}
                </button>
              )
            })}
          </div>
        )}
      </div>
    </div>
  )
}

export const MessageBubble = memo(Bubble)
