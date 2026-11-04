import type { ReactNode } from 'react'
import { Link2 } from 'lucide-react'
import { useToast } from '../ui/Toast'
import { AskAiButton } from '../assistant/Launcher'

/** Copies the address, which already carries the tab and every filter, so a colleague opens exactly this view. */
function ShareButton() {
  const toast = useToast()
  const copy = async () => {
    try {
      await navigator.clipboard.writeText(window.location.href)
      toast.show('Link copied', { detail: 'It opens this tab with the same filters.' })
    } catch {
      toast.show('Could not copy the link', { tone: 'error', detail: 'Copy it from the address bar instead.' })
    }
  }
  return (
    <button
      type="button"
      onClick={copy}
      title="Copy a link to this view, filters included"
      aria-label="Copy a link to this view"
      className="interactive inline-flex h-8 items-center gap-1.5 rounded-lg border border-[color:var(--color-border-strong)] bg-surface px-2.5 text-xs font-semibold text-[color:var(--color-text)] shadow-card hover:bg-surface-hover"
    >
      <Link2 className="h-3.5 w-3.5 text-accent" aria-hidden="true" />
      <span className="hidden sm:inline">Share</span>
    </button>
  )
}

/**
 * The title block of a dashboard: what this page is in one line, how fresh the figures are, and the few things a
 * person does from here (ask the Copilot, open the rows behind the figures, share the view).
 */
export function DashboardHeader({
  title,
  subtitle,
  status,
  actions,
  canAsk = true,
}: {
  title: string
  subtitle: string
  /** Small chips beside the actions: freshness, the latest bill. */
  status?: ReactNode
  /** Extra buttons, ahead of Share. */
  actions?: ReactNode
  /** False where the Copilot cannot read this dashboard's figures. */
  canAsk?: boolean
}) {
  return (
    <div className="flex flex-col gap-3 lg:flex-row lg:items-end lg:justify-between">
      <div className="min-w-0">
        <h1 className="page-enter t-h1 lumen-title text-[color:var(--color-text)]">{title}</h1>
        <p className="mt-1 max-w-2xl text-sm text-[color:var(--color-text-muted)]">{subtitle}</p>
      </div>
      <div className="flex flex-wrap items-center gap-2">
        {status}
        {canAsk && (
          <AskAiButton variant="secondary" prompt="Summarize what I'm looking at and tell me what needs attention.">
            Ask AI
          </AskAiButton>
        )}
        {actions}
        <ShareButton />
      </div>
    </div>
  )
}
