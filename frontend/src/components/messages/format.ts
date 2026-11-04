import type { ChatMediaKind, ChatMessage } from '../../types'

const MINUTE = 60_000

function parse(value?: string | null): Date | null {
  if (!value) return null
  const date = new Date(value)
  return Number.isNaN(date.getTime()) ? null : date
}

export function sameDay(a: Date, b: Date): boolean {
  return a.getFullYear() === b.getFullYear() && a.getMonth() === b.getMonth() && a.getDate() === b.getDate()
}

/** 14:05 */
export function clock(value?: string | null): string {
  const date = parse(value)
  return date ? date.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }) : ''
}

/** For the conversation list: the time today, "Yesterday", the weekday this week, otherwise the date. */
export function listTime(value?: string | null, now = new Date()): string {
  const date = parse(value)
  if (!date) return ''
  if (sameDay(date, now)) return clock(value)
  const yesterday = new Date(now)
  yesterday.setDate(now.getDate() - 1)
  if (sameDay(date, yesterday)) return 'Yesterday'
  const days = (now.getTime() - date.getTime()) / (24 * 60 * MINUTE)
  if (days < 6) return date.toLocaleDateString([], { weekday: 'short' })
  return date.toLocaleDateString([], { day: 'numeric', month: 'short', year: date.getFullYear() === now.getFullYear() ? undefined : '2-digit' })
}

/** For the separator between days in a conversation. */
export function dayLabel(value?: string | null, now = new Date()): string {
  const date = parse(value)
  if (!date) return ''
  if (sameDay(date, now)) return 'Today'
  const yesterday = new Date(now)
  yesterday.setDate(now.getDate() - 1)
  if (sameDay(date, yesterday)) return 'Yesterday'
  return date.toLocaleDateString([], {
    weekday: 'long',
    day: 'numeric',
    month: 'long',
    year: date.getFullYear() === now.getFullYear() ? undefined : 'numeric',
  })
}

export function fullTime(value?: string | null): string {
  const date = parse(value)
  return date ? date.toLocaleString([], { dateStyle: 'medium', timeStyle: 'short' }) : ''
}

export function fileSize(bytes?: number | null): string {
  if (!bytes) return ''
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${Math.round(bytes / 1024)} KB`
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`
}

/** What kind of attachment a file will be treated as, for the preview before it is sent. */
export function kindOf(file: File): ChatMediaKind {
  if (file.type.startsWith('image/')) return 'image'
  if (file.type.startsWith('video/')) return 'video'
  if (file.type.startsWith('audio/')) return 'audio'
  return 'file'
}

/** A recorded voice note: the file, with how long it is and a small picture of its loudness (up to 64 numbers, 0 to 100). */
export type VoiceFile = File & { voice?: { durationMs: number; waveform: number[] } }

export function voiceOf(file?: File | null): { durationMs: number; waveform: number[] } | undefined {
  return (file as VoiceFile | null | undefined)?.voice
}

/** 0:07 or 12:03 */
export function playTime(ms: number): string {
  const total = Math.max(0, Math.round(ms / 1000))
  return `${Math.floor(total / 60)}:${String(total % 60).padStart(2, '0')}`
}

/** What a call that is in the conversation says: who it was with and how it went, from the point of view of the person reading. */
export function callSummary(message: ChatMessage, meId: number, peerName: string): { text: string; missed: boolean } {
  const call = message.call
  if (!call) return { text: '', missed: false }
  const noun = call.kind === 'video' ? 'video call' : 'voice call'
  const mine = call.caller_id === meId
  if (call.outcome === 'ended' || call.outcome === 'answered') {
    return { text: `${noun[0].toUpperCase()}${noun.slice(1)}${call.seconds ? ` · ${playTime(call.seconds * 1000)}` : ''}`, missed: false }
  }
  if (call.outcome === 'declined') return { text: mine ? `${peerName} declined the ${noun}` : `You declined the ${noun}`, missed: false }
  if (call.outcome === 'cancelled') return mine ? { text: `Cancelled ${noun}`, missed: false } : { text: `Missed ${noun}`, missed: true }
  // Nobody answered.
  return mine ? { text: `${peerName} did not answer the ${noun}`, missed: false } : { text: `Missed ${noun}`, missed: true }
}

export function newClientId(): string {
  try {
    return crypto.randomUUID()
  } catch {
    return `c${Date.now().toString(36)}${Math.random().toString(36).slice(2, 10)}`
  }
}

/** Two messages are shown as one run when the same person sent them within five minutes, on the same day. */
export function continues(previous: ChatMessage | undefined, current: ChatMessage | undefined): boolean {
  if (!previous || !current || previous.sender_id !== current.sender_id || previous.call || current.call || previous.system || current.system) return false
  const a = parse(previous.created_timestamp)
  const b = parse(current.created_timestamp)
  if (!a || !b || !sameDay(a, b)) return false
  return b.getTime() - a.getTime() < 5 * MINUTE
}

const NAME_TONES = ['text-accent', 'text-positive', 'text-warning', 'text-[color:var(--color-text)]']

/** The colour a person's name wears above their messages in a group: the same person always gets the same one. */
export function senderTone(userId: number): string {
  return NAME_TONES[Math.abs(userId) % NAME_TONES.length]
}

export type Piece = { text: string; href?: string }

const URL_PATTERN = /\b(https?:\/\/[^\s<>"']+)/gi

/** Text with web addresses picked out. Only http and https become links; everything else stays plain text. */
export function linkify(text: string): Piece[] {
  const pieces: Piece[] = []
  let last = 0
  for (const match of text.matchAll(URL_PATTERN)) {
    const start = match.index ?? 0
    let url = match[1]
    let trailing = ''
    while (/[.,;:!?)\]]$/.test(url)) {
      trailing = url.slice(-1) + trailing
      url = url.slice(0, -1)
    }
    if (start > last) pieces.push({ text: text.slice(last, start) })
    pieces.push({ text: url, href: url })
    if (trailing) pieces.push({ text: trailing })
    last = start + match[1].length
  }
  if (last < text.length) pieces.push({ text: text.slice(last) })
  return pieces.length ? pieces : [{ text }]
}

/** The same text with the search words marked, as pieces, for showing why a result matched. */
export function highlight(text: string, query: string): { text: string; match: boolean }[] {
  const needle = query.trim()
  if (!needle) return [{ text, match: false }]
  const out: { text: string; match: boolean }[] = []
  const lower = text.toLowerCase()
  const target = needle.toLowerCase()
  let from = 0
  for (;;) {
    const at = lower.indexOf(target, from)
    if (at === -1) break
    if (at > from) out.push({ text: text.slice(from, at), match: false })
    out.push({ text: text.slice(at, at + target.length), match: true })
    from = at + target.length
  }
  if (from < text.length) out.push({ text: text.slice(from), match: false })
  return out.length ? out : [{ text, match: false }]
}
