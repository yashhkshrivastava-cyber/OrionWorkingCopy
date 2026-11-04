import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState, type ReactNode } from 'react'
import { tasksApi } from '../api/client'
import { useToast } from '../components/ui/Toast'
import type { TaskMe } from '../types'
import { useAuth } from './AuthContext'
import { useDataRefresh } from './DataRefreshContext'

type TasksValue = {
  /** How many notifications are unread and how many tasks of this person are late or due today. */
  me: TaskMe
  /** Asks the server again now (after something was changed here), instead of waiting for the next look. */
  refresh: () => Promise<void>
  /** Bumps whenever something changed in the task workspace, so open lists can load again. */
  version: number
  changed: () => void
}

const NONE: TaskMe = { unread: 0, overdue: 0, due_today: 0, attention: 0 }

const TasksContext = createContext<TasksValue | null>(null)

/** How often the server is asked again. A change made here asks at once; this is for what other people did. */
const POLL_MS = 60_000

/** The numbers the bell and the navigation show, looked at again every minute, when the window is used again and after a change made here. */
export function TasksProvider({ children }: { children: ReactNode }) {
  const { user } = useAuth()
  const { generation } = useDataRefresh()
  const toast = useToast()
  const [me, setMe] = useState<TaskMe>(NONE)
  const [version, setVersion] = useState(0)
  const seen = useRef<number | null>(null)
  const signedIn = Boolean(user)

  const refresh = useCallback(async () => {
    if (!signedIn) return
    try {
      const found = await tasksApi.me()
      if (seen.current !== null && found.unread > seen.current) {
        const fresh = found.unread - seen.current
        toast.show(fresh === 1 ? 'You have a new task notification' : `You have ${fresh} new task notifications`, { tone: 'info', detail: 'Open the task bell at the top to see them.' })
      }
      seen.current = found.unread
      setMe(found)
    } catch {
      // A lookup that fails leaves what is shown as it was; the next one tries again.
    }
  }, [signedIn, toast])

  useEffect(() => {
    if (!signedIn) {
      seen.current = null
      setMe(NONE)
      return
    }
    void refresh()
    const timer = window.setInterval(() => void refresh(), POLL_MS)
    const onVisible = () => {
      if (document.visibilityState === 'visible') void refresh()
    }
    document.addEventListener('visibilitychange', onVisible)
    window.addEventListener('focus', onVisible)
    return () => {
      window.clearInterval(timer)
      document.removeEventListener('visibilitychange', onVisible)
      window.removeEventListener('focus', onVisible)
    }
  }, [signedIn, refresh, generation])

  const changed = useCallback(() => {
    setVersion((value) => value + 1)
    void refresh()
  }, [refresh])

  const value = useMemo(() => ({ me, refresh, version, changed }), [me, refresh, version, changed])
  return <TasksContext.Provider value={value}>{children}</TasksContext.Provider>
}

export function useTasks(): TasksValue {
  const context = useContext(TasksContext)
  if (!context) throw new Error('useTasks must be used within TasksProvider')
  return context
}
