import { createContext, useCallback, useContext, useEffect, useRef, useState, type ReactNode } from 'react'
import { api, SESSION_ENDED_EVENT } from '../api/client'
import type { User } from '../types'
import { useAppearance } from './AppearanceContext'
import { DEFAULT_PREFS, samePrefs } from '../theme/preferences'

const TAB_SESSION_KEY = 'orion_tab_session'
const BOOT_KEY = 'orion_boot_id'

interface AuthContextValue {
  user: User | null
  loading: boolean
  login: (username: string, password: string) => Promise<void>
  logout: () => Promise<void>
  refresh: () => Promise<void>
  applyUser: (next: User) => void
}

const AuthContext = createContext<AuthContextValue | null>(null)

/** Desktop passes a new ?boot= id on every launch. Refresh keeps the same id. */
function consumeDesktopBoot(): boolean {
  const params = new URLSearchParams(window.location.search)
  const boot = params.get('boot')
  if (!boot) return false

  const previous = sessionStorage.getItem(BOOT_KEY)
  const isNewProcess = previous !== boot
  sessionStorage.setItem(BOOT_KEY, boot)

  params.delete('boot')
  const qs = params.toString()
  window.history.replaceState(null, '', `${window.location.pathname}${qs ? `?${qs}` : ''}${window.location.hash}`)
  return isNewProcess
}

/**
 * Whether this page load is a new launch of the desktop app, worked out once.
 *
 * consumeDesktopBoot() takes the id out of the address, so asking it a second time says "no". In development
 * React runs a start-up effect twice: the second run then took the other path and asked the server who is
 * signed in while the first run's sign-out was still on its way. That answer arrived last and filled the user
 * back in over a session the server had just ended: signed in on screen, refused by every request.
 */
let newDesktopLaunch: boolean | null = null
function isNewDesktopLaunch(): boolean {
  if (newDesktopLaunch === null) newDesktopLaunch = consumeDesktopBoot()
  return newDesktopLaunch
}

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null>(null)
  const [loading, setLoading] = useState(true)
  const { applyRemote, setSaver, update: updateAppearance, prefs: localPrefs } = useAppearance()

  // The server ended this session while the app was open: go back to the sign-in page.
  useEffect(() => {
    const ended = () => setUser(null)
    window.addEventListener(SESSION_ENDED_EVENT, ended)
    return () => window.removeEventListener(SESSION_ENDED_EVENT, ended)
  }, [])

  const refresh = useCallback(async () => {
    try {
      const me = (await api.me()) as User
      setUser(me)
    } catch {
      setUser(null)
    }
  }, [])

  useEffect(() => {
    if (isNewDesktopLaunch()) {
      sessionStorage.removeItem(TAB_SESSION_KEY)
      void api.logout().catch(() => undefined).finally(() => {
        setUser(null)
        setLoading(false)
      })
      return
    }

    refresh().finally(() => setLoading(false))
  }, [refresh])

  // Appearance follows the person: on sign-in the account's saved settings are applied, and later changes are saved to it.
  // Only a change of who is signed in matters here; refreshing the same user must not overwrite what was just chosen.
  const localPrefsRef = useRef(localPrefs)
  localPrefsRef.current = localPrefs
  useEffect(() => {
    if (!user) {
      setSaver(null)
      return
    }
    setSaver(async (prefs) => {
      await api.updateProfile({
        appearance: prefs,
        ...(prefs.mode === 'system' ? {} : { preferred_theme: prefs.mode }),
      })
    })
    if (user.appearance) applyRemote(user.appearance)
    else if (user.preferred_theme && samePrefs(localPrefsRef.current, DEFAULT_PREFS)) updateAppearance({ mode: user.preferred_theme })
    else applyRemote(null)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [user?.id])

  const login = async (username: string, password: string) => {
    const me = (await api.login(username, password)) as User
    sessionStorage.setItem(TAB_SESSION_KEY, '1')
    setUser(me)
  }

  const logout = async () => {
    sessionStorage.removeItem(TAB_SESSION_KEY)
    try {
      await api.logout()
    } catch {
      /* still end the local session */
    }
    setUser(null)
  }

  return (
    <AuthContext.Provider value={{ user, loading, login, logout, refresh, applyUser: setUser }}>
      {children}
    </AuthContext.Provider>
  )
}

export function useAuth() {
  const ctx = useContext(AuthContext)
  if (!ctx) throw new Error('useAuth must be used within AuthProvider')
  return ctx
}
