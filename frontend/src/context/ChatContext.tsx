import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState, type ReactNode } from 'react'
import { api } from '../api/client'
import type { CallRing, ChatMessage, ChatPeer } from '../types'
import { useAuth } from './AuthContext'
import { useDataRefresh } from './DataRefreshContext'

type Incoming = {
  message: ChatMessage
  senderName: string
}

/** Everything the server pushes about conversations. A page subscribes and picks out the events it cares about. */
export type ChatEvent =
  | { type: 'message'; message: ChatMessage; sender?: { id: number; display_name: string }; muted?: boolean }
  | { type: 'message_updated'; message: ChatMessage }
  | { type: 'reactions'; chat_id: number; message_id: number; reactions: ChatMessage['reactions'] }
  | { type: 'read'; chat_id: number; user_id: number; last_read_id: number }
  | { type: 'pins'; chat_id: number; pins: ChatMessage[] }
  | { type: 'typing'; chat_id: number; user_id: number }
  | { type: 'chat_deleted'; chat_id: number }
  | { type: 'chat_changed'; chat_id: number }
  | { type: 'error'; message: string; chat_id?: number; client_id?: string }
  | CallEvent

/** What the server says about a call (see calls.py). The call itself is run by `components/calls/CallHost`. */
export type CallEvent =
  | { type: 'call_started'; call: CallRing; peer: ChatPeer }
  | { type: 'call_ring'; call: CallRing }
  | { type: 'call_accepted'; call_id: number; by: number }
  | { type: 'call_signal'; call_id: number; from: number; data: Record<string, unknown> }
  | { type: 'call_ended'; call_id: number; chat_id: number; outcome: string; reason?: string | null; peer?: ChatPeer }
  | { type: 'call_error'; message: string; chat_id?: number; call_id?: number }

const CALL_EVENTS = ['call_started', 'call_ring', 'call_accepted', 'call_signal', 'call_ended', 'call_error']

type ChatContextValue = {
  unread: number
  online: number[]
  incoming: Incoming | null
  connected: boolean
  /** Goes up every time the connection is re-made after a drop, so a page knows to fetch what it missed. */
  reconnects: number
  subscribe: (listener: (event: ChatEvent) => void) => () => void
  /** Whether this person is typing in a conversation right now. */
  isTyping: (chatId: number, userId: number) => boolean
  sendTyping: (chatId: number) => void
  sendLive: (chatId: number, body: string) => void
  /** Sends one message over the socket (a call's set-up, mostly). False when the connection is not open. */
  sendSocket: (payload: Record<string, unknown>) => boolean
  markLiveRead: (chatId: number) => void
  clearIncoming: () => void
}

const ChatContext = createContext<ChatContextValue | null>(null)

function socketUrl() {
  const proto = window.location.protocol === 'https:' ? 'wss' : 'ws'
  return `${proto}://${window.location.host}/api/messages/ws`
}

export function messagePreview(
  message?: Pick<ChatMessage, 'body' | 'media_kind' | 'media_name' | 'deleted' | 'call'> | null,
) {
  if (!message) return 'No messages yet'
  if (message.deleted) return 'This message was deleted'
  if (message.call) return message.call.kind === 'video' ? 'Video call' : 'Voice call'
  const body = (message.body || '').trim()
  if (body) return body
  if (message.media_kind === 'image') return 'Photo'
  if (message.media_kind === 'video') return 'Video'
  if (message.media_kind === 'audio') return 'Voice note'
  if (message.media_kind === 'file') return message.media_name || 'File'
  return 'No messages yet'
}

function notifyBrowser(title: string, body: string) {
  if (typeof Notification === 'undefined') return
  if (Notification.permission !== 'granted') return
  if (!document.hidden) return
  try {
    new Notification(title, { body, icon: '/favicon.ico' })
  } catch {
    /* ignored */
  }
}

const TYPING_SHOWN_MS = 4500

export function ChatProvider({ children }: { children: ReactNode }) {
  const { user } = useAuth()
  const userId = user?.id ?? null // the effects below depend on WHO is signed in, not on the user object, which is a new one after every profile refresh
  const { generation } = useDataRefresh()
  const [unread, setUnread] = useState(0)
  const [online, setOnline] = useState<number[]>([])
  const [incoming, setIncoming] = useState<Incoming | null>(null)
  const [connected, setConnected] = useState(false)
  const [reconnects, setReconnects] = useState(0)
  const [typing, setTyping] = useState<Record<string, number>>({})
  const socket = useRef<WebSocket | null>(null)
  const listeners = useRef(new Set<(event: ChatEvent) => void>())
  const lastTypingSent = useRef(0)
  const opened = useRef(false)

  useEffect(() => {
    if (userId === null) {
      setUnread(0)
      return
    }
    api.chatUnread().then((data) => setUnread(data.count)).catch(() => null)
  }, [userId, generation])

  // A typing indicator that is not refreshed fades by itself, so a dropped "stopped typing" can never leave it stuck.
  useEffect(() => {
    const keys = Object.keys(typing)
    if (!keys.length) return
    const next = Math.min(...keys.map((key) => typing[key])) - Date.now()
    const timer = window.setTimeout(() => {
      const now = Date.now()
      setTyping((current) => Object.fromEntries(Object.entries(current).filter(([, until]) => until > now)))
    }, Math.max(next, 50) + 20)
    return () => window.clearTimeout(timer)
  }, [typing])

  useEffect(() => {
    if (userId === null) {
      setConnected(false)
      return
    }

    let closed = false
    let retry: number | undefined
    let delay = 1500
    const connect = () => {
      const ws = new WebSocket(socketUrl())
      socket.current = ws
      ws.onopen = () => {
        if (closed) return
        delay = 1500
        setConnected(true)
        if (opened.current) setReconnects((n) => n + 1)
        opened.current = true
      }
      ws.onmessage = (event) => {
        try {
          const data = JSON.parse(event.data)
          if (data.type === 'unread') setUnread(Number(data.count) || 0)
          if (data.type === 'presence') setOnline(Array.isArray(data.online) ? data.online : [])
          if (data.type === 'typing' && data.chat_id && data.user_id) {
            setTyping((current) => ({ ...current, [`${data.chat_id}:${data.user_id}`]: Date.now() + TYPING_SHOWN_MS }))
          }
          if (data.type === 'message' && data.message) {
            const message = data.message as ChatMessage
            // Having sent something ends "typing" at once.
            setTyping((current) => {
              const key = `${message.chat_id}:${message.sender_id}`
              if (!(key in current)) return current
              const { [key]: _gone, ...rest } = current
              return rest
            })
            window.dispatchEvent(new CustomEvent('orion-chat-message', { detail: message }))
            if (message.sender_id !== userId && !data.muted) {
              const name = data.sender?.display_name || 'New message'
              const viewing = window.location.pathname === `/messages/${message.chat_id}`
              if (!viewing) setIncoming({ message, senderName: name })
              notifyBrowser(name, messagePreview(message))
            }
          }
          if (data.type === 'chat_deleted' && data.chat_id) {
            const chatId = Number(data.chat_id)
            window.dispatchEvent(new CustomEvent('orion-chat-deleted', { detail: chatId }))
            setIncoming((current) => (current?.message.chat_id === chatId ? null : current))
          }
          if (['message', 'message_updated', 'reactions', 'read', 'pins', 'typing', 'chat_deleted', 'chat_changed', 'error', ...CALL_EVENTS].includes(data.type)) {
            listeners.current.forEach((listener) => listener(data as ChatEvent))
          }
        } catch {
          /* ignore */
        }
      }
      ws.onclose = () => {
        // An older socket closing late (React remounts the provider in development) must not clear the newer one.
        if (socket.current !== ws) return
        setConnected(false)
        socket.current = null
        if (!closed) {
          retry = window.setTimeout(connect, delay)
          delay = Math.min(delay * 2, 15000)
        }
      }
    }
    connect()
    return () => {
      closed = true
      opened.current = false
      if (retry) window.clearTimeout(retry)
      socket.current?.close()
      socket.current = null
    }
  }, [userId])

  const subscribe = useCallback((listener: (event: ChatEvent) => void) => {
    listeners.current.add(listener)
    return () => {
      listeners.current.delete(listener)
    }
  }, [])

  const isTyping = useCallback(
    (chatId: number, userId: number) => (typing[`${chatId}:${userId}`] ?? 0) > Date.now(),
    [typing],
  )

  const sendTyping = useCallback((chatId: number) => {
    const now = Date.now()
    if (now - lastTypingSent.current < 3000) return
    const ws = socket.current
    if (ws && ws.readyState === WebSocket.OPEN) {
      lastTypingSent.current = now
      ws.send(JSON.stringify({ type: 'typing', chat_id: chatId }))
    }
  }, [])

  const sendLive = useCallback((chatId: number, body: string) => {
    const ws = socket.current
    if (ws && ws.readyState === WebSocket.OPEN) {
      ws.send(JSON.stringify({ type: 'send', chat_id: chatId, body }))
      return
    }
    api.sendChat(chatId, body).catch(() => null)
  }, [])

  const sendSocket = useCallback((payload: Record<string, unknown>) => {
    const ws = socket.current
    if (!ws || ws.readyState !== WebSocket.OPEN) return false
    ws.send(JSON.stringify(payload))
    return true
  }, [])

  const markLiveRead = useCallback((chatId: number) => {
    const ws = socket.current
    if (ws && ws.readyState === WebSocket.OPEN) {
      ws.send(JSON.stringify({ type: 'read', chat_id: chatId }))
      return
    }
    api.readChat(chatId).then((data) => setUnread(data.count)).catch(() => null)
  }, [])

  const value = useMemo(
    () => ({
      unread,
      online,
      incoming,
      connected,
      reconnects,
      subscribe,
      isTyping,
      sendTyping,
      sendLive,
      sendSocket,
      markLiveRead,
      clearIncoming: () => setIncoming(null),
    }),
    [unread, online, incoming, connected, reconnects, subscribe, isTyping, sendTyping, sendLive, sendSocket, markLiveRead],
  )

  return <ChatContext.Provider value={value}>{children}</ChatContext.Provider>
}

export function useChat(): ChatContextValue {
  const context = useContext(ChatContext)
  if (!context) throw new Error('useChat must be used within ChatProvider')
  return context
}
