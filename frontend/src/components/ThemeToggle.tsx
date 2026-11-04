import { Moon, Sun } from 'lucide-react'
import { useTheme } from '../context/ThemeContext'

/** A plain light/dark switch, for pages (like sign-in) that have no top bar with the full Appearance menu. */
export function ThemeToggle({ className = '', compact = false }: { className?: string; compact?: boolean }) {
  const { theme, toggle } = useTheme()
  const dark = theme === 'dark'

  return (
    <button
      type="button"
      onClick={toggle}
      aria-label={dark ? 'Switch to light mode' : 'Switch to dark mode'}
      title={dark ? 'Light mode' : 'Dark mode'}
      className={`interactive inline-flex items-center justify-center gap-2 rounded-lg text-sm font-medium text-[color:var(--color-text-muted)] hover:bg-muted hover:text-[color:var(--color-text)] ${
        compact ? 'h-9 w-9 p-0' : 'border border-[color:var(--color-border)] bg-surface px-3 py-1.5'
      } ${className}`}
    >
      {dark ? <Sun className="h-4 w-4" /> : <Moon className="h-4 w-4" />}
      {!compact && <span>{dark ? 'Light' : 'Dark'}</span>}
    </button>
  )
}
