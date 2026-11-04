import { Sparkles } from 'lucide-react'
import { useAssistant } from '../../ai/AssistantContext'
import type { ReactNode } from 'react'

/** The top-bar button that opens and closes the Copilot. */
export function AssistantButton() {
  const { enabled, open, toggle, insights } = useAssistant()
  if (!enabled) return null
  const attention = insights.filter((item) => item.severity !== 'info').length
  const urgent = attention > 0
  const note = urgent ? `${attention} ${attention === 1 ? 'thing needs' : 'things need'} your attention` : ''
  return (
    <button
      type="button"
      onClick={toggle}
      aria-pressed={open}
      aria-label={`${open ? 'Close the Copilot' : 'Open the Copilot'}${note && !open ? `. ${note}` : ''}`}
      title={`Copilot (Ctrl+J)${note && !open ? ` · ${note}, open it to see` : ''}`}
      className={`interactive relative inline-flex h-9 items-center gap-1.5 rounded-lg border px-2.5 text-sm font-semibold ${
        open
          ? 'border-transparent bg-accent-dim text-accent'
          : 'border-[color:var(--color-border)] bg-surface text-[color:var(--color-text)] hover:border-[color:var(--color-border-strong)]'
      }`}
    >
      <Sparkles className="h-4 w-4 text-accent" aria-hidden="true" />
      <span className="hidden sm:inline">Copilot</span>
      {urgent && !open && <span className="absolute -right-0.5 -top-0.5 h-2.5 w-2.5 rounded-full bg-amber ring-2 ring-[color:var(--color-surface)]" aria-hidden="true" />}
    </button>
  )
}

/** The round button in the corner of every page, for people who look for it there. It steps aside while the panel is open. */
export function FloatingLauncher() {
  const { enabled, open, toggle } = useAssistant()
  if (!enabled || open) return null
  return (
    <button
      type="button"
      onClick={toggle}
      aria-label="Open the Copilot"
      title="Ask the Copilot (Ctrl+J)"
      className="btn-primary interactive fixed bottom-[max(1.25rem,env(safe-area-inset-bottom))] right-4 z-40 grid h-12 w-12 place-items-center rounded-full shadow-overlay sm:right-6"
    >
      <Sparkles className="h-5 w-5" aria-hidden="true" />
    </button>
  )
}

/**
 * A button for any page: asks the Copilot about what is on screen. `prompt` is what is asked; the page's own state
 * (tab, filters, open record) goes with it automatically.
 */
export function AskAiButton({
  prompt,
  children = 'Ask AI',
  variant = 'ghost',
  className = '',
}: {
  prompt: string
  children?: ReactNode
  variant?: 'ghost' | 'secondary'
  className?: string
}) {
  const { enabled, ask } = useAssistant()
  if (!enabled) return null
  const style =
    variant === 'secondary'
      ? 'border-[color:var(--color-border-strong)] bg-surface shadow-card hover:bg-surface-hover'
      : 'border-transparent text-accent hover:bg-accent-dim'
  return (
    <button
      type="button"
      onClick={() => ask(prompt)}
      className={`interactive inline-flex h-8 shrink-0 items-center gap-1.5 whitespace-nowrap rounded-lg border px-2.5 text-xs font-semibold ${style} ${className}`}
    >
      <Sparkles className="h-3.5 w-3.5" aria-hidden="true" />
      {children}
    </button>
  )
}
