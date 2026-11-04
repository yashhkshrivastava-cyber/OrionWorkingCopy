/**
 * Light or dark, as the rest of the app has always asked for it. The theme system lives in `../theme` and
 * `AppearanceContext`; this file is the small, stable surface the older code uses, kept so it does not have to know
 * about themes at all.
 */

import { useAppearance, AppearanceProvider } from './AppearanceContext'

export type Theme = 'light' | 'dark'

export const ThemeProvider = AppearanceProvider

export function useTheme(): { theme: Theme; setTheme: (theme: Theme) => void; toggle: () => void } {
  const { mode, update } = useAppearance()
  return {
    theme: mode,
    setTheme: (next) => update({ mode: next }, { fade: true }),
    toggle: () => update({ mode: mode === 'dark' ? 'light' : 'dark' }, { fade: true }),
  }
}
