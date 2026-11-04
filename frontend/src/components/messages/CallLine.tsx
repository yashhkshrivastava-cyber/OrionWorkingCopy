import { Phone, PhoneMissed, Video } from 'lucide-react'
import type { ChatMessage } from '../../types'
import { startCall } from '../calls/startCall'
import { callSummary, clock, fullTime } from './format'

/**
 * A call that happened in the conversation, as a line between the messages ("Missed voice call", "Video call · 12:03") with a
 * button to call back. It is not a bubble: nothing can be replied to, edited or forwarded.
 */
export function CallLine({ message, meId, peerName, canCall }: { message: ChatMessage; meId: number; peerName: string; canCall: boolean }) {
  const call = message.call
  if (!call) return null
  const { text, missed } = callSummary(message, meId, peerName)
  const Icon = missed ? PhoneMissed : call.kind === 'video' ? Video : Phone
  return (
    <div className="group my-3 flex justify-center" data-message-id={message.id}>
      <div
        className={`chat-call-line inline-flex max-w-full items-center gap-2.5 rounded-full border py-1.5 pl-2 pr-3 text-xs shadow-card ${
          missed ? 'border-negative/40 bg-negative-dim text-negative' : 'border-[color:var(--color-border)] bg-surface text-[color:var(--color-text-muted)]'
        }`}
        title={fullTime(message.created_timestamp)}
      >
        <span className={`inline-flex h-7 w-7 shrink-0 items-center justify-center rounded-full ${missed ? 'bg-negative/15' : 'bg-accent-dim text-accent'}`}>
          <Icon className="h-3.5 w-3.5" aria-hidden="true" />
        </span>
        <span className="min-w-0 truncate font-medium">{text}</span>
        <span className="shrink-0 tabular-nums opacity-80">{clock(message.created_timestamp)}</span>
        {canCall && (
          <button
            type="button"
            onClick={() => startCall(message.chat_id, call.kind)}
            className="interactive shrink-0 rounded-full px-2 py-0.5 font-semibold text-accent opacity-0 hover:bg-accent-dim focus-visible:opacity-100 group-hover:opacity-100 max-md:opacity-100"
          >
            Call back
          </button>
        )}
      </div>
    </div>
  )
}
