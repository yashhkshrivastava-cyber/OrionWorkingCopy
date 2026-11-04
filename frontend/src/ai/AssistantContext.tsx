import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState, type ReactNode } from 'react'
import { useLocation, useNavigate } from 'react-router-dom'
import { aiApi } from '../api/client'
import { useAppearance } from '../context/AppearanceContext'
import { useAuth } from '../context/AuthContext'
import type { AiCategory, AiConversation, AiEvent, AiInsight, AiMessage, AiPageContext, AiStatus, AiUiAction } from '../types'
import { contextFromLocation } from './pageContext'
import { applyEvent, emptyAssistant, plainText, present, userMessage, withAction } from './transcript'

/*
 * The Copilot's conversation layer. It knows nothing about how the panel looks: the screens call `send`, `stop`,
 * `confirm` and so on, and read `messages`, `streaming` and the rest. Everything the model can see or do is decided on
 * the server; this layer only carries the person's questions there and draws what comes back.
 */

type Failure = { message: string; retryable: boolean }

type AssistantValue = {
  /** The person may use the Copilot at all (their account has it and they have not switched it off). */
  enabled: boolean
  status: AiStatus | null
  reloadStatus: () => Promise<void>

  open: boolean
  setOpen: (open: boolean) => void
  toggle: () => void
  wide: boolean
  setWide: (wide: boolean) => void
  screen: 'chat' | 'history'
  setScreen: (screen: 'chat' | 'history') => void
  paletteOpen: boolean
  setPaletteOpen: (open: boolean) => void

  messages: AiMessage[]
  activeId: number | null
  title: string
  streaming: boolean
  failure: Failure | null
  dismissFailure: () => void
  loadingConversation: boolean

  send: (text: string) => void
  /** Starts a new conversation about something, with the current page as context, and opens the panel. */
  ask: (text: string) => void
  stop: () => void
  regenerate: () => void
  retry: () => void
  /** Asks the last question again with cloud AI, because the person chose it for this one question. */
  askWithCloud: () => void
  newChat: () => void
  openConversation: (id: number) => Promise<void>
  confirmAction: (actionId: string) => Promise<void>
  cancelAction: (actionId: string) => Promise<void>

  conversations: AiConversation[]
  loadConversations: (query?: string, category?: AiCategory | '') => Promise<void>
  renameConversation: (id: number, title: string) => Promise<void>
  setCategory: (id: number, category: AiCategory) => Promise<void>
  deleteConversation: (id: number) => Promise<void>

  insights: AiInsight[]
  dismissInsight: (id: string, days?: number) => void
  suggestions: string[]

  /** What would be sent as the page context with the next question. */
  pageContext: AiPageContext
  shareContext: boolean
  setShareContext: (share: boolean) => void
  /** A page with more to say (an open record, selected rows) adds it here; returns how to take it back. */
  registerPage: (extra: Partial<AiPageContext>) => () => void
}

const AssistantContext = createContext<AssistantValue | null>(null)

const OPEN_KEY = 'orion-ai-open'
const WIDE_KEY = 'orion-ai-wide'

function remembered(key: string): boolean {
  try {
    return localStorage.getItem(key) === '1'
  } catch {
    return false
  }
}

function remember(key: string, value: boolean) {
  try {
    localStorage.setItem(key, value ? '1' : '0')
  } catch {
    /* it just will not be remembered next visit */
  }
}

export function AssistantProvider({ children }: { children: ReactNode }) {
  const { user } = useAuth()
  const location = useLocation()
  const navigate = useNavigate()
  const appearance = useAppearance()

  const [status, setStatus] = useState<AiStatus | null>(null)
  // On a phone the panel covers the page, so it never reopens by itself; beside the page on a wide screen it does.
  const [open, setOpenState] = useState(() => remembered(OPEN_KEY) && window.matchMedia('(min-width: 1024px)').matches)
  const [wide, setWideState] = useState(() => remembered(WIDE_KEY))
  const [screen, setScreen] = useState<'chat' | 'history'>('chat')
  const [paletteOpen, setPaletteOpen] = useState(false)

  const [messages, setMessages] = useState<AiMessage[]>([])
  const [activeId, setActiveId] = useState<number | null>(null)
  const [title, setTitle] = useState('')
  const [streaming, setStreaming] = useState(false)
  const [failure, setFailure] = useState<Failure | null>(null)
  const [loadingConversation, setLoadingConversation] = useState(false)
  const [conversations, setConversations] = useState<AiConversation[]>([])
  const [insights, setInsights] = useState<AiInsight[]>([])
  const [suggestions, setSuggestions] = useState<string[]>([])
  const [shareContext, setShareContext] = useState(true)
  const [extra, setExtra] = useState<{ path: string; data: Partial<AiPageContext> }>({ path: '', data: {} })
  const pathRef = useRef(location.pathname)
  pathRef.current = location.pathname

  const abort = useRef<AbortController | null>(null)
  const messagesRef = useRef(messages)
  messagesRef.current = messages
  const activeRef = useRef(activeId)
  activeRef.current = activeId
  const streamingRef = useRef(false)

  const allowed = Boolean(user?.can_ai)
  const enabled = allowed && status !== null && status.settings.enabled

  // ------------------------------------------------------------------------------------------------- status

  const reloadStatus = useCallback(async () => {
    try {
      setStatus(await aiApi.status())
    } catch {
      setStatus(null)
    }
  }, [])

  useEffect(() => {
    if (!allowed) {
      setStatus(null)
      return
    }
    void reloadStatus()
  }, [allowed, reloadStatus, user?.id])

  // Signing out or in as someone else must never show the last person's conversation.
  useEffect(() => {
    abort.current?.abort()
    setMessages([])
    setActiveId(null)
    setTitle('')
    setConversations([])
    setInsights([])
    setFailure(null)
    setStreaming(false)
    streamingRef.current = false
  }, [user?.id])

  // ------------------------------------------------------------------------------------------------ context

  const pageContext = useMemo<AiPageContext>(
    () => ({ ...contextFromLocation(location.pathname, location.search), ...(extra.path === location.pathname ? extra.data : {}) }),
    [location.pathname, location.search, extra],
  )
  const contextRef = useRef(pageContext)
  contextRef.current = pageContext
  const shareRef = useRef(shareContext)
  shareRef.current = shareContext

  // What a page says about itself belongs to that page only, so it is filed under the address it was said at.
  const registerPage = useCallback((added: Partial<AiPageContext>) => {
    const path = pathRef.current
    setExtra((current) => ({ path, data: { ...(current.path === path ? current.data : {}), ...added } }))
    return () =>
      setExtra((current) => {
        if (current.path !== path) return current
        const data = { ...current.data }
        for (const key of Object.keys(added)) delete data[key as keyof AiPageContext]
        return { path, data }
      })
  }, [])

  // --------------------------------------------------------------------------------------------- open / close

  const setOpen = useCallback((next: boolean) => {
    setOpenState(next)
    remember(OPEN_KEY, next)
  }, [])
  const toggle = useCallback(() => setOpen(!open), [open, setOpen])
  const setWide = useCallback((next: boolean) => {
    setWideState(next)
    remember(WIDE_KEY, next)
  }, [])

  useEffect(() => {
    if (!enabled) return
    const onKey = (event: KeyboardEvent) => {
      if (!(event.ctrlKey || event.metaKey) || event.altKey || event.shiftKey) return
      const key = event.key.toLowerCase()
      if (key === 'k') {
        event.preventDefault()
        setPaletteOpen((value) => !value)
      } else if (key === 'j') {
        event.preventDefault()
        setOpenState((value) => {
          remember(OPEN_KEY, !value)
          return !value
        })
      }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [enabled])

  // ------------------------------------------------------------------------------- insights and suggestions

  const loadInsights = useCallback(async () => {
    if (!enabled || !status?.settings.show_insights) {
      setInsights([])
      return
    }
    try {
      setInsights((await aiApi.insights()).insights)
    } catch {
      setInsights([])
    }
  }, [enabled, status?.settings.show_insights])

  useEffect(() => {
    if (open && enabled) void loadInsights()
  }, [open, enabled, loadInsights])

  const dismissInsight = useCallback((id: string, days = 7) => {
    setInsights((current) => current.filter((item) => item.id !== id))
    void aiApi.dismissInsight(id, days).catch(() => undefined)
  }, [])

  const contextKey = `${pageContext.area}|${pageContext.view ?? ''}|${pageContext.filters ? 'f' : ''}`
  useEffect(() => {
    if (!open || !enabled) return
    let cancelled = false
    aiApi
      .suggestions(contextRef.current)
      .then((result) => !cancelled && setSuggestions(result.suggestions))
      .catch(() => !cancelled && setSuggestions([]))
    return () => {
      cancelled = true
    }
  }, [open, enabled, contextKey])

  // ---------------------------------------------------------------------------------------- conversations

  const loadConversations = useCallback(async (query = '', category: AiCategory | '' = '') => {
    try {
      setConversations((await aiApi.conversations(query, category)).conversations)
    } catch {
      setConversations([])
    }
  }, [])

  const newChat = useCallback(() => {
    abort.current?.abort()
    streamingRef.current = false
    setStreaming(false)
    setMessages([])
    setActiveId(null)
    setTitle('')
    setFailure(null)
    setScreen('chat')
  }, [])

  const openConversation = useCallback(async (id: number) => {
    abort.current?.abort()
    streamingRef.current = false
    setStreaming(false)
    setFailure(null)
    setLoadingConversation(true)
    setScreen('chat')
    try {
      const found = await aiApi.conversation(id)
      setMessages(present(found.messages))
      setActiveId(id)
      setTitle(found.conversation.title)
    } catch (err) {
      setFailure({ message: err instanceof Error ? err.message : 'That conversation could not be opened.', retryable: false })
    } finally {
      setLoadingConversation(false)
    }
  }, [])

  const renameConversation = useCallback(
    async (id: number, name: string) => {
      await aiApi.renameConversation(id, { title: name })
      if (activeRef.current === id) setTitle(name)
      setConversations((current) => current.map((item) => (item.id === id ? { ...item, title: name } : item)))
    },
    [],
  )

  const setCategory = useCallback(async (id: number, category: AiCategory) => {
    await aiApi.renameConversation(id, { category })
    setConversations((current) => current.map((item) => (item.id === id ? { ...item, category } : item)))
  }, [])

  const deleteConversation = useCallback(
    async (id: number) => {
      await aiApi.deleteConversation(id)
      setConversations((current) => current.filter((item) => item.id !== id))
      if (activeRef.current === id) newChat()
    },
    [newChat],
  )

  // -------------------------------------------------------------------------------------------- asking

  const runUiAction = useCallback(
    (action: AiUiAction) => {
      if (action.type === 'navigate') {
        if (action.path.startsWith('/') && !action.path.startsWith('//')) navigate(action.path)
      } else if (action.type === 'appearance') {
        if (action.theme) appearance.selectTheme(action.theme)
        if (action.mode) appearance.update({ mode: action.mode }, { fade: true })
      }
    },
    [navigate, appearance],
  )

  /** Runs one question to the end, filling the last (assistant) message as events arrive. */
  const stream = useCallback(
    async (body: { message: string; regenerate?: boolean; cloudOnce?: boolean; history?: { role: 'user' | 'assistant'; text: string }[] }) => {
      const controller = new AbortController()
      abort.current = controller
      streamingRef.current = true
      setStreaming(true)
      setFailure(null)
      let failed: Failure | null = null
      const onEvent = (event: AiEvent) => {
        if (controller.signal.aborted) return
        if (event.type === 'conversation') {
          setActiveId(event.id)
          setTitle(event.title)
          setConversations((current) => [
            { id: event.id, title: event.title, category: event.category, created_timestamp: new Date().toISOString(), updated_timestamp: new Date().toISOString() },
            ...current.filter((item) => item.id !== event.id),
          ])
          return
        }
        if (event.type === 'error') {
          failed = { message: event.message, retryable: event.retryable !== false && event.code !== 'daily' && event.code !== 'not_configured' }
          return
        }
        if (event.type === 'ui') runUiAction(event.action)
        if (event.type === 'done') {
          void loadConversationsQuiet()
        }
        setMessages((current) => {
          const last = current[current.length - 1]
          if (!last || last.role !== 'assistant') return current
          return [...current.slice(0, -1), applyEvent(last, event)]
        })
      }
      const loadConversationsQuiet = async () => {
        try {
          setConversations((await aiApi.conversations()).conversations)
        } catch {
          /* the list refreshes next time it is opened */
        }
      }
      try {
        await aiApi.chat(
          {
            message: body.message,
            conversation_id: activeRef.current,
            context: shareRef.current ? contextRef.current : undefined,
            regenerate: body.regenerate,
            cloud_once: body.cloudOnce,
            history: body.history,
          },
          onEvent,
          controller.signal,
        )
      } finally {
        if (controller.signal.aborted) {
          setMessages((current) => {
            const last = current[current.length - 1]
            return last && last.role === 'assistant' ? [...current.slice(0, -1), { ...last, parts: [...last.parts, { type: 'stopped' }] }] : current
          })
        }
        if (failed) {
          setFailure(failed)
          // An answer that never began leaves nothing worth keeping: just the question and the error.
          setMessages((current) => {
            const last = current[current.length - 1]
            return last && last.role === 'assistant' && last.parts.length === 0 ? current.slice(0, -1) : current
          })
        }
        streamingRef.current = false
        setStreaming(false)
        abort.current = null
        void reloadStatus()
      }
    },
    [runUiAction, reloadStatus],
  )

  /** Earlier turns as plain text, sent only when the person keeps no history on the server. */
  const historyForServer = useCallback(
    (upTo: AiMessage[]) =>
      status?.settings.keep_history === false
        ? upTo.filter((m) => plainText(m)).map((m) => ({ role: m.role, text: plainText(m) }))
        : undefined,
    [status?.settings.keep_history],
  )

  const send = useCallback(
    (raw: string) => {
      const text = raw.trim()
      if (!text || streamingRef.current || !enabled) return
      const before = messagesRef.current
      setMessages([...before, userMessage(text), emptyAssistant()])
      setOpen(true)
      setScreen('chat')
      void stream({ message: text, history: historyForServer(before) })
    },
    [enabled, setOpen, stream, historyForServer],
  )

  const ask = useCallback(
    (text: string) => {
      if (streamingRef.current) return
      setMessages([])
      setActiveId(null)
      activeRef.current = null
      setTitle('')
      messagesRef.current = []
      setShareContext(true)
      shareRef.current = true
      send(text)
    },
    [send],
  )

  const stop = useCallback(() => abort.current?.abort(), [])

  const regenerate = useCallback((cloudOnce = false) => {
    if (streamingRef.current) return
    const current = messagesRef.current
    let end = current.length
    while (end > 0 && current[end - 1].role === 'assistant') end -= 1
    const lastUser = current[end - 1]
    if (!lastUser) return
    const kept = current.slice(0, end)
    setMessages([...kept, emptyAssistant()])
    const earlier = kept.slice(0, -1)
    if (activeRef.current === null) void stream({ message: plainText(lastUser), cloudOnce, history: historyForServer(earlier) })
    else void stream({ message: '', regenerate: true, cloudOnce })
  }, [stream, historyForServer])

  const retry = useCallback(() => regenerate(false), [regenerate])
  const askWithCloud = useCallback(() => regenerate(true), [regenerate])

  // -------------------------------------------------------------------------------------- confirmations

  const patchAction = useCallback((actionId: string, change: Parameters<typeof withAction>[2]) => {
    setMessages((current) => current.map((message) => withAction(message, actionId, change)))
  }, [])

  const confirmAction = useCallback(
    async (actionId: string) => {
      patchAction(actionId, { status: 'confirming' })
      try {
        const done = await aiApi.confirmAction(actionId)
        patchAction(actionId, { status: 'done', result: done.summary })
        void loadInsights()
      } catch (err) {
        const message = err instanceof Error ? err.message : 'That could not be done.'
        patchAction(actionId, { status: /expired|already handled/i.test(message) ? 'expired' : 'failed', result: message })
      }
    },
    [patchAction, loadInsights],
  )

  const cancelAction = useCallback(
    async (actionId: string) => {
      try {
        await aiApi.cancelAction(actionId)
        patchAction(actionId, { status: 'cancelled', result: 'Cancelled. Nothing was changed.' })
      } catch (err) {
        patchAction(actionId, { status: 'expired', result: err instanceof Error ? err.message : 'This has expired.' })
      }
    },
    [patchAction],
  )

  const value = useMemo<AssistantValue>(
    () => ({
      enabled,
      status,
      reloadStatus,
      open: open && enabled,
      setOpen,
      toggle,
      wide,
      setWide,
      screen,
      setScreen,
      paletteOpen: paletteOpen && enabled,
      setPaletteOpen,
      messages,
      activeId,
      title,
      streaming,
      failure,
      dismissFailure: () => setFailure(null),
      loadingConversation,
      send,
      ask,
      stop,
      regenerate: () => regenerate(false),
      retry,
      askWithCloud,
      newChat,
      openConversation,
      confirmAction,
      cancelAction,
      conversations,
      loadConversations,
      renameConversation,
      setCategory,
      deleteConversation,
      insights,
      dismissInsight,
      suggestions,
      pageContext,
      shareContext,
      setShareContext,
      registerPage,
    }),
    [
      enabled, status, reloadStatus, open, setOpen, toggle, wide, setWide, screen, paletteOpen, messages, activeId, title, streaming, failure,
      loadingConversation, send, ask, stop, regenerate, retry, askWithCloud, newChat, openConversation, confirmAction, cancelAction, conversations,
      loadConversations, renameConversation, setCategory, deleteConversation, insights, dismissInsight, suggestions, pageContext, shareContext,
      registerPage,
    ],
  )

  return <AssistantContext.Provider value={value}>{children}</AssistantContext.Provider>
}

export function useAssistant(): AssistantValue {
  const context = useContext(AssistantContext)
  if (!context) throw new Error('useAssistant must be used within AssistantProvider')
  return context
}

/** For a page to tell the Copilot what the person has open: `useAssistantPage({ entity: 'Client', entity_id: 'CL-0001' })`. */
export function useAssistantPage(extra: Partial<AiPageContext>) {
  const { registerPage } = useAssistant()
  const key = JSON.stringify(extra)
  useEffect(() => registerPage(JSON.parse(key) as Partial<AiPageContext>), [registerPage, key])
}
