import { useAppearance } from '../context/AppearanceContext'
import { useAuth } from '../context/AuthContext'
import { HomePage } from './HomePage'
import { lazyPage } from '../lazyPage'

const LumenHome = lazyPage(() => import('./LumenHome'), 'LumenHome')

/** The front door: the Today page for someone signed in to Lumen, the company's own page for everyone else. */
export function HomeSwitch() {
  const { user } = useAuth()
  const { prefs } = useAppearance()
  return user && prefs.experience === 'lumen' ? <LumenHome /> : <HomePage />
}
