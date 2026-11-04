import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState, type ReactNode } from 'react'
import { api } from '../api/client'
import { useToast } from '../components/ui/Toast'
import type { Followup } from '../types'
import { useAuth } from './AuthContext'
import { useDataRefresh } from './DataRefreshContext'

type FollowupsValue = {
  /** What is waiting to be done for won opportunities, oldest first. Empty for someone who cannot change operational data. */
  open: Followup[]
  /** What people decided is not needed, newest first. */
  dismissed: Followup[]
  loaded: boolean
  /** Asks the server again now (after something was saved here), instead of waiting for the next look. */
  refresh: () => Promise<void>
  dismiss: (id: number, note: string) => Promise<void>
  reopen: (id: number) => Promise<void>
}

const FollowupsContext = createContext<FollowupsValue | null>(null)

/** How often the server is asked again. A save made here asks at once; this is for what other people did. */
const POLL_MS = 60_000

/**
 * The notifications about won opportunities: create the case, record the EMD. They stay until the case or the EMD exists or someone
 * says it is not required, so they are looked at again every minute, when the window is used again and after anything is saved here.
 */
export function FollowupsProvider({ children }: { children: ReactNode }) {
  const { user } = useAuth()
  const { generation } = useDataRefresh()
  const toast = useToast()
  const enabled = Boolean(user?.can_ods_write)
  const [open, setOpen] = useState<Followup[]>([])
  const [dismissed, setDismissed] = useState<Followup[]>([])
  const [loaded, setLoaded] = useState(false)
  // What was already known, so a new one says so (once) and what was there at sign-in does not.
  const known = useRef<Set<number> | null>(null)

  const refresh = useCallback(async () => {
    if (!enabled) return
    try {
      const found = await api.followups()
      const ids = new Set(found.open.map((item) => item.id))
      if (known.current) {
        const fresh = found.open.filter((item) => !known.current?.has(item.id))
        if (fresh.length) {
          toast.show(fresh.length === 1 ? fresh[0].title : `${fresh.length} things to do for won opportunities`, {
            tone: 'info',
            detail: fresh.length === 1 ? fresh[0].message : 'Open the bell at the top to see them.',
          })
        }
      }
      known.current = ids
      setOpen(found.open)
      setDismissed(found.dismissed)
      setLoaded(true)
    } catch {
      // A lookup that fails leaves what is shown as it was; the next one tries again.
    }
  }, [enabled, toast])

  useEffect(() => {
    if (!enabled) {
      known.current = null
      setOpen([])
      setDismissed([])
      setLoaded(false)
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
  }, [enabled, refresh, generation])

  const dismiss = useCallback(
    async (id: number, note: string) => {
      await api.dismissFollowup(id, note)
      await refresh()
    },
    [refresh],
  )
  const reopen = useCallback(
    async (id: number) => {
      await api.reopenFollowup(id)
      await refresh()
    },
    [refresh],
  )

  const value = useMemo(() => ({ open, dismissed, loaded, refresh, dismiss, reopen }), [open, dismissed, loaded, refresh, dismiss, reopen])
  return <FollowupsContext.Provider value={value}>{children}</FollowupsContext.Provider>
}

export function useFollowups(): FollowupsValue {
  const context = useContext(FollowupsContext)
  if (!context) throw new Error('useFollowups must be used within FollowupsProvider')
  return context
}
