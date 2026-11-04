import { createContext, useCallback, useContext, useEffect, useLayoutEffect, useMemo, useRef, useState, type ReactNode } from 'react'
import { applyAppearance, crossfade, prefersReducedMotion } from '../theme/apply'
import { describe, modeOf, systemMode } from '../theme/engine'
import { DEFAULT_PREFS, hasOverrides, loadLocal, samePrefs, sanitize, saveLocal, themeDefaults } from '../theme/preferences'
import { LUMEN_THEME_ID, themeById } from '../theme/themes'
import type { AppearancePrefs, Experience, Mode, StyleDef, ThemeDef } from '../theme/types'

export type SyncState = 'idle' | 'saving' | 'saved' | 'offline'

type Options = {
  /** Cross-fade the change. Used for switching theme or mode, never for a slider being dragged. */
  fade?: boolean
}

type AppearanceValue = {
  prefs: AppearancePrefs
  /** The mode on screen now: what "system" resolves to when that is chosen. */
  mode: Mode
  theme: ThemeDef
  style: StyleDef
  /** Change any preference. Applied at once, kept on this device, and saved to the account a moment later. */
  update: (patch: Partial<AppearancePrefs>, options?: Options) => void
  /** Choose a theme: opens in the mode it was designed for and drops the personal colour and style overrides. */
  selectTheme: (id: string) => void
  /** Switch the whole interface between the classic one and Lumen. What was chosen in the one is kept for when the person comes back to it. */
  setExperience: (experience: Experience) => void
  /** Back to what the chosen theme provides. Mode, density, size, contrast and motion are kept. */
  resetToTheme: () => void
  undo: () => void
  canUndo: boolean
  hasOverrides: boolean
  sync: SyncState
  /** Called by the sign-in code when the account's saved settings arrive. */
  applyRemote: (remote: unknown) => void
  /** Called by the sign-in code: how to save to the account, or null when nobody is signed in. */
  setSaver: (saver: ((prefs: AppearancePrefs) => Promise<void>) | null) => void
}

const AppearanceContext = createContext<AppearanceValue | null>(null)

/** Where the classic look is kept (on this device) while Lumen is in use, so switching back finds it as it was. */
const CLASSIC_KEY = 'orion-classic-look'
const SAVE_DELAY = 800
const HISTORY = 12

export function AppearanceProvider({ children }: { children: ReactNode }) {
  const [prefs, setPrefs] = useState<AppearancePrefs>(() => (typeof window === 'undefined' ? DEFAULT_PREFS : loadLocal()))
  const [mode, setMode] = useState<Mode>(() => (typeof window === 'undefined' ? 'light' : modeOf(prefs)))
  const [sync, setSync] = useState<SyncState>('idle')
  const [history, setHistory] = useState<AppearancePrefs[]>([])
  const current = useRef(prefs)
  const saver = useRef<((prefs: AppearancePrefs) => Promise<void>) | null>(null)
  const timer = useRef<number | undefined>(undefined)
  const dirty = useRef(false)

  const reduced = () => current.current.motion === 'reduced' || prefersReducedMotion()

  const flush = useCallback(async () => {
    if (!saver.current || !dirty.current) return
    dirty.current = false
    setSync('saving')
    try {
      await saver.current(current.current)
      setSync('saved')
    } catch {
      dirty.current = true
      setSync('offline')
    }
  }, [])

  const schedule = useCallback(() => {
    dirty.current = true
    window.clearTimeout(timer.current)
    timer.current = window.setTimeout(() => void flush(), SAVE_DELAY)
  }, [flush])

  /** Puts `next` on the page and into state, and (unless it came from the server) keeps it. */
  const commit = useCallback(
    (next: AppearancePrefs, options: Options & { remember?: boolean; fromRemote?: boolean } = {}) => {
      const nextMode = modeOf(next)
      const run = () => applyAppearance(next, nextMode)
      if (options.fade) crossfade(run, reduced())
      else run()
      if (options.remember !== false) {
        const before = current.current
        setHistory((h) => (samePrefs(h[h.length - 1], before) ? h : [...h, before].slice(-HISTORY)))
      }
      current.current = next
      setPrefs(next)
      setMode(nextMode)
      saveLocal(next)
      if (!options.fromRemote) schedule()
    },
    [schedule],
  )

  // The page was themed by public/theme-boot.js; do it again from the same source of truth.
  useLayoutEffect(() => {
    applyAppearance(prefs, modeOf(prefs))
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  // "System" follows the device while the page is open.
  useEffect(() => {
    if (prefs.mode !== 'system') return
    const media = window.matchMedia('(prefers-color-scheme: dark)')
    const onChange = () => {
      const next = systemMode()
      applyAppearance(current.current, next)
      setMode(next)
    }
    media.addEventListener('change', onChange)
    return () => media.removeEventListener('change', onChange)
  }, [prefs.mode])

  useEffect(() => {
    const onHide = () => {
      if (document.visibilityState === 'hidden') void flush()
    }
    document.addEventListener('visibilitychange', onHide)
    return () => document.removeEventListener('visibilitychange', onHide)
  }, [flush])

  const update = useCallback(
    (patch: Partial<AppearancePrefs>, options: Options = {}) => {
      const next = sanitize({ ...current.current, ...patch })
      if (samePrefs(next, current.current)) return
      commit(next, options)
    },
    [commit],
  )

  const setExperience = useCallback(
    (experience: Experience) => {
      const now = current.current
      if (now.experience === experience) return
      if (experience === 'lumen') {
        try {
          localStorage.setItem(CLASSIC_KEY, JSON.stringify(now))
        } catch {
          /* the classic look then comes back as the default one */
        }
        const picked = themeById(LUMEN_THEME_ID)
        update({ experience: 'lumen', theme: picked.id, accent: null, style: null, radius: null, gradient: null, ambient: null }, { fade: true })
        return
      }
      let back: AppearancePrefs = { ...DEFAULT_PREFS, mode: now.mode, density: now.density, scale: now.scale, contrast: now.contrast, motion: now.motion }
      try {
        const saved = localStorage.getItem(CLASSIC_KEY)
        if (saved) back = sanitize({ ...JSON.parse(saved), experience: 'classic' })
      } catch {
        /* a damaged copy: the default classic look */
      }
      update({ ...back, experience: 'classic' }, { fade: true })
    },
    [update],
  )

  const selectTheme = useCallback(
    (id: string) => {
      const picked = themeById(id)
      // a theme of the other interface (the Copilot may ask for one) takes the person to that interface first, which also keeps the classic look for the way back
      if ((picked.experience ?? 'classic') !== current.current.experience) setExperience(picked.experience ?? 'classic')
      update(
        {
          theme: picked.id,
          experience: picked.experience ?? 'classic',
          mode: picked.preferredMode ?? current.current.mode,
          accent: null,
          style: null,
          radius: null,
          gradient: null,
          ambient: null,
        },
        { fade: true },
      )
    },
    [update, setExperience],
  )

  const resetToTheme = useCallback(() => commit(themeDefaults(current.current), { fade: true }), [commit])

  const undo = useCallback(() => {
    const previous = history[history.length - 1]
    if (!previous) return
    setHistory(history.slice(0, -1))
    commit(previous, { fade: true, remember: false })
  }, [commit, history])

  const applyRemote = useCallback(
    (remote: unknown) => {
      if (!remote) {
        // Nothing saved on the account yet: what this device has becomes the account's.
        if (hasOverrides(current.current) || current.current.theme !== DEFAULT_PREFS.theme || current.current.mode !== 'system') schedule()
        return
      }
      const next = sanitize(remote)
      if (samePrefs(next, current.current)) return
      commit(next, { fade: true, remember: false, fromRemote: true })
      setSync('saved')
    },
    [commit, schedule],
  )

  const setSaver = useCallback((fn: ((prefs: AppearancePrefs) => Promise<void>) | null) => {
    saver.current = fn
    if (!fn) {
      window.clearTimeout(timer.current)
      dirty.current = false
      setSync('idle')
    }
  }, [])

  const { theme, style } = useMemo(() => describe(prefs), [prefs])

  const value = useMemo<AppearanceValue>(
    () => ({
      prefs,
      mode,
      theme,
      style,
      update,
      selectTheme,
      setExperience,
      resetToTheme,
      undo,
      canUndo: history.length > 0,
      hasOverrides: hasOverrides(prefs),
      sync,
      applyRemote,
      setSaver,
    }),
    [prefs, mode, theme, style, update, selectTheme, setExperience, resetToTheme, undo, history.length, sync, applyRemote, setSaver],
  )

  return <AppearanceContext.Provider value={value}>{children}</AppearanceContext.Provider>
}

export function useAppearance(): AppearanceValue {
  const context = useContext(AppearanceContext)
  if (!context) throw new Error('useAppearance must be used within AppearanceProvider')
  return context
}
