import { useState } from 'react'
import { AlertTriangle, ArrowUpRight, Info, ServerOff, TriangleAlert, X } from 'lucide-react'
import { Link } from 'react-router-dom'
import { useAssistant } from '../../ai/AssistantContext'
import { useAuth } from '../../context/AuthContext'
import type { AiInsight } from '../../types'
import { AssistantMark } from './MessageView'

const SEVERITY = {
  critical: { icon: TriangleAlert, tone: 'bg-negative-dim text-negative' },
  warning: { icon: AlertTriangle, tone: 'bg-warning-dim text-warning' },
  info: { icon: Info, tone: 'bg-accent-dim text-accent' },
} as const

function InsightCard({ insight, onInvestigate, onDismiss }: { insight: AiInsight; onInvestigate: () => void; onDismiss: () => void }) {
  const { icon: Icon, tone } = SEVERITY[insight.severity]
  return (
    <li className="panel flex items-start gap-3 p-3">
      <span className={`mt-0.5 grid h-7 w-7 shrink-0 place-items-center rounded-lg ${tone}`}>
        <Icon className="h-4 w-4" aria-hidden="true" />
      </span>
      <div className="min-w-0 flex-1">
        <p className="text-[13px] font-semibold leading-snug">{insight.headline}</p>
        {insight.body && <p className="t-caption mt-0.5 line-clamp-2">{insight.body}</p>}
        <button
          type="button"
          onClick={onInvestigate}
          className="interactive mt-1.5 inline-flex items-center gap-1 text-xs font-semibold text-accent hover:underline"
        >
          Investigate
          <ArrowUpRight className="h-3.5 w-3.5" aria-hidden="true" />
        </button>
      </div>
      <button
        type="button"
        onClick={onDismiss}
        aria-label={`Hide for a week: ${insight.headline}`}
        title="Hide for a week"
        className="interactive -mr-1 -mt-1 rounded-md p-1 text-[color:var(--color-text-faint)] hover:bg-muted hover:text-[color:var(--color-text)]"
      >
        <X className="h-3.5 w-3.5" />
      </button>
    </li>
  )
}

/** What the panel shows before anything has been asked: what is worth a look, and what to ask. */
export function Welcome() {
  const { user } = useAuth()
  const { status, insights, suggestions, dismissInsight, ask, send } = useAssistant()
  const [all, setAll] = useState(false)
  const first = (user?.display_name || '').split(' ')[0]
  const shown = all ? insights : insights.slice(0, 2)

  return (
    <div className="flex flex-col gap-5 px-4 pb-4 pt-6">
      <div className="flex flex-col items-start gap-3">
        <AssistantMark size={40} />
        <div>
          <h2 className="t-h1">{first ? `Hi ${first}.` : 'Hi.'}</h2>
          <p className="t-body mt-1 text-[color:var(--color-text-muted)]">
            Ask me about your business, or tell me what to do. I look things up in your data, so the figures are real.
          </p>
        </div>
      </div>

      {status && status.routing.local.state !== 'ok' && (
        <div className="flex items-start gap-2.5 rounded-xl border border-[color:var(--color-border-strong)] bg-muted/60 p-3.5 text-[13px]" role="note">
          <ServerOff className="mt-0.5 h-4 w-4 shrink-0 text-[color:var(--color-text-muted)]" aria-hidden="true" />
          <p>
            <span className="font-semibold">{status.routing.local.provider === 'none' ? 'No local AI model is set up.' : 'The local AI model is not running.'}</span> I can still answer questions about your
            figures, who owes what, records, reminders and reports directly. Open-ended questions need a local model.{' '}
            <Link to="/settings?tab=ai" className="font-semibold text-accent hover:underline">
              How to set it up
            </Link>
          </p>
        </div>
      )}

      {insights.length > 0 && (
        <section aria-label="Worth a look">
          <h3 className="eyebrow mb-2">Worth a look</h3>
          <ul className="space-y-2">
            {shown.map((insight) => (
              <InsightCard key={insight.id} insight={insight} onInvestigate={() => ask(insight.prompt)} onDismiss={() => dismissInsight(insight.id)} />
            ))}
          </ul>
          {insights.length > 2 && (
            <button type="button" onClick={() => setAll((value) => !value)} className="interactive mt-1.5 text-xs font-semibold text-accent hover:underline">
              {all ? 'Show fewer' : `${insights.length - 2} more`}
            </button>
          )}
        </section>
      )}

      {suggestions.length > 0 && (
        <section aria-label="Things to ask">
          <h3 className="eyebrow mb-2">Try asking</h3>
          <div className="flex flex-wrap gap-2">
            {suggestions.map((text) => (
              <button
                key={text}
                type="button"
                disabled={!status?.available}
                onClick={() => send(text)}
                className="interactive rounded-full border border-[color:var(--color-border)] bg-surface px-3 py-1.5 text-left text-[13px] hover:border-[color:var(--color-border-strong)] hover:bg-muted disabled:opacity-50"
              >
                {text}
              </button>
            ))}
          </div>
        </section>
      )}
    </div>
  )
}
