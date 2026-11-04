/**
 * What a person chose, how it is checked, and where it is kept on this device. The same checks run on anything that
 * comes from outside (local storage, the server), so a damaged or older value falls back to the default instead of
 * breaking the page.
 */

import { DEFAULT_THEME_ID, LUMEN_THEME_ID, STYLES, themeById } from './themes'
import type { AppearancePrefs, Contrast, Density, Experience, ModePreference, MotionPreference, StyleId } from './types'

export const STORAGE_KEY = 'orion-appearance'
/** The resolved variables, kept so the very first paint of the next visit is already themed (see public/theme-boot.js). */
export const CACHE_KEY = 'orion-appearance-cache'
/** Written before themes existed: just "light" or "dark". Still read, so nobody's choice is lost. */
const LEGACY_KEY = 'orion-theme'

export const DEFAULT_PREFS: AppearancePrefs = {
  v: 1,
  theme: DEFAULT_THEME_ID,
  mode: 'system',
  accent: null,
  style: null,
  radius: null,
  density: 'comfortable',
  scale: 100,
  contrast: 'standard',
  motion: 'full',
  gradient: null,
  ambient: null,
  experience: 'classic',
}

const oneOf = <T extends string>(value: unknown, allowed: readonly T[], fallback: T): T =>
  typeof value === 'string' && (allowed as readonly string[]).includes(value) ? (value as T) : fallback

/** Whatever was stored or received, as valid preferences. Never throws. */
export function sanitize(raw: unknown): AppearancePrefs {
  const r = (raw && typeof raw === 'object' ? raw : {}) as Record<string, unknown>
  const hex = typeof r.accent === 'string' && /^#[0-9a-fA-F]{6}$/.test(r.accent) ? r.accent.toLowerCase() : null
  const radius = typeof r.radius === 'number' && r.radius >= 0 && r.radius <= 1 ? Math.round(r.radius * 1000) / 1000 : null
  const scale = typeof r.scale === 'number' && r.scale >= 85 && r.scale <= 125 ? Math.round(r.scale) : DEFAULT_PREFS.scale
  const experience = oneOf<Experience>(r.experience, ['classic', 'lumen'], 'classic')
  const known = typeof r.theme === 'string' ? themeById(r.theme) : themeById(DEFAULT_PREFS.theme)
  // a theme belongs to one interface: a mismatch (an older save, a hand-edited one) falls back to that interface's own default
  const themeId = (known.experience ?? 'classic') === experience ? known.id : experience === 'lumen' ? LUMEN_THEME_ID : DEFAULT_PREFS.theme
  return {
    v: 1,
    theme: themeId,
    mode: oneOf<ModePreference>(r.mode, ['light', 'dark', 'system'], 'system'),
    accent: hex,
    style: typeof r.style === 'string' && STYLES.some((s) => s.id === r.style) ? (r.style as StyleId) : null,
    radius,
    density: oneOf<Density>(r.density, ['compact', 'comfortable', 'spacious'], 'comfortable'),
    scale,
    contrast: oneOf<Contrast>(r.contrast, ['standard', 'high'], 'standard'),
    motion: oneOf<MotionPreference>(r.motion, ['full', 'reduced'], 'full'),
    gradient: typeof r.gradient === 'boolean' ? r.gradient : null,
    ambient: typeof r.ambient === 'boolean' ? r.ambient : null,
    experience,
  }
}

export function loadLocal(): AppearancePrefs {
  try {
    const stored = localStorage.getItem(STORAGE_KEY)
    if (stored) return sanitize(JSON.parse(stored))
    const legacy = localStorage.getItem(LEGACY_KEY)
    if (legacy === 'light' || legacy === 'dark') return { ...DEFAULT_PREFS, mode: legacy }
  } catch {
    /* storage is blocked or damaged: use the default */
  }
  return DEFAULT_PREFS
}

export function saveLocal(prefs: AppearancePrefs) {
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(prefs))
    // Keep the old key in step so an older tab or build still follows the mode.
    if (prefs.mode !== 'system') localStorage.setItem(LEGACY_KEY, prefs.mode)
    else localStorage.removeItem(LEGACY_KEY)
  } catch {
    /* private mode: the choice still applies for this visit */
  }
}

export const samePrefs = (a: AppearancePrefs | undefined, b: AppearancePrefs | undefined) =>
  a !== undefined && b !== undefined && JSON.stringify(a) === JSON.stringify(b)

/** The person's mode and theme kept, every personal override removed: "reset to theme defaults". */
export const themeDefaults = (prefs: AppearancePrefs): AppearancePrefs => ({
  ...DEFAULT_PREFS,
  theme: prefs.theme,
  mode: prefs.mode,
  experience: prefs.experience,
})

/** True when something has been changed from what the theme itself provides. */
export const hasOverrides = (prefs: AppearancePrefs): boolean => !samePrefs(prefs, themeDefaults(prefs))
