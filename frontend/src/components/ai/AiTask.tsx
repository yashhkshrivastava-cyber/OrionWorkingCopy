import { useCallback, useRef, useState, type ReactNode } from 'react'
import { AlertTriangle, Loader2, Sparkles } from 'lucide-react'

/** What every AI help endpoint answers: it worked, it needs a yes to send this off the computer, or it cannot be done. */
export type AiOutcome<T> =
  | ({ status: 'ok'; where?: 'local' | 'cloud'; provider?: string } & T)
  | { status: 'needs_consent'; message: string }
  | { status: 'unavailable'; message: string }

type Phase = 'idle' | 'working' | 'ok' | 'consent' | 'unavailable' | 'error'

export type AiTask<T> = {
  phase: Phase
  message: string
  result: (T & { where?: 'local' | 'cloud'; provider?: string }) | null
  /** Starts a request. `call` is given whether the person has said yes to sending it to a cloud AI service. */
  run: (call: (cloudOnce: boolean) => Promise<AiOutcome<T>>) => void
  /** The person's yes for this one request: asks again, this time with permission to use the cloud. */
  confirm: () => void
  reset: () => void
  busy: boolean
}

/**
 * One request for AI help and its three possible endings. The same hook serves every screen, so a person meets the same
 * words and the same question ("send this to a cloud AI service, this once?") wherever they ask. The answer is held here
 * for the screen to show; nothing is applied until the person chooses to.
 */
export function useAiTask<T>(): AiTask<T> {
  const [phase, setPhase] = useState<Phase>('idle')
  const [message, setMessage] = useState('')
  const [result, setResult] = useState<AiTask<T>['result']>(null)
  const last = useRef<((cloudOnce: boolean) => Promise<AiOutcome<T>>) | null>(null)
  const token = useRef(0)

  const execute = useCallback((cloudOnce: boolean) => {
    const call = last.current
    if (!call) return
    const mine = ++token.current
    setPhase('working')
    setMessage('')
    call(cloudOnce)
      .then((outcome) => {
        if (mine !== token.current) return
        if (outcome.status === 'ok') {
          setResult(outcome as AiTask<T>['result'])
          setPhase('ok')
        } else {
          setMessage(outcome.message)
          setPhase(outcome.status === 'needs_consent' ? 'consent' : 'unavailable')
        }
      })
      .catch((err: Error) => {
        if (mine !== token.current) return
        setMessage(err.message || 'That did not work. Try again.')
        setPhase('error')
      })
  }, [])

  return {
    phase,
    message,
    result,
    run: (call) => {
      last.current = call
      setResult(null)
      execute(false)
    },
    confirm: () => execute(true),
    reset: () => {
      token.current += 1
      setPhase('idle')
      setMessage('')
      setResult(null)
    },
    busy: phase === 'working',
  }
}

/** Where an answer came from, so nobody is left wondering whether it left the computer. */
export function AiProvenance({ where, provider }: { where?: 'local' | 'cloud'; provider?: string }) {
  if (!where) return null
  return (
    <span className="text-[11px] font-normal text-[color:var(--color-text-faint)]">
      {where === 'local' ? 'Written on this computer' : `Written by cloud AI${provider ? ` (${provider})` : ''}`}
    </span>
  )
}

/** The working, ask-first and could-not states of a task. Shows nothing while idle or when there is an answer. */
export function AiNotice<T>({ task, className = '' }: { task: AiTask<T>; className?: string }) {
  if (task.phase === 'working') {
    return (
      <p className={`flex items-center gap-2 text-sm text-[color:var(--color-text-muted)] ${className}`} role="status">
        <Loader2 className="h-4 w-4 animate-spin text-accent" aria-hidden="true" />
        Working on it…
      </p>
    )
  }
  if (task.phase === 'consent') {
    return (
      <div className={`space-y-2 rounded-xl border border-[color:var(--color-border)] bg-muted/60 p-3 text-sm ${className}`} role="alert">
        <p className="flex items-start gap-2">
          <Sparkles className="mt-0.5 h-4 w-4 shrink-0 text-accent" aria-hidden="true" />
          <span>{task.message}</span>
        </p>
        <p className="text-xs text-[color:var(--color-text-faint)]">
          It is sent only for this one request. What comes back is a draft: nothing is saved or sent until you do it.
        </p>
        <div className="flex gap-2">
          <button type="button" onClick={task.confirm} className="interactive rounded-lg bg-primary px-3 py-1.5 text-xs font-semibold text-on-primary">
            Send this once
          </button>
          <button type="button" onClick={task.reset} className="interactive rounded-lg border border-[color:var(--color-border-strong)] px-3 py-1.5 text-xs font-medium">
            Cancel
          </button>
        </div>
      </div>
    )
  }
  if (task.phase === 'unavailable' || task.phase === 'error') {
    return (
      <p className={`flex items-start gap-2 text-sm text-[color:var(--color-text-muted)] ${className}`} role="alert">
        <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0 text-warning" aria-hidden="true" />
        <span>{task.message}</span>
      </p>
    )
  }
  return null
}

/** A small sparkle button for starting AI help, in the style of the app's other quiet actions. */
export function AiButton({
  onClick,
  disabled,
  children,
  title,
}: {
  onClick: () => void
  disabled?: boolean
  children: ReactNode
  title?: string
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      disabled={disabled}
      title={title}
      className="interactive inline-flex h-8 items-center gap-1.5 rounded-lg border border-transparent px-2.5 text-xs font-semibold text-accent hover:bg-accent-dim disabled:cursor-not-allowed disabled:opacity-50"
    >
      <Sparkles className="h-3.5 w-3.5" aria-hidden="true" />
      {children}
    </button>
  )
}
