import { useEffect, useMemo, useRef, useState } from 'react'
import {
  Archive,
  ArchiveRestore,
  BellOff,
  Bell,
  Check,
  Image as ImageIcon,
  Loader2,
  Mic,
  MoreHorizontal,
  Paperclip,
  Phone,
  PhoneMissed,
  Pin,
  PinOff,
  Search,
  SquarePen,
  Users,
  Video,
  X,
} from 'lucide-react'
import { api } from '../../api/client'
import { messagePreview } from '../../context/ChatContext'
import { UserAvatar } from '../UserAvatar'
import { GroupAvatar } from './GroupAvatar'
import type { ChatMessage, ChatPeer, ChatSearchHit, ChatSettings, ChatThread } from '../../types'
import { highlight, listTime } from './format'

type Filter = 'all' | 'unread' | 'archived'

type Props = {
  chats: ChatThread[]
  people: ChatPeer[]
  loading: boolean
  selectedId: number | null
  composeUserId: number | null
  meId: number
  online: number[]
  /** Text typed but not sent, by "chat:ID" or "user:ID". */
  drafts: Record<string, string>
  typingIn: (chatId: number, userId: number) => boolean
  onOpenChat: (chatId: number) => void
  onOpenPerson: (userId: number) => void
  onOpenHit: (hit: ChatSearchHit) => void
  onSettings: (chatId: number, changes: Partial<ChatSettings>) => void
  onMarkRead: (chatId: number) => void
  onDiscardDraft: (userId: number) => void
  onNewGroup: () => void
}

/** A small picture in front of a preview that says what kind of message it is (a call, a voice note, a photo). */
function Glyph({ message, me }: { message: ChatMessage; me: number }) {
  const cls = 'mr-1 inline h-3.5 w-3.5 shrink-0 align-[-2px]'
  if (message.deleted) return null
  if (message.call) {
    const missed = ['missed', 'cancelled'].includes(message.call.outcome) && message.call.caller_id !== me
    if (missed) return <PhoneMissed className={`${cls} text-negative`} aria-hidden="true" />
    return message.call.kind === 'video' ? <Video className={cls} aria-hidden="true" /> : <Phone className={cls} aria-hidden="true" />
  }
  if (message.media_kind === 'audio') return <Mic className={cls} aria-hidden="true" />
  if (message.media_kind === 'image') return <ImageIcon className={cls} aria-hidden="true" />
  if (message.media_kind === 'video') return <Video className={cls} aria-hidden="true" />
  if (message.media_kind === 'file') return <Paperclip className={cls} aria-hidden="true" />
  return null
}

function Row({
  chat,
  active,
  me,
  online,
  draft,
  typing,
  onOpen,
  onSettings,
  onMarkRead,
}: {
  chat: ChatThread
  active: boolean
  me: number
  online: boolean
  draft?: string
  /** What to say in place of the last message while somebody is typing, or null. */
  typing: string | null
  onOpen: () => void
  onSettings: (changes: Partial<ChatSettings>) => void
  onMarkRead: () => void
}) {
  const [menu, setMenu] = useState(false)
  const box = useRef<HTMLDivElement>(null)
  const group = chat.kind === 'group'
  const peer = chat.peer
  const name = group ? (chat.title ?? 'Group') : (peer?.display_name ?? '')
  const last = chat.last_message
  const mine = last?.sender_id === me
  const settings = chat.settings
  const unread = chat.unread > 0

  useEffect(() => {
    if (!menu) return
    const close = (event: Event) => {
      if (!box.current?.contains(event.target as Node)) setMenu(false)
    }
    const key = (event: KeyboardEvent) => event.key === 'Escape' && setMenu(false)
    document.addEventListener('pointerdown', close)
    document.addEventListener('keydown', key)
    return () => {
      document.removeEventListener('pointerdown', close)
      document.removeEventListener('keydown', key)
    }
  }, [menu])

  const sender = group && last && !mine && !last.system && !last.deleted ? chat.members.find((m) => m.id === last.sender_id)?.display_name.split(' ')[0] : null
  const preview = typing ? (
    <span className="font-medium text-accent">{typing}</span>
  ) : draft ? (
    <>
      <span className="text-warning">Draft: </span>
      {draft}
    </>
  ) : (
    <>
      {mine && last && !last.deleted && !last.call && !last.system && <span className="text-[color:var(--color-text-faint)]">You: </span>}
      {sender && <span className="text-[color:var(--color-text-faint)]">{sender}: </span>}
      {last && <Glyph message={last} me={me} />}
      {messagePreview(last)}
    </>
  )

  return (
    <div
      ref={box}
      className="chat-row-wrap group relative px-2"
      onContextMenu={(event) => {
        event.preventDefault()
        setMenu(true)
      }}
    >
      <button
        type="button"
        onClick={onOpen}
        aria-current={active ? 'true' : undefined}
        className={`chat-row interactive flex w-full items-center gap-3.5 rounded-2xl px-3 py-3 text-left ${active ? 'bg-accent-dim' : 'hover:bg-muted'}`}
      >
        <span className="relative shrink-0">
          {group ? <GroupAvatar title={name} size="row" /> : peer && <UserAvatar user={peer} size="row" />}
          {online && !group && <span className="absolute bottom-0 right-0 h-3.5 w-3.5 rounded-full border-[2.5px] border-[color:var(--color-surface)] bg-positive" aria-label="Online" />}
        </span>
        <span className="min-w-0 flex-1">
          <span className="flex items-center justify-between gap-2">
            <span className={`truncate text-[15px] ${unread ? 'font-bold' : 'font-semibold'}`}>{name}</span>
            <span className={`shrink-0 text-xs ${unread && !settings.muted ? 'font-semibold text-accent' : 'text-[color:var(--color-text-faint)]'}`}>
              {listTime(last?.created_timestamp)}
            </span>
          </span>
          <span className="mt-0.5 flex items-center justify-between gap-2">
            <span className={`truncate text-[13px] ${unread ? 'font-medium text-[color:var(--color-text)]' : 'text-[color:var(--color-text-muted)]'}`}>{preview}</span>
            <span className="flex shrink-0 items-center gap-1.5">
              {settings.muted && <BellOff className="h-3.5 w-3.5 text-[color:var(--color-text-faint)]" aria-label="Muted" />}
              {settings.pinned && <Pin className="h-3.5 w-3.5 text-[color:var(--color-text-faint)]" aria-label="Kept at the top" />}
              {unread && (
                <span
                  className={`min-w-[1.4rem] rounded-full px-1.5 py-1 text-center text-[11px] font-bold leading-none ${
                    settings.muted ? 'bg-muted text-[color:var(--color-text-muted)]' : 'bg-primary text-on-primary'
                  }`}
                  aria-label={`${chat.unread} unread`}
                >
                  {chat.unread > 99 ? '99+' : chat.unread}
                </span>
              )}
            </span>
          </span>
        </span>
      </button>
      <button
        type="button"
        aria-label={`Options for ${name}`}
        aria-haspopup="menu"
        aria-expanded={menu}
        onClick={() => setMenu((open) => !open)}
        className="absolute right-4 top-3 rounded-lg bg-surface p-1 text-[color:var(--color-text-muted)] opacity-0 shadow-card hover:bg-muted focus-visible:opacity-100 group-hover:opacity-100 max-md:hidden"
      >
        <MoreHorizontal className="h-4 w-4" />
      </button>
      {menu && (
        <div role="menu" className="overlay pop-in absolute right-4 top-10 z-30 w-52 rounded-xl border border-[color:var(--color-border)] p-1.5 shadow-overlay">
          {[
            { show: unread, icon: <Check className="h-4 w-4" />, label: 'Mark as read', run: onMarkRead },
            { show: true, icon: settings.pinned ? <PinOff className="h-4 w-4" /> : <Pin className="h-4 w-4" />, label: settings.pinned ? 'Unpin from the top' : 'Keep at the top', run: () => onSettings({ pinned: !settings.pinned }) },
            { show: true, icon: settings.muted ? <Bell className="h-4 w-4" /> : <BellOff className="h-4 w-4" />, label: settings.muted ? 'Unmute' : 'Mute', run: () => onSettings({ muted: !settings.muted }) },
            { show: true, icon: settings.archived ? <ArchiveRestore className="h-4 w-4" /> : <Archive className="h-4 w-4" />, label: settings.archived ? 'Move back to chats' : 'Archive', run: () => onSettings({ archived: !settings.archived }) },
          ]
            .filter((item) => item.show)
            .map((item) => (
              <button
                key={item.label}
                type="button"
                role="menuitem"
                onClick={() => {
                  setMenu(false)
                  item.run()
                }}
                className="interactive flex w-full items-center gap-2.5 rounded-lg px-2.5 py-2 text-left text-sm hover:bg-muted"
              >
                <span className="opacity-75" aria-hidden="true">
                  {item.icon}
                </span>
                {item.label}
              </button>
            ))}
        </div>
      )}
    </div>
  )
}

/** One person in a list of people to start with: their name, whether they are around, and nothing else to read. */
function PersonRow({ person, online, active, onOpen, note }: { person: ChatPeer; online: boolean; active: boolean; onOpen: () => void; note?: React.ReactNode }) {
  return (
    <div className="px-2">
      <button type="button" onClick={onOpen} className={`interactive flex w-full items-center gap-3.5 rounded-2xl px-3 py-2.5 text-left hover:bg-muted ${active ? 'bg-accent-dim' : ''}`}>
        <span className="relative shrink-0">
          <UserAvatar user={person} size="md" />
          {online && <span className="absolute bottom-0 right-0 h-3 w-3 rounded-full border-2 border-[color:var(--color-surface)] bg-positive" aria-label="Online" />}
        </span>
        <span className="min-w-0">
          <span className="block truncate text-sm font-semibold">{person.display_name}</span>
          <span className="block truncate text-xs text-[color:var(--color-text-faint)]">{note ?? (online ? 'Online' : `@${person.username}`)}</span>
        </span>
      </button>
    </div>
  )
}

/**
 * Everyone you talk to, newest first with kept-at-the-top conversations above, who is around right now, and the way to start a new
 * one. One box finds people by name and messages by what was said. The list of everyone in Orion is not always on show: it opens with
 * the new-message button, while searching, and as the way in when there are no conversations yet.
 */
export function ConversationList({ chats, people, loading, selectedId, composeUserId, meId, online, drafts, typingIn, onOpenChat, onOpenPerson, onOpenHit, onSettings, onMarkRead, onDiscardDraft, onNewGroup }: Props) {
  const [query, setQuery] = useState('')
  const [filter, setFilter] = useState<Filter>('all')
  const [hits, setHits] = useState<ChatSearchHit[]>([])
  const [searching, setSearching] = useState(false)
  const [composing, setComposing] = useState(false)
  const search = useRef<HTMLInputElement>(null)
  const needle = query.trim().toLowerCase()

  // What was said: ask the server (only the person's own conversations come back).
  useEffect(() => {
    if (needle.length < 2) {
      setHits([])
      setSearching(false)
      return
    }
    setSearching(true)
    const timer = window.setTimeout(() => {
      api
        .searchChats(query.trim())
        .then((result) => setHits(result.results))
        .catch(() => setHits([]))
        .finally(() => setSearching(false))
    }, 300)
    return () => window.clearTimeout(timer)
  }, [query, needle])

  const matches = (person: ChatPeer) => !needle || `${person.display_name} ${person.username}`.toLowerCase().includes(needle)
  const chatMatches = (c: ChatThread) => (c.kind === 'group' ? !needle || (c.title ?? '').toLowerCase().includes(needle) : Boolean(c.peer) && matches(c.peer!))

  const counts = useMemo(
    () => ({
      unread: chats.filter((c) => c.unread > 0 && !c.settings.archived).length,
      archived: chats.filter((c) => c.settings.archived).length,
    }),
    [chats],
  )

  const shown = useMemo(() => {
    const visible = chats.filter((c) => {
      if (!c.last_message || (!c.peer && c.kind !== 'group')) return false
      if (needle && !chatMatches(c)) return false
      if (filter === 'archived') return c.settings.archived
      if (c.settings.archived) return false
      if (filter === 'unread') return c.unread > 0
      return true
    })
    return visible.sort((a, b) => {
      if (a.settings.pinned !== b.settings.pinned) return a.settings.pinned ? -1 : 1
      return (b.last_message?.created_timestamp ?? '').localeCompare(a.last_message?.created_timestamp ?? '')
    })
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [chats, needle, filter])

  const inChats = useMemo(() => new Set(chats.filter((c) => c.last_message).map((c) => c.peer?.id)), [chats])
  const draftPeople = people.filter((p) => !inChats.has(p.id) && drafts[`user:${p.id}`]?.trim()).filter(matches)
  const others = people.filter((p) => !inChats.has(p.id) && !drafts[`user:${p.id}`]?.trim()).filter(matches)
  const nameById = useMemo(() => new Map(chats.map((c) => [c.id, c.kind === 'group' ? c.title : c.peer?.display_name])), [chats])
  const typingLabel = (chat: ChatThread): string | null => {
    if (chat.kind === 'group') {
      const who = chat.members.filter((m) => m.id !== meId && typingIn(chat.id, m.id)).map((m) => m.display_name.split(' ')[0])
      return who.length === 0 ? null : who.length === 1 ? `${who[0]} is typing…` : `${who.length} people are typing…`
    }
    return chat.peer && typingIn(chat.id, chat.peer.id) ? 'typing…' : null
  }
  const chatDraft = (id: number) => drafts[`chat:${id}`]?.trim()
  const isOnline = (person: ChatPeer) => person.online || online.includes(person.id)
  const around = useMemo(() => people.filter((p) => online.includes(p.id) || p.online).slice(0, 12), [people, online])

  // Everyone in Orion is offered when asked for, when searching, and when there is nothing else to show yet.
  const noConversations = !loading && chats.every((c) => !c.last_message)
  const showPeople = filter === 'all' && (composing || needle.length > 0 || noConversations)
  const peopleToShow = showPeople ? others : []

  const tab = (id: Filter, label: string, count?: number) => (
    <button
      key={id}
      type="button"
      onClick={() => setFilter(id)}
      aria-pressed={filter === id}
      className={`chat-filter interactive rounded-full px-3.5 py-1.5 text-[13px] font-semibold ${filter === id ? 'bg-primary text-on-primary' : 'bg-muted text-[color:var(--color-text-muted)] hover:text-[color:var(--color-text)]'}`}
    >
      {label}
      {count ? <span className="ml-1.5 opacity-80">{count}</span> : null}
    </button>
  )

  const peopleSection = peopleToShow.length > 0 && (
          <section aria-label="People">
            <p className="eyebrow px-5 pb-1 pt-3">{noConversations && !composing && !needle ? 'Say hello to someone' : 'People'}</p>
            {peopleToShow.map((person) => (
              <PersonRow key={person.id} person={person} online={isOnline(person)} active={composeUserId === person.id} onOpen={() => openPerson(person.id)} />
            ))}
          </section>
        )

  const newGroupRow = (
    <div className="px-2">
      <button type="button" onClick={onNewGroup} className="interactive flex w-full items-center gap-3.5 rounded-2xl px-3 py-2.5 text-left hover:bg-muted">
        <span className="inline-flex h-10 w-10 shrink-0 items-center justify-center rounded-full bg-accent-dim text-accent" aria-hidden="true">
          <Users className="h-5 w-5" />
        </span>
        <span className="text-sm font-semibold">New group</span>
      </button>
    </div>
  )
  const intro = filter === 'all' && !needle && (composing || noConversations) ? newGroupRow : null

  const openPerson = (id: number) => {
    setComposing(false)
    setQuery('')
    onOpenPerson(id)
  }

  return (
    <div className="chat-list flex h-full min-h-0 w-full flex-col bg-surface md:w-[19.5rem] md:border-r md:border-[color:var(--color-border)] xl:w-[21rem] 2xl:w-[24rem]">
      <div className="space-y-3 px-4 pb-2 pt-5">
        <div className="flex items-center justify-between gap-3">
          <h1 className="t-h1">Messages</h1>
          <button
            type="button"
            onClick={() => {
              setComposing((open) => !open)
              setFilter('all')
              if (!composing) search.current?.focus()
            }}
            aria-pressed={composing}
            aria-label={composing ? 'Close the list of people' : 'New message'}
            title={composing ? 'Close' : 'New message'}
            className={`chat-compose interactive inline-flex h-10 w-10 items-center justify-center rounded-full ${composing ? 'bg-primary text-on-primary' : 'bg-accent-dim text-accent hover:bg-muted'}`}
          >
            {composing ? <X className="h-5 w-5" /> : <SquarePen className="h-5 w-5" />}
          </button>
        </div>
        <div className="relative">
          <Search className="pointer-events-none absolute left-3.5 top-1/2 h-4 w-4 -translate-y-1/2 text-[color:var(--color-text-faint)]" aria-hidden="true" />
          <input
            ref={search}
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            placeholder="Search people and messages"
            aria-label="Search people and messages"
            className="chat-search w-full rounded-2xl border border-transparent bg-muted py-3 pl-10 pr-9 text-sm outline-none transition-colors placeholder:text-[color:var(--color-text-faint)] focus:border-accent focus:bg-surface"
          />
          {query && (
            <button type="button" onClick={() => setQuery('')} aria-label="Clear search" className="absolute right-2.5 top-1/2 -translate-y-1/2 rounded p-1 text-[color:var(--color-text-faint)] hover:bg-surface">
              <X className="h-3.5 w-3.5" />
            </button>
          )}
        </div>
      </div>

      {around.length > 0 && !needle && filter === 'all' && (
        <section aria-label="Around now" className="px-4 pb-1 pt-2">
          <p className="eyebrow mb-2 flex items-center gap-1.5">
            <span className="h-1.5 w-1.5 rounded-full bg-positive" aria-hidden="true" />
            Around now
          </p>
          <ul className="scroll-quiet -mx-1 flex gap-3 overflow-x-auto px-1 pb-2">
            {around.map((person) => (
              <li key={person.id} className="shrink-0">
                <button type="button" onClick={() => openPerson(person.id)} className="interactive flex w-16 flex-col items-center gap-1.5 rounded-2xl py-1" title={`Message ${person.display_name}`}>
                  <span className="relative">
                    <UserAvatar user={person} size="row" />
                    <span className="absolute bottom-0 right-0 h-3.5 w-3.5 rounded-full border-[2.5px] border-[color:var(--color-surface)] bg-positive" aria-hidden="true" />
                  </span>
                  <span className="w-full truncate text-center text-[11px] font-medium text-[color:var(--color-text-muted)]">{person.display_name.split(' ')[0]}</span>
                </button>
              </li>
            ))}
          </ul>
        </section>
      )}

      <div className="flex items-center gap-1.5 px-4 pb-2 pt-1" role="group" aria-label="Filter conversations">
        {tab('all', 'All')}
        {tab('unread', 'Unread', counts.unread)}
        {counts.archived > 0 || filter === 'archived' ? tab('archived', 'Archived', counts.archived) : null}
      </div>

      <div className="scroll-quiet min-h-0 flex-1 overflow-y-auto pb-3">
        {loading && chats.length === 0 && (
          <div className="space-y-1 px-4 py-3" aria-busy="true" aria-label="Loading conversations">
            {[0, 1, 2, 3, 4].map((n) => (
              <div key={n} className="flex items-center gap-3.5 py-2.5">
                <div className="skeleton h-12 w-12 rounded-full" />
                <div className="flex-1 space-y-2">
                  <div className="skeleton h-3.5 w-2/5" />
                  <div className="skeleton h-3 w-4/5" />
                </div>
              </div>
            ))}
          </div>
        )}

        {composing && (
          <>
            {intro}
            {peopleSection}
          </>
        )}

        {needle.length >= 2 && (searching || hits.length > 0) && (
          <section aria-label="Messages that match">
            <p className="eyebrow flex items-center gap-2 px-5 pb-1 pt-3">
              Messages {searching && <Loader2 className="h-3 w-3 animate-spin" aria-hidden="true" />}
            </p>
            {hits.map((hit) => {
              const chatName = nameById.get(hit.chat_id)
              return (
                <div key={hit.id} className="px-2">
                  <button type="button" onClick={() => onOpenHit(hit)} className="interactive block w-full rounded-2xl px-3 py-2.5 text-left hover:bg-muted">
                    <span className="flex items-baseline justify-between gap-2 text-xs text-[color:var(--color-text-faint)]">
                      <span className="truncate font-semibold text-[color:var(--color-text-muted)]">{chatName ?? 'Conversation'}</span>
                      <span>{listTime(hit.created_timestamp)}</span>
                    </span>
                    <span className="mt-0.5 line-clamp-2 text-sm">
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
                </div>
              )
            })}
          </section>
        )}

        {shown.length > 0 && (
          <section aria-label="Conversations">
            {(needle.length >= 2 || composing) && <p className="eyebrow px-5 pb-1 pt-3">Conversations</p>}
            {shown.map((chat) => (
              <Row
                key={chat.id}
                chat={chat}
                me={meId}
                active={chat.id === selectedId}
                online={chat.kind === 'direct' && Boolean(chat.peer && isOnline(chat.peer))}
                draft={chat.id === selectedId ? undefined : chatDraft(chat.id)}
                typing={typingLabel(chat)}
                onOpen={() => onOpenChat(chat.id)}
                onSettings={(changes) => onSettings(chat.id, changes)}
                onMarkRead={() => onMarkRead(chat.id)}
              />
            ))}
          </section>
        )}

        {filter !== 'archived' && draftPeople.length > 0 && (
          <section aria-label="Drafts">
            <p className="eyebrow px-5 pb-1 pt-3">Drafts</p>
            {draftPeople.map((person) => (
              <div key={person.id} className="flex items-center">
                <div className="min-w-0 flex-1">
                  <PersonRow
                    person={person}
                    online={isOnline(person)}
                    active={composeUserId === person.id}
                    onOpen={() => openPerson(person.id)}
                    note={
                      <>
                        <span className="text-warning">Draft: </span>
                        {drafts[`user:${person.id}`]}
                      </>
                    }
                  />
                </div>
                <button type="button" onClick={() => onDiscardDraft(person.id)} aria-label={`Discard draft for ${person.display_name}`} className="mr-3 rounded-lg p-1.5 text-[color:var(--color-text-faint)] hover:bg-muted">
                  <X className="h-3.5 w-3.5" />
                </button>
              </div>
            ))}
          </section>
        )}

        {!composing && (
          <>
            {intro}
            {peopleSection}
          </>
        )}

        {!loading && shown.length === 0 && draftPeople.length === 0 && peopleToShow.length === 0 && hits.length === 0 && !searching && (
          <div className="px-6 py-12 text-center">
            <p className="text-sm font-semibold">
              {filter === 'unread' ? 'You are all caught up' : filter === 'archived' ? 'Nothing archived' : needle ? `No one matches “${query.trim()}”` : 'No conversations yet'}
            </p>
            <p className="mt-1 text-xs text-[color:var(--color-text-muted)]">
              {filter === 'unread' ? 'Unread conversations appear here.' : filter === 'archived' ? 'Archived conversations come back here when you archive one.' : 'Use the new message button to start one.'}
            </p>
          </div>
        )}
      </div>
    </div>
  )
}
