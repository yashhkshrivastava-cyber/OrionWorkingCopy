import { useEffect, useMemo, useRef, useState } from 'react'
import { createPortal } from 'react-dom'
import { ChevronDown, ChevronUp, Download, FileText, Forward, Loader2, Phone, Pin, Search, Video, X } from 'lucide-react'
import { api } from '../../api/client'
import { UserAvatar } from '../UserAvatar'
import type { ChatMessage, ChatPeer, ChatSearchHit, ChatSettings, ChatSharedItem, ChatThread } from '../../types'
import { fileSize, highlight, listTime, fullTime } from './format'
import { GroupAvatar } from './GroupAvatar'
import { GroupIdentity, GroupMembers } from './GroupSection'

// ---------------------------------------------------------------------------------------------------- pinned bar

/** The pinned message at the top of the conversation. With several, each press shows the next one and goes to it. */
export function PinnedBar({ pins, onGo, onOpenPanel }: { pins: ChatMessage[]; onGo: (messageId: number) => void; onOpenPanel: () => void }) {
  const [at, setAt] = useState(0)
  useEffect(() => setAt(0), [pins.length])
  if (!pins.length) return null
  const current = pins[Math.min(at, pins.length - 1)]
  const text = current.body || (current.media_kind === 'image' ? 'Photo' : current.media_kind === 'video' ? 'Video' : current.media_kind === 'audio' ? 'Voice note' : current.media_name || 'File')
  return (
    <div className="flex items-center gap-2 border-b border-[color:var(--color-border)] bg-muted/50 px-3 py-1.5 text-xs sm:px-4">
      <Pin className="h-3.5 w-3.5 shrink-0 text-accent" aria-hidden="true" />
      <button
        type="button"
        onClick={() => {
          onGo(current.id)
          setAt((value) => (value + 1) % pins.length)
        }}
        className="min-w-0 flex-1 text-left"
        aria-label={`Pinned message ${Math.min(at, pins.length - 1) + 1} of ${pins.length}: ${text}. Go to it`}
      >
        <span className="font-semibold text-accent">Pinned{pins.length > 1 ? ` ${Math.min(at, pins.length - 1) + 1} of ${pins.length}` : ''}</span>
        <span className="ml-2 truncate text-[color:var(--color-text-muted)]">{text.slice(0, 120)}</span>
      </button>
      {pins.length > 1 && (
        <button type="button" onClick={onOpenPanel} className="shrink-0 font-medium text-accent hover:underline">
          All
        </button>
      )}
    </div>
  )
}

// ----------------------------------------------------------------------------------------------- search in a chat

export function InChatSearch({
  chatId,
  meId,
  peer,
  names,
  onGo,
  onClose,
}: {
  chatId: number
  meId: number
  peer: ChatPeer | null
  /** In a group: who each person is. */
  names?: Map<number, string>
  onGo: (messageId: number) => void
  onClose: () => void
}) {
  const [query, setQuery] = useState('')
  const [hits, setHits] = useState<ChatSearchHit[]>([])
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [active, setActive] = useState(0)
  const input = useRef<HTMLInputElement>(null)

  useEffect(() => input.current?.focus(), [])

  useEffect(() => {
    const text = query.trim()
    setError('')
    if (text.length < 2) {
      setHits([])
      return
    }
    setBusy(true)
    const timer = window.setTimeout(() => {
      api
        .searchChats(text, chatId)
        .then((result) => {
          setHits(result.results)
          setActive(0)
        })
        .catch((err: Error) => setError(err.message))
        .finally(() => setBusy(false))
    }, 250)
    return () => window.clearTimeout(timer)
  }, [query, chatId])

  const go = (hit?: ChatSearchHit) => {
    if (hit) onGo(hit.id)
  }

  return (
    <div className="relative border-b border-[color:var(--color-border)] bg-surface px-3 py-2 sm:px-4">
      <div className="flex items-center gap-2">
        <Search className="h-4 w-4 text-[color:var(--color-text-faint)]" aria-hidden="true" />
        <input
          ref={input}
          value={query}
          onChange={(event) => setQuery(event.target.value)}
          onKeyDown={(event) => {
            if (event.key === 'Escape') onClose()
            else if (event.key === 'ArrowDown') {
              event.preventDefault()
              setActive((n) => Math.min(n + 1, hits.length - 1))
            } else if (event.key === 'ArrowUp') {
              event.preventDefault()
              setActive((n) => Math.max(n - 1, 0))
            } else if (event.key === 'Enter') {
              event.preventDefault()
              go(hits[active])
            }
          }}
          placeholder="Search in this conversation"
          aria-label="Search in this conversation"
          className="min-w-0 flex-1 bg-transparent text-sm outline-none placeholder:text-[color:var(--color-text-faint)]"
        />
        {busy && <Loader2 className="h-4 w-4 animate-spin text-[color:var(--color-text-faint)]" aria-hidden="true" />}
        {hits.length > 1 && (
          <span className="flex items-center gap-0.5 text-xs text-[color:var(--color-text-muted)]">
            {active + 1}/{hits.length}
            <button type="button" aria-label="Previous result" onClick={() => setActive((n) => Math.max(n - 1, 0))} className="rounded p-1 hover:bg-muted">
              <ChevronUp className="h-4 w-4" />
            </button>
            <button type="button" aria-label="Next result" onClick={() => setActive((n) => Math.min(n + 1, hits.length - 1))} className="rounded p-1 hover:bg-muted">
              <ChevronDown className="h-4 w-4" />
            </button>
          </span>
        )}
        <button type="button" onClick={onClose} aria-label="Close search" className="rounded p-1 text-[color:var(--color-text-muted)] hover:bg-muted">
          <X className="h-4 w-4" />
        </button>
      </div>
      {(hits.length > 0 || error || (query.trim().length >= 2 && !busy)) && (
        <div className="absolute inset-x-0 top-full z-20 max-h-72 overflow-y-auto border-b border-[color:var(--color-border)] bg-surface shadow-overlay" role="listbox" aria-label="Search results">
          {error && <p className="px-4 py-3 text-xs text-negative">{error}</p>}
          {!error && hits.length === 0 && !busy && <p className="px-4 py-3 text-sm text-[color:var(--color-text-muted)]">No messages match “{query.trim()}”.</p>}
          {hits.map((hit, index) => (
            <button
              key={hit.id}
              type="button"
              role="option"
              aria-selected={index === active}
              onClick={() => go(hit)}
              onMouseEnter={() => setActive(index)}
              className={`block w-full px-4 py-2.5 text-left ${index === active ? 'bg-accent-dim/60' : 'hover:bg-muted'}`}
            >
              <span className="flex items-baseline justify-between gap-3 text-[11px] text-[color:var(--color-text-faint)]">
                <span className="font-medium text-[color:var(--color-text-muted)]">{hit.sender_id === meId ? 'You' : names?.get(hit.sender_id) || peer?.display_name || 'Them'}</span>
                <span>{listTime(hit.created_timestamp)}</span>
              </span>
              <span className="mt-0.5 block text-sm">
                {highlight(hit.snippet, query).map((part, i) =>
                  part.match ? (
                    <mark key={i} className="rounded bg-warning-dim px-0.5 text-[color:var(--color-text)]">
                      {part.text}
                    </mark>
                  ) : (
                    <span key={i}>{part.text}</span>
                  ),
                )}
              </span>
            </button>
          ))}
        </div>
      )}
    </div>
  )
}

// ----------------------------------------------------------------------------------------------------- contact panel

export function ContactPanel({
  chat,
  peer,
  online,
  pins,
  onClose,
  onGo,
  onUnpin,
  onSettings,
  onDelete,
  onOpenMedia,
  onCall,
  onSearch,
  group,
}: {
  chat: ChatThread | null
  peer: ChatPeer | null
  online: boolean
  pins: ChatMessage[]
  onClose: () => void
  onGo: (messageId: number) => void
  onUnpin: (messageId: number) => void
  onSettings: (changes: Partial<ChatSettings>) => void
  onDelete: () => void
  onOpenMedia: (url: string, name: string) => void
  onCall?: (kind: 'voice' | 'video') => void
  onSearch?: () => void
  /** Present for a group: who is looking, everybody who could be added, and what leaving does. */
  group?: { meId: number; directory: ChatPeer[]; online: number[]; onLeave: () => void }
}) {
  const [items, setItems] = useState<ChatSharedItem[] | null>(null)
  const [tab, setTab] = useState<'media' | 'files' | 'pinned'>('media')
  const chatId = chat?.id ?? null

  useEffect(() => {
    // A person you have not written to yet has no conversation, so nothing has been shared.
    if (!chatId) {
      setItems([])
      return
    }
    let live = true
    setItems(null)
    api
      .chatMedia(chatId)
      .then((result) => live && setItems(result.items))
      .catch(() => live && setItems([]))
    return () => {
      live = false
    }
  }, [chatId, chat?.last_message?.id])

  const media = useMemo(() => (items ?? []).filter((i) => i.kind === 'image' || i.kind === 'video'), [items])
  const docs = useMemo(() => (items ?? []).filter((i) => i.kind === 'file'), [items])
  const settings = chat?.settings
  const tabs: [typeof tab, string, number][] = [
    ['media', 'Media', media.length],
    ['files', 'Files', docs.length],
    ['pinned', 'Pinned', pins.length],
  ]

  return (
    <aside className="flex min-h-0 w-full shrink-0 flex-col border-l border-[color:var(--color-border)] bg-surface 2xl:w-80" aria-label="Conversation details">
      <div className="flex items-center justify-between border-b border-[color:var(--color-border)] px-4 py-3">
        <h2 className="text-sm font-semibold">Details</h2>
        <button type="button" onClick={onClose} aria-label="Close details" className="rounded-lg p-1.5 text-[color:var(--color-text-muted)] hover:bg-muted">
          <X className="h-4 w-4" />
        </button>
      </div>
      <div className="min-h-0 flex-1 overflow-y-auto">
        {chat?.kind === 'group' && <GroupIdentity chat={chat} admin={chat.my_role === 'admin'} />}
        {chat?.kind !== 'group' && peer && (
          <div className="flex flex-col items-center px-4 py-5 text-center">
            <span className="relative">
              <UserAvatar user={peer} size="lg" />
              {online && <span className="absolute bottom-0.5 right-0.5 h-4 w-4 rounded-full border-[3px] border-[color:var(--color-surface)] bg-positive" aria-label="Online" />}
            </span>
            <p className="mt-3 text-lg font-bold">{peer.display_name}</p>
            <p className="text-xs text-[color:var(--color-text-muted)]">@{peer.username}</p>
            <p className="mt-1 text-xs text-[color:var(--color-text-muted)]">
              {online ? <span className="text-positive">Online now</span> : peer.role ? peer.role.charAt(0).toUpperCase() + peer.role.slice(1) : ''}
            </p>
            {(onCall || onSearch) && (
              <div className="mt-4 flex items-start justify-center gap-4">
                {onCall && (
                  <>
                    <button type="button" onClick={() => onCall('voice')} className="interactive flex w-16 flex-col items-center gap-1.5 text-xs font-medium text-[color:var(--color-text-muted)]">
                      <span className="chat-call-button inline-flex h-11 w-11 items-center justify-center rounded-full bg-accent-dim text-accent">
                        <Phone className="h-5 w-5" aria-hidden="true" />
                      </span>
                      Call
                    </button>
                    <button type="button" onClick={() => onCall('video')} className="interactive flex w-16 flex-col items-center gap-1.5 text-xs font-medium text-[color:var(--color-text-muted)]">
                      <span className="chat-call-button inline-flex h-11 w-11 items-center justify-center rounded-full bg-accent-dim text-accent">
                        <Video className="h-5 w-5" aria-hidden="true" />
                      </span>
                      Video
                    </button>
                  </>
                )}
                {onSearch && (
                  <button type="button" onClick={onSearch} className="interactive flex w-16 flex-col items-center gap-1.5 text-xs font-medium text-[color:var(--color-text-muted)]">
                    <span className="chat-call-button inline-flex h-11 w-11 items-center justify-center rounded-full bg-accent-dim text-accent">
                      <Search className="h-5 w-5" aria-hidden="true" />
                    </span>
                    Search
                  </button>
                )}
              </div>
            )}
          </div>
        )}
        {chat?.kind === 'group' && group && <GroupMembers chat={chat} meId={group.meId} directory={group.directory} online={group.online} admin={chat.my_role === 'admin'} />}
        {settings && (
          <div className="space-y-1 border-y border-[color:var(--color-border)] px-3 py-2">
            {(
              [
                ['muted', 'Mute notifications', 'No pop-ups or badge for this conversation'],
                ['pinned', 'Keep at the top', 'Stays first in your list'],
                ['archived', 'Archive', 'Hidden from your list until a new message'],
              ] as const
            ).map(([key, label, hint]) => (
              <div key={key} className="flex items-center justify-between gap-3 rounded-lg px-1 py-2">
                <span id={`setting-${key}`}>
                  <span className="block text-sm">{label}</span>
                  <span className="block text-xs text-[color:var(--color-text-faint)]">{hint}</span>
                </span>
                <button
                  type="button"
                  role="switch"
                  aria-checked={settings[key]}
                  aria-labelledby={`setting-${key}`}
                  onClick={() => onSettings({ [key]: !settings[key] })}
                  className={`interactive relative h-6 w-10 shrink-0 rounded-full transition-colors focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[color:var(--color-accent)] ${
                    settings[key] ? 'bg-primary' : 'bg-[color:var(--color-border-strong)]'
                  }`}
                >
                  <span
                    className={`absolute top-0.5 h-5 w-5 rounded-full bg-surface shadow-card transition-[left] ${settings[key] ? 'left-[1.125rem]' : 'left-0.5'}`}
                  />
                </button>
              </div>
            ))}
          </div>
        )}
        <div className="px-3 pt-3">
          <div role="tablist" className="flex gap-1 rounded-lg bg-muted p-0.5">
            {tabs.map(([id, label, count]) => (
              <button
                key={id}
                type="button"
                role="tab"
                aria-selected={tab === id}
                onClick={() => setTab(id)}
                className={`flex-1 rounded-md px-2 py-1.5 text-xs font-medium ${tab === id ? 'bg-surface shadow-card' : 'text-[color:var(--color-text-muted)]'}`}
              >
                {label} {count > 0 && <span className="text-[color:var(--color-text-faint)]">{count}</span>}
              </button>
            ))}
          </div>
          <div className="py-3">
            {items === null && tab !== 'pinned' && (
              <p className="flex items-center justify-center gap-2 py-6 text-xs text-[color:var(--color-text-faint)]">
                <Loader2 className="h-4 w-4 animate-spin" /> Loading
              </p>
            )}
            {tab === 'media' && items !== null &&
              (media.length ? (
                <div className="grid grid-cols-3 gap-1.5">
                  {media.map((item) =>
                    item.kind === 'image' ? (
                      <button key={item.message_id} type="button" onClick={() => onOpenMedia(item.url, item.name)} className="aspect-square overflow-hidden rounded-lg bg-muted" aria-label={`Open ${item.name}`}>
                        <img src={item.url} alt="" loading="lazy" className="h-full w-full object-cover" />
                      </button>
                    ) : (
                      <a key={item.message_id} href={item.url} target="_blank" rel="noreferrer" className="flex aspect-square items-center justify-center rounded-lg bg-muted text-[10px] text-[color:var(--color-text-muted)]">
                        Video
                      </a>
                    ),
                  )}
                </div>
              ) : (
                <p className="py-6 text-center text-xs text-[color:var(--color-text-faint)]">No photos or videos yet.</p>
              ))}
            {tab === 'files' && items !== null &&
              (docs.length ? (
                <ul className="space-y-1">
                  {docs.map((item) => (
                    <li key={item.message_id}>
                      <a href={item.url} download={item.name} className="interactive flex items-center gap-2.5 rounded-lg px-2 py-2 hover:bg-muted">
                        <FileText className="h-5 w-5 shrink-0 text-[color:var(--color-text-muted)]" aria-hidden="true" />
                        <span className="min-w-0 flex-1">
                          <span className="block truncate text-sm">{item.name}</span>
                          <span className="block text-xs text-[color:var(--color-text-faint)]">
                            {fileSize(item.size)} · {fullTime(item.created_timestamp)}
                          </span>
                        </span>
                        <Download className="h-4 w-4 text-[color:var(--color-text-faint)]" aria-hidden="true" />
                      </a>
                    </li>
                  ))}
                </ul>
              ) : (
                <p className="py-6 text-center text-xs text-[color:var(--color-text-faint)]">No files yet.</p>
              ))}
            {tab === 'pinned' &&
              (pins.length ? (
                <ul className="space-y-1.5">
                  {pins.map((pin) => (
                    <li key={pin.id} className="flex items-start gap-2 rounded-lg border border-[color:var(--color-border)] p-2">
                      <button type="button" onClick={() => onGo(pin.id)} className="min-w-0 flex-1 text-left">
                        <span className="block text-[11px] text-[color:var(--color-text-faint)]">{fullTime(pin.created_timestamp)}</span>
                        <span className="line-clamp-3 text-sm">{pin.body || pin.media_name || 'Attachment'}</span>
                      </button>
                      <button type="button" onClick={() => onUnpin(pin.id)} aria-label="Unpin" className="rounded p-1 text-[color:var(--color-text-faint)] hover:bg-muted">
                        <X className="h-3.5 w-3.5" />
                      </button>
                    </li>
                  ))}
                </ul>
              ) : (
                <p className="py-6 text-center text-xs text-[color:var(--color-text-faint)]">Nothing pinned. Use a message’s menu to pin it.</p>
              ))}
          </div>
        </div>
      </div>
      {chatId && (
        <div className="border-t border-[color:var(--color-border)] p-3">
          {chat?.kind === 'group' ? (
            <>
              <button type="button" onClick={group?.onLeave} className="interactive w-full rounded-lg px-3 py-2 text-sm font-medium text-negative hover:bg-negative-dim">
                Leave group
              </button>
              {chat.my_role === 'admin' && (
                <button type="button" onClick={onDelete} className="interactive w-full rounded-lg px-3 py-2 text-sm font-medium text-negative hover:bg-negative-dim">
                  Delete group for everyone
                </button>
              )}
            </>
          ) : (
            <button type="button" onClick={onDelete} className="interactive w-full rounded-lg px-3 py-2 text-sm font-medium text-negative hover:bg-negative-dim">
              Delete conversation
            </button>
          )}
        </div>
      )}
    </aside>
  )
}

// ---------------------------------------------------------------------------------------------------- forward dialog

export function ForwardDialog({
  message,
  chats,
  people,
  meId,
  onClose,
  onForward,
}: {
  message: ChatMessage
  chats: ChatThread[]
  people: ChatPeer[]
  meId: number
  onClose: () => void
  onForward: (target: { chat_id?: number; user_id?: number }) => Promise<void>
}) {
  const [query, setQuery] = useState('')
  const [busy, setBusy] = useState<string | null>(null)
  void meId
  const needle = query.trim().toLowerCase()
  const inChats = new Set(chats.map((c) => c.peer?.id))
  type Row = { key: string; name: string; note: string; person: ChatPeer | null; target: { chat_id?: number; user_id?: number } }
  const rows: Row[] = [
    ...chats
      .filter((c) => c.peer || c.kind === 'group')
      .map((c): Row =>
        c.kind === 'group'
          ? { key: `c${c.id}`, name: c.title ?? 'Group', note: `Group · ${c.members.length} people`, person: null, target: { chat_id: c.id } }
          : { key: `c${c.id}`, name: c.peer!.display_name, note: `@${c.peer!.username}`, person: c.peer!, target: { chat_id: c.id } },
      ),
    ...people.filter((p) => !inChats.has(p.id)).map((p): Row => ({ key: `u${p.id}`, name: p.display_name, note: `@${p.username}`, person: p, target: { user_id: p.id } })),
  ].filter((row) => !needle || `${row.name} ${row.note}`.toLowerCase().includes(needle))

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => event.key === 'Escape' && onClose()
    document.addEventListener('keydown', onKey)
    return () => document.removeEventListener('keydown', onKey)
  }, [onClose])

  return createPortal(
    <div className="fixed inset-0 z-[70] flex items-end justify-center bg-[color:var(--color-scrim)] p-0 sm:items-center sm:p-4" onPointerDown={(event) => event.target === event.currentTarget && onClose()}>
      <div role="dialog" aria-modal="true" aria-label="Forward message" className="modal-in flex max-h-[80dvh] w-full max-w-md flex-col overflow-hidden rounded-t-2xl border border-[color:var(--color-border)] bg-surface shadow-overlay sm:rounded-2xl">
        <div className="flex items-center justify-between border-b border-[color:var(--color-border)] px-4 py-3">
          <h2 className="flex items-center gap-2 text-sm font-semibold">
            <Forward className="h-4 w-4 text-accent" aria-hidden="true" />
            Forward to
          </h2>
          <button type="button" onClick={onClose} aria-label="Close" className="rounded-lg p-1.5 hover:bg-muted">
            <X className="h-4 w-4" />
          </button>
        </div>
        <div className="border-b border-[color:var(--color-border)] px-4 py-2.5">
          <p className="mb-2 line-clamp-2 rounded-lg bg-muted px-3 py-2 text-xs text-[color:var(--color-text-muted)]">
            {message.body || message.media_name || 'Attachment'}
          </p>
          <input
            autoFocus
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            placeholder="Find someone"
            aria-label="Find someone"
            className="w-full rounded-lg border border-[color:var(--color-border)] bg-[color:var(--color-bg)] px-3 py-2 text-sm outline-none focus:border-accent"
          />
        </div>
        <ul className="min-h-0 flex-1 overflow-y-auto py-1">
          {rows.length === 0 && <li className="px-4 py-6 text-center text-sm text-[color:var(--color-text-faint)]">No one found.</li>}
          {rows.map((row) => (
            <li key={row.key}>
              <button
                type="button"
                disabled={busy !== null}
                onClick={async () => {
                  setBusy(row.key)
                  try {
                    await onForward(row.target)
                  } finally {
                    setBusy(null)
                  }
                }}
                className="interactive flex w-full items-center gap-3 px-4 py-2.5 text-left hover:bg-muted disabled:opacity-60"
              >
                {row.person ? <UserAvatar user={row.person} size="sm" /> : <GroupAvatar title={row.name} size="sm" />}
                <span className="min-w-0 flex-1">
                  <span className="block truncate text-sm font-medium">{row.name}</span>
                  <span className="block truncate text-xs text-[color:var(--color-text-faint)]">{row.note}</span>
                </span>
                {busy === row.key && <Loader2 className="h-4 w-4 animate-spin" />}
              </button>
            </li>
          ))}
        </ul>
      </div>
    </div>,
    document.body,
  )
}

// ------------------------------------------------------------------------------------------------------------ lightbox

export function Lightbox({ url, name, onClose }: { url: string; name: string; onClose: () => void }) {
  useEffect(() => {
    const onKey = (event: KeyboardEvent) => event.key === 'Escape' && onClose()
    document.addEventListener('keydown', onKey)
    return () => document.removeEventListener('keydown', onKey)
  }, [onClose])
  return createPortal(
    <div className="fixed inset-0 z-[90] flex flex-col bg-black/85" role="dialog" aria-modal="true" aria-label={name} onPointerDown={(event) => event.target === event.currentTarget && onClose()}>
      <div className="flex items-center justify-between px-4 py-3 text-white">
        <p className="min-w-0 truncate text-sm">{name}</p>
        <div className="flex items-center gap-1">
          <a href={url} download={name} aria-label="Download" className="rounded-lg p-2 hover:bg-white/10">
            <Download className="h-5 w-5" />
          </a>
          <button type="button" onClick={onClose} aria-label="Close" autoFocus className="rounded-lg p-2 hover:bg-white/10">
            <X className="h-5 w-5" />
          </button>
        </div>
      </div>
      <div className="flex min-h-0 flex-1 items-center justify-center p-4" onPointerDown={(event) => event.target === event.currentTarget && onClose()}>
        <img src={url} alt={name} className="max-h-full max-w-full rounded-lg object-contain" />
      </div>
    </div>,
    document.body,
  )
}
