import { Check, Sparkles } from 'lucide-react'
import { useAppearance } from '../../context/AppearanceContext'
import { DEFAULT_PREFS } from '../../theme/preferences'
import type { Experience, Mode } from '../../theme/types'
import { ThemePreview } from './ThemePreview'

const CHOICES: { id: Experience; name: string; line: string; points: string[]; theme: string }[] = [
  {
    id: 'classic',
    name: 'Classic',
    line: 'The Orion you know.',
    points: ['A dark navigation rail', 'Dense tables and dashboards', 'Six themes and six styles'],
    theme: DEFAULT_PREFS.theme,
  },
  {
    id: 'lumen',
    name: 'Lumen',
    line: 'A new way to work.',
    points: ['A floating dock and a command bar', 'A Today page made for you', 'Soft, colourful, more alive'],
    theme: 'lumen',
  },
]

/**
 * The two interfaces of the application, side by side. Both do exactly the same things with the same data; only the way the workspace is laid out,
 * drawn and animated differs. Switching is instant and can be undone from the same place.
 */
export function ExperienceSwitch() {
  const { prefs, mode, setExperience } = useAppearance()
  return (
    <section>
      <div className="mb-3">
        <h2 className="t-h3">Interface</h2>
        <p className="t-caption mt-0.5">Choose how Orion looks and feels. Nothing about your data or what you can do changes.</p>
      </div>
      <div role="radiogroup" aria-label="Interface" className="grid gap-4 sm:grid-cols-2">
        {CHOICES.map((choice) => {
          const selected = prefs.experience === choice.id
          const shown: Mode = choice.id === 'lumen' ? (mode === 'dark' ? 'dark' : 'light') : mode
          return (
            <button
              key={choice.id}
              type="button"
              role="radio"
              aria-checked={selected}
              onClick={() => setExperience(choice.id)}
              className={`group interactive relative flex flex-col rounded-2xl border-2 bg-surface p-2 text-left ${
                selected ? 'border-primary shadow-raised' : 'border-[color:var(--color-border)] hover:-translate-y-0.5 hover:border-[color:var(--color-border-strong)] hover:shadow-raised'
              }`}
            >
              <div className="relative overflow-hidden rounded-xl border border-[color:var(--color-border)]">
                <ThemePreview prefs={{ theme: choice.theme, experience: choice.id }} mode={shown} />
                {choice.id === 'lumen' && (
                  <span className="absolute left-1.5 top-1.5 inline-flex items-center gap-1 rounded-full bg-black/55 px-1.5 py-0.5 text-[10px] font-medium text-white backdrop-blur-sm">
                    <Sparkles className="h-2.5 w-2.5" aria-hidden="true" /> New
                  </span>
                )}
              </div>
              <div className="px-1.5 pb-1 pt-2.5">
                <div className="flex items-center justify-between gap-2">
                  <span className="t-h3">{choice.name}</span>
                  {selected && (
                    <span className="inline-flex h-5 w-5 items-center justify-center rounded-full bg-primary text-on-primary">
                      <Check className="h-3 w-3" strokeWidth={3} aria-hidden="true" />
                      <span className="sr-only">Selected</span>
                    </span>
                  )}
                </div>
                <p className="mt-0.5 text-[13px] font-medium text-[color:var(--color-text)]">{choice.line}</p>
                <ul className="t-caption mt-1 space-y-0.5">
                  {choice.points.map((point) => (
                    <li key={point}>• {point}</li>
                  ))}
                </ul>
              </div>
            </button>
          )
        })}
      </div>
    </section>
  )
}
