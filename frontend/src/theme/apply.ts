/**
 * Puts a resolved appearance on the page, and remembers it so the next visit paints in the right theme from the first
 * frame. This is the only part of the theme system that touches the DOM.
 */

import { resolveAppearance } from './engine'
import { CACHE_KEY } from './preferences'
import { describe } from './engine'
import type { AppearancePrefs, Mode } from './types'

/** The variables this module put on <html>, so a theme that sets fewer of them leaves none behind. */
let written = new Set<string>()

const FONT_LINK_ID = 'orion-theme-font'

function ensureFont(url: string | null) {
  const existing = document.getElementById(FONT_LINK_ID) as HTMLLinkElement | null
  if (!url) {
    existing?.remove()
    return
  }
  if (existing?.href === url) return
  const link = existing ?? document.createElement('link')
  link.id = FONT_LINK_ID
  link.rel = 'stylesheet'
  link.href = url
  if (!existing) document.head.appendChild(link)
}

export function applyAppearance(prefs: AppearancePrefs, mode: Mode) {
  const root = document.documentElement
  const resolved = resolveAppearance(prefs, mode)
  const { style } = describe(prefs)

  written.forEach((name) => {
    if (!(name in resolved.vars)) root.style.removeProperty(name)
  })
  for (const [name, value] of Object.entries(resolved.vars)) root.style.setProperty(name, value)
  written = new Set(Object.keys(resolved.vars))

  root.classList.toggle('dark', mode === 'dark')
  root.style.colorScheme = mode
  root.dataset.theme = prefs.theme
  root.dataset.style = style.id
  root.dataset.mode = mode
  root.dataset.experience = prefs.experience
  root.dataset.motion = prefs.motion
  root.dataset.contrast = prefs.contrast

  document.querySelector('meta[name="theme-color"]')?.setAttribute('content', resolved.themeColor)
  ensureFont(resolved.fontLink)
  writeCache(prefs, style.id)
}

/** Both modes are kept, so a visit in "system" mode picks the right one before any script has run. */
function writeCache(prefs: AppearancePrefs, styleId: string) {
  try {
    const light = resolveAppearance(prefs, 'light')
    const dark = resolveAppearance(prefs, 'dark')
    localStorage.setItem(
      CACHE_KEY,
      JSON.stringify({
        mode: prefs.mode,
        light: { vars: light.vars, themeColor: light.themeColor },
        dark: { vars: dark.vars, themeColor: dark.themeColor },
        fontLink: light.fontLink,
        attrs: { theme: prefs.theme, style: styleId, motion: prefs.motion, contrast: prefs.contrast, experience: prefs.experience },
      }),
    )
  } catch {
    /* storage is blocked: the next visit works the theme out after the page loads */
  }
}

export const prefersReducedMotion = () => window.matchMedia?.('(prefers-reduced-motion: reduce)').matches ?? false

/**
 * Runs `update` (which changes the theme on the page) inside a cross-fade, so switching theme or mode is a smooth
 * dissolve rather than a flash. Uses the View Transitions API where there is one and a short colour transition
 * elsewhere. Does nothing fancy for people who asked for less motion.
 */
export function crossfade(update: () => void, reduced: boolean) {
  if (reduced) {
    update()
    return
  }
  const doc = document as Document & { startViewTransition?: (callback: () => void) => { skipTransition?: () => void; ready?: Promise<void>; finished?: Promise<void> } }
  if (doc.startViewTransition) {
    const transition = doc.startViewTransition(update)
    // a transition that is cut short rejects these promises; nobody waits on them, so that is not an error
    transition.ready?.catch(() => undefined)
    transition.finished?.catch(() => undefined)
    // The new theme is already on the page once `update` has run; the fade is only decoration. If frames are not being
    // drawn (a background tab, a throttled embedded view) the page must not wait on it, so it is cut short.
    window.setTimeout(() => transition.skipTransition?.(), 700)
    return
  }
  const root = document.documentElement
  root.classList.add('theme-switching')
  update()
  window.setTimeout(() => root.classList.remove('theme-switching'), 420)
}
