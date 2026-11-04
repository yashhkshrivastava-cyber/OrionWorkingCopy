import { useEffect, useMemo, useRef, useState } from 'react'
import { Link } from 'react-router-dom'
import { Check, Moon, Monitor, Palette, Sun } from 'lucide-react'
import { useAppearance } from '../../context/AppearanceContext'
import { usePresence } from '../../hooks/usePresence'
import { Tooltip } from '../ui/Tooltip'
import { resolveAppearance } from '../../theme/engine'
import { DEFAULT_PREFS } from '../../theme/preferences'
import { THEMES, themesFor } from '../../theme/themes'
import type { Mode, ModePreference } from '../../theme/types'

const MODES: { id: ModePreference; label: string; icon: typeof Sun }[] = [
  { id: 'light', label: 'Light', icon: Sun },
  { id: 'dark', label: 'Dark', icon: Moon },
  { id: 'system', label: 'System', icon: Monitor },
]

function ThemeChip({ id, name, selected, mode, onPick }: { id: string; name: string; selected: boolean; mode: Mode; onPick: () => void }) {
  const shown = THEMES.find((t) => t.id === id)?.preferredMode ?? mode
  const vars = useMemo(() => resolveAppearance({ ...DEFAULT_PREFS, theme: id }, shown).vars, [id, shown])
  return (
    <button
      type="button"
      role="menuitemradio"
      aria-checked={selected}
      onClick={onPick}
      className={`interactive flex items-center gap-2.5 rounded-lg px-2 py-1.5 text-left text-sm ${selected ? 'bg-accent-dim' : 'hover:bg-muted'}`}
    >
      <span aria-hidden="true" className="relative h-6 w-9 shrink-0 overflow-hidden rounded-md border border-[color:var(--color-border-strong)]" style={{ background: vars['--orion-bg'] }}>
        <span className="absolute inset-y-0 left-0 w-2.5" style={{ background: vars['--orion-rail'] }} />
        <span className="absolute bottom-1 right-1 h-2.5 w-4 rounded-sm" style={{ background: vars['--orion-surface'], border: `1px solid ${vars['--orion-border-strong']}` }} />
        <span className="absolute left-3.5 top-1 h-1.5 w-3 rounded-sm" style={{ background: vars['--orion-primary'] }} />
      </span>
      <span className="min-w-0 flex-1 truncate font-medium text-[color:var(--color-text)]">{name}</span>
      {selected && <Check className="h-4 w-4 text-accent" strokeWidth={3} aria-hidden="true" />}
    </button>
  )
}

/**
 * The palette button in the top bar: switch theme and mode without leaving the page, and a way to the full Appearance
 * settings. Changes apply at once, exactly as in Settings.
 */
export function AppearanceMenu() {
  const { prefs, mode, selectTheme, update } = useAppearance()
  const [open, setOpen] = useState(false)
  const { present, leaving } = usePresence(open)
  const root = useRef<HTMLDivElement>(null)

  useEffect(() => {
    if (!open) return
    const onPointer = (event: PointerEvent) => {
      if (!root.current?.contains(event.target as Node)) setOpen(false)
    }
    const onKey = (event: KeyboardEvent) => {
      if (event.key === 'Escape') setOpen(false)
    }
    document.addEventListener('pointerdown', onPointer)
    document.addEventListener('keydown', onKey)
    return () => {
      document.removeEventListener('pointerdown', onPointer)
      document.removeEventListener('keydown', onKey)
    }
  }, [open])

  return (
    <div ref={root} className="relative">
      <Tooltip label="Appearance">
        <button
          type="button"
          onClick={() => setOpen((value) => !value)}
          aria-haspopup="menu"
          aria-expanded={open}
          aria-label="Appearance"
          className="interactive inline-flex h-9 w-9 items-center justify-center rounded-lg text-[color:var(--color-text-muted)] hover:bg-muted hover:text-[color:var(--color-text)]"
        >
          <Palette className="h-4 w-4" />
        </button>
      </Tooltip>
      {present && (
        <div
          role="menu"
          aria-label="Appearance"
          className={`${leaving ? 'pop-out' : 'pop-in'} overlay absolute right-0 top-full z-50 mt-2 w-72 rounded-xl border border-[color:var(--color-border)] p-2`}
        >
          <p className="eyebrow px-2 pb-1 pt-1">Theme</p>
          <div className="grid gap-0.5">
            {themesFor(prefs.experience).map((t) => (
              <ThemeChip key={t.id} id={t.id} name={t.name} mode={mode} selected={prefs.theme === t.id} onPick={() => selectTheme(t.id)} />
            ))}
          </div>
          <p className="eyebrow px-2 pb-1 pt-3">Mode</p>
          <div role="group" aria-label="Mode" className="grid grid-cols-3 gap-1 px-1">
            {MODES.map(({ id, label, icon: Icon }) => (
              <button
                key={id}
                type="button"
                role="menuitemradio"
                aria-checked={prefs.mode === id}
                onClick={() => update({ mode: id }, { fade: true })}
                className={`interactive flex flex-col items-center gap-1 rounded-lg px-2 py-2 text-xs font-medium ${prefs.mode === id ? 'bg-accent-dim text-accent' : 'text-[color:var(--color-text-muted)] hover:bg-muted hover:text-[color:var(--color-text)]'}`}
              >
                <Icon className="h-4 w-4" aria-hidden="true" />
                {label}
              </button>
            ))}
          </div>
          <div className="mt-2 border-t border-[color:var(--color-border)] pt-2">
            <Link
              to="/settings?tab=appearance"
              role="menuitem"
              onClick={() => setOpen(false)}
              className="interactive flex items-center justify-between rounded-lg px-2 py-2 text-sm font-medium text-accent hover:bg-muted"
            >
              More appearance options
              <span aria-hidden="true">→</span>
            </Link>
          </div>
        </div>
      )}
    </div>
  )
}
