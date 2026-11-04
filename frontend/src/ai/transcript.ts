import type { AiEvent, AiMessage, AiPart, AiPendingAction } from '../types'

/*
 * Turning the server's stream into a message, and a saved conversation into what the screen shows. Pure functions, no
 * React, so they are easy to reason about: an assistant message is a list of parts in the order they were produced.
 */

/** A pending action older than this has expired on the server (it keeps them 20 minutes). */
const PENDING_MINUTES = 20

let local = 0
/** Ids for messages that have not been saved yet are negative, so they can never collide with a saved one. */
export const localId = () => --local

export function userMessage(text: string): AiMessage {
  return { id: localId(), role: 'user', text, parts: [{ type: 'text', text }] }
}

export function emptyAssistant(): AiMessage {
  return { id: localId(), role: 'assistant', text: '', parts: [] }
}

/** The message with one more event applied. Returns a new message; the old one is untouched. */
export function applyEvent(message: AiMessage, event: AiEvent): AiMessage {
  const parts = message.parts.slice()
  switch (event.type) {
    case 'text': {
      const last = parts[parts.length - 1]
      if (last && last.type === 'text') parts[parts.length - 1] = { type: 'text', text: last.text + event.delta }
      else parts.push({ type: 'text', text: event.delta })
      return { ...message, parts, text: message.text + event.delta }
    }
    case 'reset':
      // What was written is taken back (a retry, or a stronger model taking over): the answer starts again.
      return { ...message, parts: [], text: '' }
    case 'route': {
      const { type: _type, ...route } = event
      return { ...message, parts: [{ type: 'route', ...route }, ...parts.filter((part) => part.type !== 'route')] }
    }
    case 'tool': {
      const at = parts.findIndex((part) => part.type === 'tool' && part.id === event.id)
      const next: AiPart = { type: 'tool', id: event.id, label: event.label, status: event.status, summary: event.summary }
      if (at === -1) parts.push(next)
      else parts[at] = next
      return { ...message, parts }
    }
    case 'block':
      parts.push({ type: 'block', block: event.block })
      return { ...message, parts }
    case 'ui':
      parts.push({ type: 'ui', action: event.action })
      return { ...message, parts }
    case 'confirm':
      parts.push({ type: 'confirm', action: event.action })
      return { ...message, parts }
    case 'notice':
      parts.push({ type: 'notice', kind: event.kind, text: event.text, figures: event.figures, can_use_cloud: event.can_use_cloud, local_state: event.local_state, reason: event.reason })
      return { ...message, parts }
    case 'sources':
      parts.push({ type: 'sources', sources: event.sources })
      return { ...message, parts }
    case 'done':
      return event.message_id ? { ...message, id: event.message_id } : message
    default:
      return message
  }
}

/** The same message with one pending action changed (confirmed, cancelled, failed). */
export function withAction(message: AiMessage, actionId: string, change: Partial<AiPendingAction>): AiMessage {
  let touched = false
  const parts = message.parts.map((part) => {
    if (part.type === 'confirm' && part.action.id === actionId) {
      touched = true
      return { ...part, action: { ...part.action, ...change } }
    }
    return part
  })
  return touched ? { ...message, parts } : message
}

/**
 * A saved conversation as the screen shows it. What happened to each confirmation card is stored as a separate small
 * message after it; this folds that result into the card and drops the small message, and marks cards that were left
 * unanswered too long as expired.
 */
export function present(saved: AiMessage[], now = Date.now()): AiMessage[] {
  const results = new Map<string, Extract<AiPart, { type: 'action_result' }>>()
  for (const message of saved) {
    for (const part of message.parts || []) if (part.type === 'action_result') results.set(part.action_id, part)
  }
  const shown: AiMessage[] = []
  for (const message of saved) {
    const parts = message.parts || []
    if (message.role === 'assistant' && parts.length > 0 && parts.every((part) => part.type === 'action_result')) continue
    const stamp = message.created_timestamp ? Date.parse(message.created_timestamp) : now
    const expired = now - stamp > PENDING_MINUTES * 60_000
    shown.push({
      ...message,
      parts: parts.map((part) => {
        if (part.type !== 'confirm') return part
        const result = results.get(part.action.id)
        if (result) {
          const status = result.ok ? 'done' : /^cancelled/i.test(result.text) ? 'cancelled' : 'failed'
          return { ...part, action: { ...part.action, status, result: result.text } }
        }
        return expired && part.action.status === 'pending' ? { ...part, action: { ...part.action, status: 'expired' as const } } : part
      }),
    })
  }
  return shown
}

/** The plain words of a message, for copying and for sending as history. */
export function plainText(message: AiMessage): string {
  const text = message.parts.filter((part): part is Extract<AiPart, { type: 'text' }> => part.type === 'text').map((part) => part.text).join('')
  return (text || message.text).replace(/\n*\[Looked up this turn:[^\]]*\]\s*$/i, '').trim()
}
