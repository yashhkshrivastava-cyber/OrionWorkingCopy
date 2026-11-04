import { useCallback, useEffect, useMemo, useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { MessageCircle, Phone, Users, Video } from 'lucide-react'
import { api } from '../api/client'
import { useAuth } from '../context/AuthContext'
import { useChat, type ChatEvent } from '../context/ChatContext'
import { useDataRefresh } from '../context/DataRefreshContext'
import { ConversationList } from '../components/messages/ConversationList'
import { NewGroupDialog } from '../components/messages/NewGroupDialog'
import { startCall } from '../components/calls/startCall'
import { newClientId, voiceOf } from '../components/messages/format'
import { ThreadView } from '../components/messages/ThreadView'
import { UserAvatar } from '../components/UserAvatar'
import { useToast } from '../components/ui/Toast'
import type { ChatPeer, ChatSearchHit, ChatSettings, ChatThread } from '../types'

const draftsKey = (userId: number) => `orion-chat-drafts:${userId}`

function readDrafts(userId: number): Record<string, string> {
  try {
    const raw = localStorage.getItem(draftsKey(userId))
    return raw ? (JSON.parse(raw) as Record<string, string>) : {}
  } catch {
    return {}
  }
}

function writeDrafts(userId: number, drafts: Record<string, string>) {
  try {
    localStorage.setItem(draftsKey(userId), JSON.stringify(drafts))
  } catch {
    /* the drafts simply do not persist */
  }
}

/**
 * Messages: your conversations on the left, the open one on the right (one at a time on a phone). This page owns the lists,
 * what was typed but not sent, and which conversation is open; the open conversation's messages are `ThreadView`'s.
 */
export function MessagesPage() {
  const { chatId, userId } = useParams()
  const navigate = useNavigate()
  const { user } = useAuth()
  const toast = useToast()
  const { generation } = useDataRefresh()
  const { online, subscribe, isTyping, markLiveRead } = useChat()
  const [people, setPeople] = useState<ChatPeer[]>([])
  const [chats, setChats] = useState<ChatThread[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [drafts, setDrafts] = useState<Record<string, string>>({})
  const [jump, setJump] = useState<{ chatId: number; messageId: number; nonce: number } | null>(null)
  const [groupOpen, setGroupOpen] = useState(false)
  const selectedId = chatId && /^\d+$/.test(chatId) ? Number(chatId) : null
  const composeUserId = userId && /^\d+$/.test(userId) ? Number(userId) : null
  const meId = user?.id ?? 0
  const open = Boolean(selectedId || composeUserId)

  const loadLists = useCallback(() => {
    api.chatDirectory().then(setPeople).catch((err: Error) => setError(err.message))
    api
      .chats()
      .then(setChats)
      .catch((err: Error) => setError(err.message))
      .finally(() => setLoading(false))
  }, [])

  useEffect(() => {
    loadLists()
  }, [loadLists, generation])

  const signedInId = user?.id ?? null
  useEffect(() => {
    if (signedInId !== null) setDrafts(readDrafts(signedInId))
  }, [signedInId])

  useEffect(() => {
    if (typeof Notification === 'undefined') return
    if (Notification.permission === 'default') Notification.requestPermission().catch(() => null)
  }, [])

  // Keep the list in step with what the server says is happening, without asking for it all again.
  useEffect(() => {
    return subscribe((event: ChatEvent) => {
      if (event.type === 'message') {
        const message = event.message
        setChats((current) => {
          const found = current.find((c) => c.id === message.chat_id)
          if (!found) {
            loadLists()
            return current
          }
          const viewing = message.chat_id === selectedId && document.visibilityState === 'visible'
          return current.map((c) =>
            c.id === message.chat_id
              ? {
                  ...c,
                  last_message: message,
                  unread: message.sender_id === meId || viewing ? c.unread : c.unread + 1,
                  settings: { ...c.settings, archived: false },
                }
              : c,
          )
        })
      } else if (event.type === 'message_updated') {
        setChats((current) =>
          current.map((c) => (c.last_message?.id === event.message.id ? { ...c, last_message: event.message } : c)),
        )
        if (event.message.deleted) setChats((current) => current.map((c) => (c.id === event.message.chat_id && c.unread > 0 && c.last_message?.id === event.message.id ? { ...c, unread: c.unread - 1 } : c)))
      } else if (event.type === 'chat_deleted') {
        setChats((current) => current.filter((c) => c.id !== event.chat_id))
        if (event.chat_id === selectedId) navigate('/messages', { replace: true })
      } else if (event.type === 'chat_changed') {
        loadLists() // a group was made, renamed, or somebody joined or left it
      }
    })
  }, [subscribe, selectedId, meId, navigate, loadLists])

  // -- drafts -------------------------------------------------------------------------------------------------------

  const draftKey = selectedId ? `chat:${selectedId}` : composeUserId ? `user:${composeUserId}` : null
  const draft = draftKey ? (drafts[draftKey] ?? '') : ''

  const setDraft = useCallback(
    (key: string | null, text: string) => {
      if (!user || !key) return
      setDrafts((current) => {
        const next = { ...current }
        if (text.trim()) next[key] = text
        else delete next[key]
        writeDrafts(user.id, next)
        return next
      })
    },
    [user],
  )

  const discardDraft = (personId: number) => {
    setDraft(`user:${personId}`, '')
    if (composeUserId === personId) navigate('/messages')
  }

  // -- lists ---------------------------------------------------------------------------------------------------------

  const newPeer = useMemo(() => (composeUserId ? (people.find((p) => p.id === composeUserId) ?? null) : null), [composeUserId, people])

  const openPerson = (personId: number) => {
    const existing = chats.find((c) => c.peer?.id === personId && c.last_message)
    navigate(existing ? `/messages/${existing.id}` : `/messages/new/${personId}`)
  }

  /** A call from the front page of Messages: into the conversation if there is one, otherwise it is made first. */
  const callPerson = async (personId: number, kind: 'voice' | 'video') => {
    const existing = chats.find((c) => c.peer?.id === personId)
    try {
      const chat = existing ?? (await api.startChat(personId))
      startCall(chat.id, kind)
    } catch (err) {
      toast.show('Could not start the call', { tone: 'error', detail: err instanceof Error ? err.message : undefined })
    }
  }

  const openHit = (hit: ChatSearchHit) => {
    setJump({ chatId: hit.chat_id, messageId: hit.id, nonce: Date.now() })
    navigate(`/messages/${hit.chat_id}`)
  }

  const changeSettings = async (chatIdToChange: number, changes: Partial<ChatSettings>) => {
    try {
      const settings = await api.chatSettings(chatIdToChange, changes)
      setChats((current) => current.map((c) => (c.id === chatIdToChange ? { ...c, settings } : c)))
      if (changes.archived === true && chatIdToChange === selectedId) navigate('/messages')
    } catch (err) {
      toast.show('Could not change that', { tone: 'error', detail: err instanceof Error ? err.message : undefined })
    }
  }

  const markRead = (id: number) => {
    markLiveRead(id)
    setChats((current) => current.map((c) => (c.id === id ? { ...c, unread: 0 } : c)))
  }

  /** The first message to someone new: make the conversation, send into it, then open it. */
  const firstSend = async (body: string, file: File | null) => {
    if (!composeUserId) return
    const created = await api.startChat(composeUserId)
    await api.sendChat(created.id, body, file, { clientId: newClientId(), voice: voiceOf(file) })
    setDraft(`user:${composeUserId}`, '')
    loadLists()
    navigate(`/messages/${created.id}`, { replace: true })
  }

  const jumpForThread = jump && jump.chatId === selectedId ? { messageId: jump.messageId, nonce: jump.nonce } : null

  return (
    <div className="chat-shell relative flex h-full min-h-[calc(100dvh-5rem)] overflow-hidden rounded-xl border border-[color:var(--color-border)] bg-surface">
      <div className={`min-h-0 w-full md:w-auto ${open ? 'hidden md:flex' : 'flex'}`}>
        <ConversationList
          chats={chats}
          people={people}
          loading={loading}
          selectedId={selectedId}
          composeUserId={composeUserId}
          meId={meId}
          online={online}
          drafts={drafts}
          typingIn={isTyping}
          onOpenChat={(id) => navigate(`/messages/${id}`)}
          onOpenPerson={openPerson}
          onOpenHit={openHit}
          onSettings={(id, changes) => void changeSettings(id, changes)}
          onMarkRead={markRead}
          onDiscardDraft={discardDraft}
          onNewGroup={() => setGroupOpen(true)}
        />
      </div>

      <div className={`min-h-0 min-w-0 flex-1 ${open ? 'flex' : 'hidden md:flex'}`}>
        {open ? (
          <ThreadView
            key={selectedId ?? `new-${composeUserId}`}
            chatId={selectedId}
            newPeer={newPeer}
            chats={chats}
            people={people}
            draft={draft}
            onDraftChange={(text) => setDraft(draftKey, text)}
            jump={jumpForThread}
            onFirstSend={firstSend}
            onSettingsChanged={(id, settings) => setChats((current) => current.map((c) => (c.id === id ? { ...c, settings } : c)))}
            onRead={(id) => setChats((current) => current.map((c) => (c.id === id && c.unread ? { ...c, unread: 0 } : c)))}
            onDeleted={(id) => {
              setChats((current) => current.filter((c) => c.id !== id))
              navigate('/messages', { replace: true })
              toast.show('Conversation deleted')
            }}
          />
        ) : (
          <div className="scroll-quiet flex min-w-0 flex-1 flex-col overflow-y-auto px-5 py-8 sm:px-8">
            <div className="mx-auto w-full max-w-2xl">
              <section
                className="relative overflow-hidden rounded-[2rem] p-7 text-[color:var(--orion-on-primary)] sm:p-9"
                style={{ backgroundImage: 'var(--orion-highlight-fill)' }}
                aria-label="Welcome to Messages"
              >
                <span className="lumen-orb pointer-events-none absolute -right-12 -top-16 h-60 w-60 rounded-full bg-white/20 blur-2xl" aria-hidden="true" />
                <div className="relative">
                  <span className="inline-flex h-12 w-12 items-center justify-center rounded-2xl bg-white/20">
                    <MessageCircle className="h-6 w-6" aria-hidden="true" />
                  </span>
                  <button type="button" onClick={() => setGroupOpen(true)} className="interactive float-right inline-flex items-center gap-2 rounded-full bg-white/20 px-4 py-2 text-sm font-semibold hover:bg-white/30">
                    <Users className="h-4 w-4" aria-hidden="true" /> New group
                  </button>
                  <h2 className="font-display mt-4 text-3xl font-semibold leading-tight sm:text-4xl">Talk to your team</h2>
                  <p className="mt-2 max-w-md text-sm leading-relaxed opacity-90">
                    Message anyone in Orion, send photos, files and voice notes, or call with sound, video or your screen. Pick a conversation on the left, or start with someone below.
                  </p>
                </div>
              </section>

              {people.length > 0 && (
                <section className="mt-7" aria-label="People to reach">
                  <h3 className="eyebrow mb-3 flex items-center gap-2">
                    {people.some((p) => online.includes(p.id)) && <span className="h-1.5 w-1.5 rounded-full bg-positive" aria-hidden="true" />}
                    {people.some((p) => online.includes(p.id)) ? 'Around now, then everyone else' : 'People'}
                  </h3>
                  <ul className="grid gap-2.5 sm:grid-cols-2">
                    {[...people].sort((a, b) => Number(online.includes(b.id)) - Number(online.includes(a.id))).slice(0, 8).map((person) => (
                      <li key={person.id} className="flex items-center gap-3 rounded-2xl border border-[color:var(--color-border)] bg-surface p-3">
                        <button type="button" onClick={() => openPerson(person.id)} className="interactive flex min-w-0 flex-1 items-center gap-3 rounded-xl text-left" aria-label={`Message ${person.display_name}`}>
                          <span className="relative shrink-0">
                            <UserAvatar user={person} size="row" />
                            {online.includes(person.id) && <span className="absolute bottom-0 right-0 h-3.5 w-3.5 rounded-full border-[2.5px] border-[color:var(--color-surface)] bg-positive" aria-label="Online" />}
                          </span>
                          <span className="min-w-0">
                            <span className="block truncate text-sm font-bold">{person.display_name}</span>
                            <span className="block truncate text-xs text-[color:var(--color-text-muted)]">{online.includes(person.id) ? 'Online now' : 'Offline'}</span>
                          </span>
                        </button>
                        <button type="button" onClick={() => void callPerson(person.id, 'voice')} aria-label={`Voice call ${person.display_name}`} title="Voice call" className="chat-call-button interactive rounded-full bg-accent-dim p-2.5 text-accent hover:bg-muted">
                          <Phone className="h-[18px] w-[18px]" />
                        </button>
                        <button type="button" onClick={() => void callPerson(person.id, 'video')} aria-label={`Video call ${person.display_name}`} title="Video call" className="chat-call-button interactive rounded-full bg-accent-dim p-2.5 text-accent hover:bg-muted">
                          <Video className="h-[18px] w-[18px]" />
                        </button>
                      </li>
                    ))}
                  </ul>
                </section>
              )}
            </div>
          </div>
        )}
      </div>

      <NewGroupDialog
        open={groupOpen}
        people={people}
        onClose={() => setGroupOpen(false)}
        onCreated={(made) => {
          setGroupOpen(false)
          loadLists()
          navigate(`/messages/${made.id}`)
        }}
      />

      {error && (
        <p role="alert" className="absolute bottom-3 left-1/2 -translate-x-1/2 rounded-lg bg-negative px-3 py-1.5 text-xs text-on-negative">
          {error}
        </p>
      )}
    </div>
  )
}
