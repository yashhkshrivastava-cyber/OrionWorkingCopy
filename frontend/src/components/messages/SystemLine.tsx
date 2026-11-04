import type { ChatMessage } from '../../types'
import { fullTime } from './format'

/** A line of the conversation that nobody wrote ("Priya added Rahul", "Anita left"): small and centred, between the messages. */
export function SystemLine({ message }: { message: ChatMessage }) {
  return (
    <div className="my-3 flex justify-center px-4" data-message-id={message.id}>
      <p className="max-w-full rounded-full bg-muted px-3.5 py-1 text-center text-xs text-[color:var(--color-text-muted)]" title={fullTime(message.created_timestamp)}>
        {message.body}
      </p>
    </div>
  )
}
