import { useMemo, useState, type KeyboardEvent, type ReactNode } from 'react'
import { Check, ChevronDown, CircleCheck, CloudOff, LoaderCircle, Moon, Monitor, RotateCcw, Sun, Undo2 } from 'lucide-react'
import { useAppearance } from '../../context/AppearanceContext'
import { checks, resolveAppearance } from '../../theme/engine'
import { DEFAULT_PREFS } from '../../theme/preferences'
import { ACCENT_SWATCHES, STYLES, themesFor } from '../../theme/themes'
import type { AppearancePrefs, Density, Mode, ModePreference, StyleDef, ThemeDef } from '../../theme/types'
import { Alert, Badge } from '../ui/Alert'
import { Button } from '../ui/Button'
import { Field, Input, Select, Switch } from '../ui/Field'
import { Modal } from '../ui/Modal'
import { Segmented } from '../ui/Segmented'
import { Tabs } from '../ui/Tabs'
import { useToast } from '../ui/Toast'
import { ExperienceSwitch } from './ExperienceSwitch'
import { ThemePreview } from './ThemePreview'

/** One block of the screen: a heading, a line that says what it is for, and its controls. */
function Section({ title, description, children }: { title: string; description?: string; children: ReactNode }) {
  return (
    <section className="panel p-5" aria-label={title}>
      <h3 className="t-h2">{title}</h3>
      {description && <p className="t-small mt-0.5 max-w-xl text-[color:var(--color-text-muted)]">{description}</p>}
      <div className="mt-4">{children}</div>
    </section>
  )
}

/** Roving-focus arrow keys for a set of radio-style cards. */
function arrowKeys(event: KeyboardEvent, index: number, count: number, go: (next: number) => void) {
  const step = event.key === 'ArrowRight' || event.key === 'ArrowDown' ? 1 : event.key === 'ArrowLeft' || event.key === 'ArrowUp' ? -1 : 0
  if (!step) return
  event.preventDefault()
  go((index + step + count) % count)
}

function Swatches({ colors }: { colors: string[] }) {
  return (
    <span className="flex items-center" aria-hidden="true">
      {colors.map((color, i) => (
        <span key={i} className="-ml-1 h-4 w-4 rounded-full border border-[color:var(--color-border-strong)] first:ml-0" style={{ background: color }} />
      ))}
    </span>
  )
}

// ------------------------------------------------------------------------------------------------------------ theme

function ThemeCard({ theme, selected, mode, onPick, onKey, tabIndex }: { theme: ThemeDef; selected: boolean; mode: Mode; onPick: () => void; onKey: (e: KeyboardEvent) => void; tabIndex: number }) {
  // Each theme is shown the way it was designed (Midnight dark, Ivory light), so the cards read as different looks.
  const shownMode: Mode = theme.preferredMode ?? mode
  const vars = useMemo(() => resolveAppearance({ ...DEFAULT_PREFS, theme: theme.id }, shownMode).vars, [theme.id, shownMode])
  const ModeIcon = shownMode === 'dark' ? Moon : Sun
  return (
    <button
      type="button"
      role="radio"
      aria-checked={selected}
      tabIndex={tabIndex}
      onClick={onPick}
      onKeyDown={onKey}
      className={`group interactive relative flex w-[78%] shrink-0 snap-start flex-col rounded-2xl border-2 bg-surface p-2 text-left sm:w-auto sm:shrink ${
        selected ? 'border-primary shadow-raised' : 'border-[color:var(--color-border)] hover:-translate-y-0.5 hover:border-[color:var(--color-border-strong)] hover:shadow-raised'
      }`}
    >
      <div className="relative overflow-hidden rounded-xl border border-[color:var(--color-border)]">
        <ThemePreview prefs={{ theme: theme.id, experience: theme.experience ?? 'classic' }} mode={shownMode} />
        <span className="absolute right-1.5 top-1.5 inline-flex items-center gap-1 rounded-full bg-black/55 px-1.5 py-0.5 text-[10px] font-medium text-white backdrop-blur-sm">
          <ModeIcon className="h-2.5 w-2.5" aria-hidden="true" />
          {shownMode === 'dark' ? 'Dark' : 'Light'}
        </span>
      </div>
      <div className="px-1.5 pb-1 pt-2.5">
        <div className="flex items-center justify-between gap-2">
          <span className="t-h3">{theme.name}</span>
          <span className="flex items-center gap-2">
            <Swatches colors={[vars['--orion-bg'], vars['--orion-surface'], vars['--orion-primary'], vars['--orion-rail']]} />
            {selected && (
              <span className="inline-flex h-5 w-5 items-center justify-center rounded-full bg-primary text-on-primary">
                <Check className="h-3 w-3" strokeWidth={3} aria-hidden="true" />
                <span className="sr-only">Selected</span>
              </span>
            )}
          </span>
        </div>
        <p className="mt-0.5 text-[13px] font-medium text-[color:var(--color-text)]">{theme.tagline}</p>
        <p className="t-caption mt-0.5">{theme.description}</p>
      </div>
    </button>
  )
}

// ------------------------------------------------------------------------------------------------------------ pieces

function StyleCard({ style, selected, themeDefault, prefs, mode, onPick, onKey, tabIndex }: { style: StyleDef; selected: boolean; themeDefault: boolean; prefs: AppearancePrefs; mode: Mode; onPick: () => void; onKey: (e: KeyboardEvent) => void; tabIndex: number }) {
  return (
    <button
      type="button"
      role="radio"
      aria-checked={selected}
      tabIndex={tabIndex}
      onClick={onPick}
      onKeyDown={onKey}
      className={`interactive flex w-[64%] shrink-0 snap-start flex-col rounded-xl border-2 bg-surface p-1.5 text-left sm:w-auto sm:shrink ${
        selected ? 'border-primary shadow-raised' : 'border-[color:var(--color-border)] hover:border-[color:var(--color-border-strong)]'
      }`}
    >
      <div className="overflow-hidden rounded-lg border border-[color:var(--color-border)]">
        <ThemePreview prefs={{ ...prefs, style: style.id, radius: null, gradient: null, ambient: null }} mode={mode} />
      </div>
      <div className="px-1 pb-0.5 pt-2">
        <span className="flex items-center gap-1.5">
          <span className="t-label">{style.name}</span>
          {themeDefault && <Badge>Theme</Badge>}
          {selected && <Check className="ml-auto h-3.5 w-3.5 text-accent" strokeWidth={3} aria-label="Selected" />}
        </span>
        <p className="t-caption mt-0.5">{style.description}</p>
      </div>
    </button>
  )
}

function SyncStatus() {
  const { sync } = useAppearance()
  const view =
    sync === 'saving'
      ? { icon: <LoaderCircle className="h-3.5 w-3.5 animate-spin" aria-hidden="true" />, text: 'Saving…' }
      : sync === 'saved'
        ? { icon: <CircleCheck className="h-3.5 w-3.5 text-positive" aria-hidden="true" />, text: 'Saved to your account' }
        : sync === 'offline'
          ? { icon: <CloudOff className="h-3.5 w-3.5 text-warning" aria-hidden="true" />, text: 'Saved on this device; could not reach the server' }
          : { icon: <CircleCheck className="h-3.5 w-3.5 text-positive" aria-hidden="true" />, text: 'Saved on this device' }
  return (
    <span role="status" className="t-caption inline-flex items-center gap-1.5">
      {view.icon}
      {view.text}
    </span>
  )
}

/** The real components, as they look under the current settings, for trying a change before leaving the page. */
function LivePreview() {
  const toast = useToast()
  const [tab, setTab] = useState<'one' | 'two' | 'three'>('one')
  const [on, setOn] = useState(true)
  const [open, setOpen] = useState(false)
  return (
    <div className="panel p-4" aria-label="Live preview">
      <div className="flex items-center justify-between">
        <h3 className="t-h3">Try it</h3>
        <span className="t-caption">Real components</span>
      </div>
      <div className="mt-3 space-y-4">
        <div className="flex flex-wrap gap-2">
          <Button size="sm">Primary</Button>
          <Button size="sm" variant="secondary">Secondary</Button>
          <Button size="sm" variant="ghost">Ghost</Button>
          <Button size="sm" variant="danger">Delete</Button>
        </div>
        <Field label="A field" hint="Helper text sits underneath.">
          <Input placeholder="Type here" />
        </Field>
        <Select aria-label="A choice" defaultValue="b">
          <option value="a">First option</option>
          <option value="b">Second option</option>
        </Select>
        <Tabs label="Example tabs" tabs={[{ id: 'one', label: 'Overview' }, { id: 'two', label: 'Activity' }, { id: 'three', label: 'Files' }]} active={tab} onChange={setTab} />
        <div className="flex flex-wrap items-center gap-1.5">
          <Badge variant="emerald">Active</Badge>
          <Badge variant="amber">Due soon</Badge>
          <Badge variant="rose">Overdue</Badge>
          <Badge variant="cyan">Draft</Badge>
        </div>
        <Switch label="A setting" hint="Switches act at once." checked={on} onChange={setOn} />
        <div className="overflow-hidden rounded-lg border border-[color:var(--color-border)]">
          <table className="w-full text-left text-xs">
            <thead>
              <tr className="bg-surface-hover text-[color:var(--color-text-faint)]">
                <th className="px-3 py-1.5 font-semibold uppercase tracking-wider">Client</th>
                <th className="px-3 py-1.5 text-right font-semibold uppercase tracking-wider">Billed</th>
              </tr>
            </thead>
            <tbody>
              {[['Acme HQ', '₹4,20,000'], ['Civil Hospital', '₹2,85,500']].map(([a, b]) => (
                <tr key={a} className="border-t border-[color:var(--color-border)] hover:bg-surface-hover">
                  <td className="px-3 py-1.5">{a}</td>
                  <td className="t-num px-3 py-1.5 text-right">{b}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <Alert variant="info">Notices use the same tokens.</Alert>
        <div className="flex flex-wrap gap-2">
          <Button size="sm" variant="secondary" onClick={() => toast.show('Document filed', { detail: 'This is what a notification looks like.' })}>
            Show a notification
          </Button>
          <Button size="sm" variant="secondary" onClick={() => setOpen(true)}>
            Open a dialog
          </Button>
        </div>
      </div>
      <Modal open={open} title="A dialog" onClose={() => setOpen(false)} footer={<><Button variant="secondary" onClick={() => setOpen(false)}>Cancel</Button><Button onClick={() => setOpen(false)}>Confirm</Button></>}>
        <p className="t-body text-[color:var(--color-text-muted)]">Dialogs fade in, keep keyboard focus inside, and give it back when they close.</p>
      </Modal>
    </div>
  )
}

// ----------------------------------------------------------------------------------------------------------- screen

const MODE_OPTIONS: { id: ModePreference; label: string }[] = [
  { id: 'light', label: 'Light' },
  { id: 'dark', label: 'Dark' },
  { id: 'system', label: 'System' },
]
const DENSITY_OPTIONS: { id: Density; label: string }[] = [
  { id: 'compact', label: 'Compact' },
  { id: 'comfortable', label: 'Comfortable' },
  { id: 'spacious', label: 'Spacious' },
]

/**
 * Appearance: choose a theme and shape it. Every control changes the whole application at once and is kept at once,
 * on this device and (a moment later) on the account; there is no Save to forget. "Undo" steps back through changes and
 * "Reset to theme defaults" removes every personal override but keeps the theme and mode.
 */
export function AppearanceSettings() {
  const { prefs, mode, theme, style, update, selectTheme, resetToTheme, undo, canUndo, hasOverrides } = useAppearance()
  const [accentText, setAccentText] = useState('')
  const effectiveAccent = prefs.accent ?? theme.accent[mode]
  const effectiveRadius = prefs.radius ?? theme.radius ?? style.radius
  const labelOnPrimary = useMemo(() => checks(prefs, mode).find((c) => c.name === 'label on primary button')?.ratio ?? 0, [prefs, mode])

  const commitHex = (value: string) => {
    const hex = value.trim().startsWith('#') ? value.trim() : `#${value.trim()}`
    if (/^#[0-9a-fA-F]{6}$/.test(hex)) update({ accent: hex.toLowerCase() })
  }

  const THEMES = themesFor(prefs.experience)
  const themeIndex = Math.max(0, THEMES.findIndex((t) => t.id === prefs.theme))
  const styleIndex = Math.max(0, STYLES.findIndex((s) => s.id === style.id))

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <SyncStatus />
        <div className="flex flex-wrap items-center gap-2">
          <Button variant="ghost" size="sm" onClick={undo} disabled={!canUndo}>
            <Undo2 className="h-4 w-4" aria-hidden="true" /> Undo
          </Button>
          <Button variant="secondary" size="sm" onClick={resetToTheme} disabled={!hasOverrides}>
            <RotateCcw className="h-4 w-4" aria-hidden="true" /> Reset to theme defaults
          </Button>
        </div>
      </div>

      <ExperienceSwitch />

      <Section title="Theme" description="Each theme has its own colours, type, surfaces and feel. Pick one and the whole workspace changes.">
        <div role="radiogroup" aria-label="Theme" className="scroll-quiet -mx-1 flex snap-x snap-mandatory gap-3 overflow-x-auto px-1 pb-2 sm:mx-0 sm:grid sm:grid-cols-2 sm:gap-4 sm:overflow-visible sm:px-0 sm:pb-0 xl:grid-cols-3">
          {THEMES.map((t, i) => (
            <ThemeCard
              key={t.id}
              theme={t}
              mode={mode}
              selected={t.id === prefs.theme}
              tabIndex={i === themeIndex ? 0 : -1}
              onPick={() => selectTheme(t.id)}
              onKey={(e) => arrowKeys(e, i, THEMES.length, (next) => { selectTheme(THEMES[next].id); (e.currentTarget.parentElement?.children[next] as HTMLElement | undefined)?.focus() })}
            />
          ))}
        </div>
      </Section>

      <div className="grid items-start gap-6 lg:grid-cols-[minmax(0,1fr)_21rem]">
        <div className="space-y-6">
          <Section title="Mode" description={theme.preferredMode ? `${theme.name} is designed for ${theme.preferredMode} mode, but works in both.` : 'Light, dark, or follow your device.'}>
            <Segmented<ModePreference> label="Mode" value={prefs.mode} options={MODE_OPTIONS} onChange={(next) => update({ mode: next }, { fade: true })} />
            <p className="t-caption mt-2 inline-flex items-center gap-1.5">
              {mode === 'dark' ? <Moon className="h-3.5 w-3.5" aria-hidden="true" /> : <Sun className="h-3.5 w-3.5" aria-hidden="true" />}
              Showing {mode} {prefs.mode === 'system' && <><Monitor className="h-3.5 w-3.5" aria-hidden="true" /> (your device)</>}
            </p>
          </Section>

          <Section title="Accent" description="The colour of buttons, links and highlights. Text on it is adjusted to stay readable.">
            <div role="radiogroup" aria-label="Accent colour" className="flex flex-wrap items-center gap-2.5">
              <button
                type="button"
                role="radio"
                aria-checked={prefs.accent === null}
                aria-label={`${theme.name} accent`}
                onClick={() => update({ accent: null })}
                className={`interactive relative flex h-9 items-center gap-2 rounded-full border-2 px-3 text-xs font-medium ${prefs.accent === null ? 'border-primary' : 'border-[color:var(--color-border)] hover:border-[color:var(--color-border-strong)]'}`}
              >
                <span className="h-4 w-4 rounded-full" style={{ background: theme.accent[mode] }} />
                Theme
              </button>
              {ACCENT_SWATCHES.map((swatch) => {
                const selected = prefs.accent === swatch.color
                return (
                  <button
                    key={swatch.color}
                    type="button"
                    role="radio"
                    aria-checked={selected}
                    aria-label={swatch.name}
                    title={swatch.name}
                    onClick={() => update({ accent: swatch.color })}
                    className={`interactive relative h-9 w-9 rounded-full border-2 p-0.5 ${selected ? 'border-primary' : 'border-transparent hover:border-[color:var(--color-border-strong)]'}`}
                  >
                    <span className="flex h-full w-full items-center justify-center rounded-full" style={{ background: swatch.color }}>
                      {selected && <Check className="h-4 w-4 text-white drop-shadow" strokeWidth={3} aria-hidden="true" />}
                    </span>
                  </button>
                )
              })}
              <label className="relative inline-flex h-9 cursor-pointer items-center gap-2 rounded-full border-2 border-dashed border-[color:var(--color-border-strong)] px-3 text-xs font-medium hover:border-primary focus-within:ring-[3px] focus-within:ring-[color:var(--orion-ring)]">
                <input
                  type="color"
                  value={effectiveAccent}
                  onChange={(e) => update({ accent: e.target.value })}
                  className="h-5 w-5 cursor-pointer appearance-none rounded-full border-0 bg-transparent p-0"
                  aria-label="Pick a custom accent colour"
                />
                Custom
              </label>
            </div>
            <div className="mt-3 flex flex-wrap items-end gap-3">
              <Field label="Hex colour" className="w-36">
                <Input
                  value={accentText || (prefs.accent ?? '')}
                  placeholder={theme.accent[mode]}
                  maxLength={7}
                  spellCheck={false}
                  onChange={(e) => {
                    setAccentText(e.target.value)
                    commitHex(e.target.value)
                  }}
                  onBlur={() => setAccentText('')}
                />
              </Field>
              <p className="t-caption pb-2.5">
                Button text contrast {labelOnPrimary.toFixed(1)}:1 {labelOnPrimary >= 4.5 ? '(meets AA)' : ''}
              </p>
            </div>
          </Section>

          <Section title="Style" description="How surfaces are treated: corners, shadows, glass and light.">
            <div role="radiogroup" aria-label="Style" className="scroll-quiet -mx-1 flex snap-x snap-mandatory gap-3 overflow-x-auto px-1 pb-2 sm:mx-0 sm:grid sm:grid-cols-2 sm:overflow-visible sm:px-0 sm:pb-0 xl:grid-cols-3">
              {STYLES.map((s, i) => (
                <StyleCard
                  key={s.id}
                  style={s}
                  prefs={prefs}
                  mode={mode}
                  selected={s.id === style.id}
                  themeDefault={s.id === theme.style}
                  tabIndex={i === styleIndex ? 0 : -1}
                  onPick={() => update({ style: s.id === theme.style ? null : s.id }, { fade: true })}
                  onKey={(e) => arrowKeys(e, i, STYLES.length, (next) => { update({ style: STYLES[next].id === theme.style ? null : STYLES[next].id }, { fade: true }); (e.currentTarget.parentElement?.children[next] as HTMLElement | undefined)?.focus() })}
                />
              ))}
            </div>
          </Section>

          <Section title="Layout" description="How roomy and how round the interface is.">
            <div className="space-y-5">
              <div>
                <div className="flex items-center justify-between">
                  <label htmlFor="radius" className="t-label">Corner radius</label>
                  <span className="flex items-center gap-2">
                    <span className="t-caption t-num">{Math.round(effectiveRadius * 100)}%</span>
                    {prefs.radius !== null && (
                      <button type="button" className="t-caption underline" onClick={() => update({ radius: null })}>Use theme's</button>
                    )}
                  </span>
                </div>
                <div className="mt-2 flex items-center gap-3">
                  <span className="t-caption">Sharp</span>
                  <input id="radius" type="range" min={0} max={100} step={5} value={Math.round(effectiveRadius * 100)} onChange={(e) => update({ radius: Number(e.target.value) / 100 })} className="h-2 flex-1 cursor-pointer accent-[color:var(--orion-primary)]" />
                  <span className="t-caption">Rounded</span>
                </div>
              </div>
              <div>
                <p className="t-label mb-2">Density</p>
                <Segmented<Density> label="Density" value={prefs.density} options={DENSITY_OPTIONS} onChange={(next) => update({ density: next })} />
              </div>
              <div>
                <div className="flex items-center justify-between">
                  <label htmlFor="scale" className="t-label">Interface size</label>
                  <span className="flex items-center gap-2">
                    <span className="t-caption t-num">{prefs.scale}%</span>
                    {prefs.scale !== 100 && <button type="button" className="t-caption underline" onClick={() => update({ scale: 100 })}>Reset</button>}
                  </span>
                </div>
                <div className="mt-2 flex items-center gap-3">
                  <span className="t-caption">Smaller</span>
                  <input id="scale" type="range" min={85} max={125} step={5} value={prefs.scale} onChange={(e) => update({ scale: Number(e.target.value) })} className="h-2 flex-1 cursor-pointer accent-[color:var(--orion-primary)]" />
                  <span className="t-caption">Larger</span>
                </div>
              </div>
            </div>
          </Section>

          <Section title="Accessibility" description="Easier reading and calmer movement.">
            <div className="space-y-4">
              <Switch label="Higher contrast" hint="Stronger text and visible borders." checked={prefs.contrast === 'high'} onChange={(v) => update({ contrast: v ? 'high' : 'standard' })} />
              <Switch label="Reduce motion" hint="No sliding or fading. Your device's reduce-motion setting is always respected too." checked={prefs.motion === 'reduced'} onChange={(v) => update({ motion: v ? 'reduced' : 'full' })} />
            </div>
          </Section>

          <details className="panel group p-5">
            <summary className="flex cursor-pointer list-none items-center justify-between">
              <span>
                <span className="t-h2 block">Advanced</span>
                <span className="t-small text-[color:var(--color-text-muted)]">Gradients and the glow behind the page.</span>
              </span>
              <ChevronDown className="h-4 w-4 transition-transform group-open:rotate-180" aria-hidden="true" />
            </summary>
            <div className="mt-4 space-y-4">
              <div>
                <p className="t-label mb-2">Accent gradients</p>
                <Segmented<'theme' | 'on' | 'off'>
                  label="Accent gradients"
                  value={prefs.gradient === null ? 'theme' : prefs.gradient ? 'on' : 'off'}
                  options={[{ id: 'theme', label: "Theme's choice" }, { id: 'on', label: 'On' }, { id: 'off', label: 'Off' }]}
                  onChange={(v) => update({ gradient: v === 'theme' ? null : v === 'on' })}
                />
              </div>
              <div>
                <p className="t-label mb-2">Background glow</p>
                <Segmented<'theme' | 'on' | 'off'>
                  label="Background glow"
                  value={prefs.ambient === null ? 'theme' : prefs.ambient ? 'on' : 'off'}
                  options={[{ id: 'theme', label: "Theme's choice" }, { id: 'on', label: 'On' }, { id: 'off', label: 'Off' }]}
                  onChange={(v) => update({ ambient: v === 'theme' ? null : v === 'on' })}
                />
              </div>
            </div>
          </details>
        </div>

        <aside className="lg:sticky lg:top-4">
          <LivePreview />
        </aside>
      </div>
    </div>
  )
}
