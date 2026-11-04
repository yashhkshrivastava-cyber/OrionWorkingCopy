import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { api } from '../../api/client'
import { useAuth } from '../../context/AuthContext'
import { useChat, type ChatEvent } from '../../context/ChatContext'
import { useToast } from '../ui/Toast'
import type { ChatMessage, ChatReaction, ChatSettings, ChatThread } from '../../types'
import { kindOf, newClientId, voiceOf } from './format'

/** A message this browser has not had confirmed yet has a negative id, so it sorts after every real one. */
let localSeq = 0
const nextLocalId = () => --localSeq

function byOrder(a: ChatMessage, b: ChatMessage): number {
  const pa = a.id < 0
  const pb = b.id < 0
  if (pa !== pb) return pa ? 1 : -1
  if (pa) return b.id - a.id // pending: the order they were typed (ids count down)
  return a.id - b.id
}

/** Folds incoming messages into the list: the same id replaces, a confirmed send replaces its pending twin. */
export function mergeMessages(current: ChatMessage[], incoming: ChatMessage[]): ChatMessage[] {
  if (!incoming.length) return current
  const next = new Map<number, ChatMessage>()
  const byClient = new Map<string, number>()
  for (const message of current) {
    next.set(message.id, message)
    if (message.client_id && message.id < 0) byClient.set(message.client_id, message.id)
  }
  for (const message of incoming) {
    if (message.client_id && byClient.has(message.client_id)) {
      next.delete(byClient.get(message.client_id)!)
      byClient.delete(message.client_id)
    }
    next.set(message.id, { ...next.get(message.id), ...message, pending: undefined })
  }
  return [...next.values()].sort(byOrder)
}

export type SendInput = { body: string; file?: File | null; replyTo?: ChatMessage | null }

export type ThreadState = ReturnType<typeof useThread>

/**
 * One conversation's messages and everything that can happen to them: paging back through history, sending with a
 * pending, sent or failed state, editing, deleting, reactions, pins, and the live events that change them.
 */
export function useThread(chatId: number | null) {
  const { user } = useAuth()
  const { subscribe, reconnects, markLiveRead } = useChat()
  const toast = useToast()
  const [summary, setSummary] = useState<ChatThread | null>(null)
  const [messages, setMessages] = useState<ChatMessage[]>([])
  const [pins, setPins] = useState<ChatMessage[]>([])
  const [hasMore, setHasMore] = useState(false)
  const [reachesLatest, setReachesLatest] = useState(true)
  const [loading, setLoading] = useState(false)
  const [loadingOlder, setLoadingOlder] = useState(false)
  const [error, setError] = useState('')
  const [peerRead, setPeerRead] = useState(0)
  /** In a group: how far each person has read, kept up to date by what the server says. */
  const [memberReads, setMemberReads] = useState<Record<number, number>>({})
  /** Where the person had read up to when they opened the conversation, to mark what is new. */
  const [readMark, setReadMark] = useState(0)
  const token = useRef(0)
  const live = useRef({ chatId, messages, reachesLatest })
  const atBottom = useRef(true)
  live.current = { chatId, messages, reachesLatest }
  const me = user?.id ?? 0

  const markRead = useCallback(() => {
    if (chatId && document.visibilityState === 'visible') markLiveRead(chatId)
  }, [chatId, markLiveRead])

  // -- opening a conversation -------------------------------------------------------------------------------------

  const load = useCallback(() => {
    if (!chatId) return
    const mine = ++token.current
    setLoading(true)
    setError('')
    api
      .chatThread(chatId)
      .then((thread) => {
        if (mine !== token.current) return
        const { messages: page, has_more, pins: pinned, ...rest } = thread
        setSummary(rest)
        setMessages((current) => mergeMessages(current.filter((m) => m.id < 0 && m.chat_id === chatId), page))
        setHasMore(has_more)
        setReachesLatest(true)
        setPins(pinned)
        setPeerRead(thread.peer_last_read_id)
        setMemberReads({})
        setReadMark(thread.my_last_read_id)
        markRead()
      })
      .catch((err: Error) => {
        if (mine === token.current) setError(err.message)
      })
      .finally(() => {
        if (mine === token.current) setLoading(false)
      })
  }, [chatId, markRead])

  useEffect(() => {
    token.current += 1
    setSummary(null)
    setMessages([])
    setPins([])
    setHasMore(false)
    setReachesLatest(true)
    setError('')
    setPeerRead(0)
    setMemberReads({})
    setReadMark(0)
    atBottom.current = true
    if (chatId) load()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [chatId])

  // -- live events -------------------------------------------------------------------------------------------------

  useEffect(() => {
    if (!chatId) return
    return subscribe((event: ChatEvent) => {
      if (event.type === 'message' && event.message.chat_id === chatId) {
        if (!live.current.reachesLatest) return
        setMessages((current) => mergeMessages(current, [event.message]))
        if (event.message.sender_id !== me && atBottom.current) markRead()
      } else if (event.type === 'message_updated' && event.message.chat_id === chatId) {
        setMessages((current) => mergeMessages(current, [event.message]))
        if (event.message.deleted) setPins((current) => current.filter((p) => p.id !== event.message.id))
        else setPins((current) => current.map((p) => (p.id === event.message.id ? { ...p, ...event.message } : p)))
      } else if (event.type === 'reactions' && event.chat_id === chatId) {
        setMessages((current) => current.map((m) => (m.id === event.message_id ? { ...m, reactions: event.reactions } : m)))
      } else if (event.type === 'read' && event.chat_id === chatId && event.user_id !== me) {
        setPeerRead((value) => Math.max(value, event.last_read_id))
        setMemberReads((current) => ({ ...current, [event.user_id]: Math.max(current[event.user_id] ?? 0, event.last_read_id) }))
      } else if (event.type === 'pins' && event.chat_id === chatId) {
        setPins(event.pins)
      } else if (event.type === 'chat_changed' && event.chat_id === chatId) {
        // Somebody joined, left, was made an admin or the group was renamed: fetch who is in it now.
        api
          .chatThread(chatId)
          .then((fresh) => {
            if (live.current.chatId !== chatId) return
            const { messages: _messages, has_more: _more, pins: pinned, ...rest } = fresh
            setSummary(rest)
            setPins(pinned)
            setMemberReads({})
          })
          .catch(() => null) // the next change, or the next time it is opened, brings it up to date
      }
    })
  }, [chatId, subscribe, me, markRead])

  // Coming back to the window with the conversation open and at its end: what arrived meanwhile has now been seen.
  useEffect(() => {
    if (!chatId) return
    const seen = () => {
      if (document.visibilityState === 'visible' && atBottom.current) markRead()
    }
    document.addEventListener('visibilitychange', seen)
    window.addEventListener('focus', seen)
    return () => {
      document.removeEventListener('visibilitychange', seen)
      window.removeEventListener('focus', seen)
    }
  }, [chatId, markRead])

  // After a dropped connection, fetch whatever arrived while it was down.
  useEffect(() => {
    if (!chatId || !reconnects) return
    const lastReal = [...live.current.messages].reverse().find((m) => m.id > 0)?.id ?? 0
    if (!live.current.reachesLatest) return
    api
      .chatPage(chatId, lastReal ? { after: lastReal } : {})
      .then((page) => {
        if (live.current.chatId !== chatId) return
        setMessages((current) => mergeMessages(current, page.messages))
        if (page.messages.length && atBottom.current) markRead()
      })
      .catch(() => null)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [reconnects])

  // -- history -----------------------------------------------------------------------------------------------------

  const loadOlder = useCallback(async () => {
    if (!chatId || loadingOlder || !hasMore) return
    const oldest = messages.find((m) => m.id > 0)?.id
    if (!oldest) return
    setLoadingOlder(true)
    try {
      const page = await api.chatPage(chatId, { before: oldest })
      if (live.current.chatId !== chatId) return
      setMessages((current) => mergeMessages(current, page.messages))
      setHasMore(page.has_more)
    } catch (err) {
      toast.show('Could not load earlier messages', { tone: 'error', detail: err instanceof Error ? err.message : undefined })
    } finally {
      setLoadingOlder(false)
    }
  }, [chatId, loadingOlder, hasMore, messages, toast])

  /** Brings a message into view even if it is far back, loading the stretch around it. Resolves false if it is gone. */
  const jumpTo = useCallback(
    async (messageId: number): Promise<boolean> => {
      if (!chatId) return false
      if (live.current.messages.some((m) => m.id === messageId)) return true
      try {
        const page = await api.chatPage(chatId, { around: messageId })
        if (live.current.chatId !== chatId) return false
        setMessages((current) => mergeMessages(current.filter((m) => m.id < 0), page.messages))
        setHasMore(page.has_more)
        setReachesLatest(Boolean(page.reaches_latest))
        return page.messages.some((m) => m.id === messageId)
      } catch (err) {
        toast.show('Could not find that message', { tone: 'error', detail: err instanceof Error ? err.message : undefined })
        return false
      }
    },
    [chatId, toast],
  )

  const jumpToLatest = useCallback(() => {
    if (!reachesLatest) load()
  }, [reachesLatest, load])

  // -- sending -----------------------------------------------------------------------------------------------------

  const patchPending = useCallback((localId: number, patch: Partial<NonNullable<ChatMessage['pending']>>) => {
    setMessages((current) =>
      current.map((m) => (m.id === localId && m.pending ? { ...m, pending: { ...m.pending, ...patch } } : m)),
    )
  }, [])

  const transmit = useCallback(
    (message: ChatMessage, replyTo: number | null) => {
      const file = message.pending?.file ?? null
      const localId = message.id
      patchPending(localId, { state: 'sending', progress: file ? 0 : undefined, error: undefined })
      api
        .sendChat(message.chat_id, message.body, file, {
          replyTo,
          clientId: message.client_id || undefined,
          voice: voiceOf(file),
          onProgress: (fraction) => patchPending(localId, { progress: fraction }),
        })
        .then((saved) => {
          setMessages((current) => mergeMessages(current, [{ ...saved, client_id: message.client_id }]))
          window.dispatchEvent(new CustomEvent('orion-chat-message', { detail: saved }))
        })
        .catch((err: Error) => patchPending(localId, { state: 'failed', error: err.message, progress: undefined }))
    },
    [patchPending],
  )

  const send = useCallback(
    ({ body, file, replyTo }: SendInput) => {
      if (!chatId || !me) return
      const text = body.trim()
      if (!text && !file) return
      const pending: ChatMessage = {
        id: nextLocalId(),
        chat_id: chatId,
        sender_id: me,
        body: text,
        created_timestamp: new Date().toISOString(),
        client_id: newClientId(),
        reply_to: replyTo
          ? {
              id: replyTo.id,
              sender_id: replyTo.sender_id,
              body: replyTo.body.slice(0, 140),
              media_kind: replyTo.media_kind,
              media_name: replyTo.media_name,
              deleted: false,
            }
          : null,
        media_kind: file ? kindOf(file) : null,
        media_name: file?.name ?? null,
        media_size: file?.size ?? null,
        media_duration_ms: voiceOf(file)?.durationMs ?? null,
        media_waveform: voiceOf(file)?.waveform ?? [],
        reactions: [],
        pending: { state: 'sending', file: file ?? null },
      }
      setMessages((current) => mergeMessages(current, [pending]))
      transmit(pending, replyTo?.id ?? null)
    },
    [chatId, me, transmit],
  )

  const retry = useCallback(
    (localId: number) => {
      const message = live.current.messages.find((m) => m.id === localId)
      if (message?.pending) transmit(message, message.reply_to?.id ?? null)
    },
    [transmit],
  )

  const discard = useCallback((localId: number) => {
    setMessages((current) => current.filter((m) => m.id !== localId))
  }, [])

  // -- changing a message ----------------------------------------------------------------------------------------

  const fail = useCallback((what: string, err: unknown) => {
    toast.show(what, { tone: 'error', detail: err instanceof Error ? err.message : undefined })
  }, [toast])

  const edit = useCallback(
    async (messageId: number, body: string) => {
      try {
        const saved = await api.editChatMessage(messageId, body)
        setMessages((current) => mergeMessages(current, [saved]))
        toast.show('Message edited')
        return true
      } catch (err) {
        fail('Could not edit the message', err)
        return false
      }
    },
    [toast, fail],
  )

  const remove = useCallback(
    async (messageId: number) => {
      try {
        const saved = await api.deleteChatMessage(messageId)
        setMessages((current) => mergeMessages(current, [saved]))
        setPins((current) => current.filter((p) => p.id !== messageId))
        toast.show('Message deleted')
      } catch (err) {
        fail('Could not delete the message', err)
      }
    },
    [toast, fail],
  )

  const react = useCallback(
    async (messageId: number, emoji: string) => {
      const before = live.current.messages.find((m) => m.id === messageId)?.reactions ?? []
      const toggle = (reactions: ChatReaction[]): ChatReaction[] => {
        const found = reactions.find((r) => r.emoji === emoji)
        if (!found) return [...reactions, { emoji, user_ids: [me] }]
        const has = found.user_ids.includes(me)
        const ids = has ? found.user_ids.filter((id) => id !== me) : [...found.user_ids, me]
        return reactions.map((r) => (r.emoji === emoji ? { ...r, user_ids: ids } : r)).filter((r) => r.user_ids.length)
      }
      setMessages((current) => current.map((m) => (m.id === messageId ? { ...m, reactions: toggle(m.reactions ?? []) } : m)))
      try {
        const result = await api.reactToChatMessage(messageId, emoji)
        setMessages((current) => current.map((m) => (m.id === messageId ? { ...m, reactions: result.reactions } : m)))
      } catch (err) {
        setMessages((current) => current.map((m) => (m.id === messageId ? { ...m, reactions: before } : m)))
        fail('Could not add the reaction', err)
      }
    },
    [me, fail],
  )

  const pin = useCallback(
    async (messageId: number, pinned: boolean) => {
      if (!chatId) return
      try {
        const result = await api.pinChatMessage(chatId, messageId, pinned)
        setPins(result.pins)
        toast.show(pinned ? 'Message pinned' : 'Message unpinned')
      } catch (err) {
        fail(pinned ? 'Could not pin the message' : 'Could not unpin the message', err)
      }
    },
    [chatId, toast, fail],
  )

  const updateSettings = useCallback(
    async (changes: Partial<ChatSettings>) => {
      if (!chatId) return null
      try {
        const settings = await api.chatSettings(chatId, changes)
        setSummary((s) => (s ? { ...s, settings } : s))
        return settings
      } catch (err) {
        fail('Could not change that setting', err)
        return null
      }
    },
    [chatId, fail],
  )

  const setAtBottom = useCallback(
    (value: boolean) => {
      atBottom.current = value
      if (value) markRead()
    },
    [markRead],
  )

  const lastMine = useMemo(() => [...messages].reverse().find((m) => m.sender_id === me && m.id > 0 && !m.deleted), [messages, me])

  // A message in a group is read for its sender when everybody else has read it: the one who has read least decides.
  const groupPeerRead = useMemo(() => {
    if (summary?.kind !== 'group') return peerRead
    const others = summary.members.filter((m) => m.id !== me)
    if (!others.length) return 0
    return Math.min(...others.map((m) => Math.max(m.last_read_id, memberReads[m.id] ?? 0)))
  }, [summary, peerRead, memberReads, me])

  return {
    summary,
    messages,
    pins,
    hasMore,
    reachesLatest,
    loading,
    loadingOlder,
    error,
    peerRead: groupPeerRead,
    readMark,
    lastMine,
    reload: load,
    loadOlder,
    jumpTo,
    jumpToLatest,
    send,
    retry,
    discard,
    edit,
    remove,
    react,
    pin,
    updateSettings,
    setAtBottom,
    markRead,
  }
}
