import { Fragment, useState } from 'react'
import { Link } from 'react-router-dom'
import { TabLink } from '../ui/TabLink'
import { Check, ChevronDown, CircleAlert, Cloud, Copy, Cpu, ExternalLink, LoaderCircle, Palette, RefreshCw, ServerOff, Sparkles, TriangleAlert, Zap } from 'lucide-react'
import { providerLabel } from '../../ai/labels'
import { plainText } from '../../ai/transcript'
import type { AiMessage, AiPart, AiRoute, AiSource } from '../../types'
import { Button } from '../ui/Button'
import { Markdown } from './Markdown'
import { BlockView } from './Blocks'
import { ConfirmCard } from './ConfirmCard'

type ToolPart = Extract<AiPart, { type: 'tool' }>

/** The assistant's mark: the accent, so it follows the theme. */
export function AssistantMark({ size = 28 }: { size?: number }) {
  return (
    <span
      className="accent-fill btn-primary grid shrink-0 place-items-center rounded-full"
      style={{ width: size, height: size }}
      aria-hidden="true"
    >
      <Sparkles style={{ width: size * 0.5, height: size * 0.5 }} />
    </span>
  )
}

// ------------------------------------------------------------------------------------------------ the steps

function Steps({ steps, live }: { steps: ToolPart[]; live: boolean }) {
  const [open, setOpen] = useState(false)
  const running = steps.some((step) => step.status === 'running')
  const shown = live || open
  const problems = steps.filter((step) => step.status === 'error' || step.status === 'denied').length
  return (
    <div className="rounded-lg border border-[color:var(--color-border)] bg-muted/40 px-3 py-2">
      <button
        type="button"
        onClick={() => setOpen((value) => !value)}
        disabled={live}
        aria-expanded={shown}
        className="flex w-full items-center gap-2 text-left text-xs font-medium text-[color:var(--color-text-muted)] disabled:cursor-default"
      >
        {running ? <LoaderCircle className="h-3.5 w-3.5 animate-spin text-accent" aria-hidden="true" /> : <Check className="h-3.5 w-3.5 text-positive" aria-hidden="true" />}
        <span>
          {running ? 'Looking things up…' : `Checked ${steps.length} ${steps.length === 1 ? 'thing' : 'things'}${problems ? ` · ${problems} could not be done` : ''}`}
        </span>
        {!live && <ChevronDown className={`ml-auto h-3.5 w-3.5 transition ${open ? 'rotate-180' : ''}`} aria-hidden="true" />}
      </button>
      {shown && (
        <ul className="mt-1.5 space-y-1 border-t border-[color:var(--color-border)] pt-1.5">
          {steps.map((step) => (
            <li key={step.id} className="flex items-start gap-2 text-xs text-[color:var(--color-text-muted)]">
              {step.status === 'running' ? (
                <LoaderCircle className="mt-0.5 h-3 w-3 shrink-0 animate-spin text-accent" aria-hidden="true" />
              ) : step.status === 'done' ? (
                <Check className="mt-0.5 h-3 w-3 shrink-0 text-positive" aria-hidden="true" />
              ) : (
                <CircleAlert className="mt-0.5 h-3 w-3 shrink-0 text-negative" aria-hidden="true" />
              )}
              <span className="min-w-0">
                <span className="font-medium text-[color:var(--color-text)]">{step.label}</span>
                {step.summary && <span> · {step.summary}</span>}
              </span>
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}

function Sources({ sources }: { sources: AiSource[] }) {
  return (
    <div className="flex flex-wrap items-center gap-1.5">
      <span className="eyebrow mr-0.5">Sources</span>
      {sources.map((source) => {
        const inner = (
          <>
            <span className="font-semibold">{source.label}</span>
            {source.detail && <span className="text-[color:var(--color-text-muted)]"> · {source.detail}</span>}
            {source.path && <ExternalLink className="ml-1 inline h-3 w-3 text-[color:var(--color-text-faint)]" aria-hidden="true" />}
          </>
        )
        const cls = 'interactive max-w-full truncate rounded-full border border-[color:var(--color-border)] bg-surface px-2.5 py-1 text-[11px]'
        return source.path ? (
          <TabLink key={source.label + source.detail} to={source.path} className={`${cls} hover:border-[color:var(--color-border-strong)] hover:bg-muted`}>
            {inner}
          </TabLink>
        ) : (
          <span key={source.label + source.detail} className={cls}>
            {inner}
          </span>
        )
      })}
    </div>
  )
}

function UiNote({ part }: { part: Extract<AiPart, { type: 'ui' }> }) {
  const action = part.action
  if (action.type === 'navigate') {
    return (
      <Link to={action.path} className="interactive inline-flex w-fit items-center gap-1.5 rounded-full border border-[color:var(--color-border)] bg-surface px-3 py-1 text-xs font-medium hover:bg-muted">
        <ExternalLink className="h-3.5 w-3.5 text-accent" aria-hidden="true" />
        Opened {action.label}
      </Link>
    )
  }
  return (
    <span className="inline-flex w-fit items-center gap-1.5 rounded-full border border-[color:var(--color-border)] bg-surface px-3 py-1 text-xs font-medium">
      <Palette className="h-3.5 w-3.5 text-accent" aria-hidden="true" />
      Changed the look{action.theme ? ` to ${action.theme}` : ''}
      {action.mode ? ` (${action.mode} mode)` : ''}
    </span>
  )
}

// ------------------------------------------------------------------------------------------------ one message

function Dots() {
  return (
    <span className="inline-flex items-center gap-1 py-2" role="status" aria-label="Working on it">
      {[0, 1, 2].map((n) => (
        <span key={n} className="h-1.5 w-1.5 animate-pulse rounded-full bg-[color:var(--color-text-faint)]" style={{ animationDelay: `${n * 160}ms` }} />
      ))}
    </span>
  )
}

/**
 * How this answer was made, said plainly. "Local AI" is never shown for an answer that went to a cloud model; the label comes
 * from the server, which is the one that knows where the question was sent.
 */
function RouteChip({ route }: { route: AiRoute }) {
  const Icon = route.path === 'cloud' ? Cloud : route.path === 'local' ? Cpu : Zap
  const tone =
    route.path === 'cloud'
      ? 'bg-warning-dim text-warning'
      : route.path === 'local'
        ? 'bg-accent-dim text-accent'
        : 'bg-muted text-[color:var(--color-text-muted)]'
  const label = route.path === 'local' && route.model ? `${route.label} · ${route.model.split(':')[0]}` : route.label
  const detail =
    route.path === 'cloud'
      ? 'Your question and the figures needed to answer it were sent to a cloud AI service, with names replaced.'
      : route.path === 'local'
        ? 'Answered by the AI model running on this computer. Nothing was sent out.'
        : 'Answered by Orion directly from your data. No AI model was needed, and nothing was sent out.'
  return (
    <span className="flex flex-wrap items-center gap-x-2 gap-y-0.5">
      <span title={`${route.reason} ${detail}`} className={`inline-flex w-fit items-center gap-1 rounded-full px-2 py-0.5 text-[11px] font-semibold ${tone}`}>
        <Icon className="h-3 w-3" aria-hidden="true" />
        {label}
      </span>
      {route.escalated && <span className="t-caption">Used because the local AI could not complete this.</span>}
    </span>
  )
}

function Notice({ part, onUseCloud, cloudProvider }: { part: Extract<AiPart, { type: 'notice' }>; onUseCloud: () => void; cloudProvider: string }) {
  if (part.kind === 'unverified') {
    return (
      <p className="flex items-start gap-2 rounded-lg bg-warning-dim px-3 py-2 text-xs text-warning" role="note">
        <TriangleAlert className="mt-0.5 h-3.5 w-3.5 shrink-0" aria-hidden="true" />
        <span>I could not match {part.figures?.length ? part.figures.join(', ') : 'some figures'} to your data. Please check before relying on it.</span>
      </p>
    )
  }
  if (part.kind === 'local_unavailable') {
    return (
      <div className="panel space-y-3 p-3.5" role="note">
        <p className="flex items-start gap-2.5 text-[13px]">
          <ServerOff className="mt-0.5 h-4 w-4 shrink-0 text-[color:var(--color-text-muted)]" aria-hidden="true" />
          <span>{part.text}</span>
        </p>
        <div className="flex flex-wrap items-center gap-2">
          {part.can_use_cloud && (
            <Button size="sm" variant="secondary" onClick={onUseCloud}>
              <Cloud className="h-3.5 w-3.5" aria-hidden="true" />
              Use cloud AI for this question
            </Button>
          )}
          <Link to="/settings?tab=ai" className="text-xs font-semibold text-accent hover:underline">
            Set up local AI
          </Link>
        </div>
        {part.can_use_cloud && (
          <p className="t-caption">
            Only this question{cloudProvider && cloudProvider !== 'none' ? ` goes to ${providerLabel(cloudProvider)}` : ' is sent'}, with names in any figures replaced. It counts against your cloud allowance.
          </p>
        )}
      </div>
    )
  }
  return (
    <p className="t-caption flex items-start gap-1.5">
      <Cpu className="mt-0.5 h-3 w-3 shrink-0" aria-hidden="true" />
      {part.text}
    </p>
  )
}

export function UserBubble({ message }: { message: AiMessage }) {
  return (
    <div className="flex justify-end">
      <p className="t-body max-w-[88%] whitespace-pre-wrap break-words rounded-2xl rounded-br-md bg-muted px-3.5 py-2 text-[color:var(--color-text)]">
        {message.text}
      </p>
    </div>
  )
}

export function AssistantMessage({
  message,
  live,
  last,
  canRegenerate,
  onRegenerate,
  onConfirm,
  onCancel,
  onUseCloud,
  cloudProvider,
}: {
  message: AiMessage
  /** This is the answer being written right now. */
  live: boolean
  last: boolean
  canRegenerate: boolean
  onRegenerate: () => void
  onConfirm: (id: string) => void
  onCancel: (id: string) => void
  onUseCloud: () => void
  cloudProvider: string
}) {
  const [copied, setCopied] = useState(false)
  const body = plainText(message)

  const copy = async () => {
    try {
      await navigator.clipboard.writeText(body)
      setCopied(true)
      window.setTimeout(() => setCopied(false), 1600)
    } catch {
      /* the browser refused; nothing else to do */
    }
  }

  // Consecutive steps are one group; everything else is drawn in the order it arrived.
  const groups: (AiPart | ToolPart[])[] = []
  for (const part of message.parts) {
    if (part.type === 'tool') {
      const prev = groups[groups.length - 1]
      if (Array.isArray(prev)) prev.push(part)
      else groups.push([part])
    } else groups.push(part)
  }
  const empty = message.parts.length === 0
  // "I've prepared that, please confirm" is stale once the card above it has been answered, and the card says it better.
  const answered = message.parts.findIndex((part) => part.type === 'confirm' && part.action.status !== 'pending' && part.action.status !== 'confirming')
  const hasConfirm = message.parts.some((part) => part.type === 'confirm')

  return (
    <div className="group flex gap-2.5">
      <AssistantMark size={26} />
      <div className="min-w-0 flex-1 space-y-2.5">
        {empty && live && <Dots />}
        {groups.map((group, at) => {
          if (Array.isArray(group)) return <Steps key={at} steps={group} live={live && at === groups.length - 1 && group.some((s) => s.status === 'running')} />
          switch (group.type) {
            case 'text': {
              const stale = answered !== -1 && message.parts.indexOf(group) > answered && group.text.length < 400
              return group.text.trim() && !stale ? <Markdown key={at} text={group.text} /> : <Fragment key={at} />
            }
            case 'block':
              return <BlockView key={at} block={group.block} />
            case 'ui':
              return <UiNote key={at} part={group} />
            case 'confirm':
              return <ConfirmCard key={at} action={group.action} onConfirm={onConfirm} onCancel={onCancel} />
            case 'sources':
              return <Sources key={at} sources={group.sources} />
            case 'notice':
              return <Notice key={at} part={group} onUseCloud={onUseCloud} cloudProvider={cloudProvider} />
            case 'route':
              return <RouteChip key={at} route={group} />
            case 'stopped':
              return (
                <p key={at} className="t-caption italic">
                  Stopped.
                </p>
              )
            default:
              return <Fragment key={at} />
          }
        })}
        {live && !empty && groups[groups.length - 1] && (Array.isArray(groups[groups.length - 1]) ? false : (groups[groups.length - 1] as AiPart).type === 'block') && <Dots />}
        {!live && body && (
          <div className="flex items-center gap-1 pt-0.5 opacity-70 transition group-hover:opacity-100 focus-within:opacity-100">
            <button
              type="button"
              onClick={copy}
              className="interactive inline-flex items-center gap-1 rounded-md px-1.5 py-1 text-[11px] font-medium text-[color:var(--color-text-muted)] hover:bg-muted hover:text-[color:var(--color-text)]"
            >
              {copied ? <Check className="h-3.5 w-3.5 text-positive" aria-hidden="true" /> : <Copy className="h-3.5 w-3.5" aria-hidden="true" />}
              {copied ? 'Copied' : 'Copy'}
            </button>
            {last && canRegenerate && !hasConfirm && (
              <button
                type="button"
                onClick={onRegenerate}
                className="interactive inline-flex items-center gap-1 rounded-md px-1.5 py-1 text-[11px] font-medium text-[color:var(--color-text-muted)] hover:bg-muted hover:text-[color:var(--color-text)]"
              >
                <RefreshCw className="h-3.5 w-3.5" aria-hidden="true" />
                Regenerate
              </button>
            )}
          </div>
        )}
      </div>
    </div>
  )
}
