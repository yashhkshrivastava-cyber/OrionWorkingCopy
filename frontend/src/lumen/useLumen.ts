import { useAppearance } from '../context/AppearanceContext'

/** True while the Lumen interface is on. Shared components use it to draw their richer Lumen form; the data and the actions they offer never change with it. */
export function useLumen(): boolean {
  return useAppearance().prefs.experience === 'lumen'
}
