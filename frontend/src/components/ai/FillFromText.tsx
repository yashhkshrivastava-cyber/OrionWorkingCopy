import { useState } from 'react'
import { api } from '../../api/client'
import { Button } from '../ui/Button'
import { Textarea } from '../ui/Field'
import { AiButton, AiNotice, AiProvenance, useAiTask } from './AiTask'

/**
 * "Fill from text" above a record form: paste an email, a message or a few lines and the AI proposes values for the
 * plain fields. Nothing is typed into the form until the person presses "Put these in the form", and the form is not
 * saved by this; they read it over and save it as they would anything they typed. Fields that link to other records,
 * fields the form works out and private fields are never filled.
 */
export function FillFromText({ entity, onFill }: { entity: string; onFill: (values: Record<string, unknown>) => void }) {
  const [open, setOpen] = useState(false)
  const [text, setText] = useState('')
  const task = useAiTask<{ values: Record<string, unknown>; labels: Record<string, string> }>()
  const found = task.result
  const keys = found ? Object.keys(found.values) : []

  if (!open) {
    return (
      <div className="mb-4">
        <AiButton onClick={() => setOpen(true)} title="Paste a message or a few lines and let the AI fill the plain fields">
          Fill from text
        </AiButton>
      </div>
    )
  }

  return (
    <section className="mb-5 max-w-2xl space-y-3 rounded-xl border border-[color:var(--color-border)] bg-muted/40 p-4" aria-label="Fill the form from text">
      <div>
        <p className="text-sm font-semibold">Fill from text</p>
        <p className="text-xs text-[color:var(--color-text-muted)]">
          Paste an email, a message or a few lines. The AI suggests values; you check them in the form before saving.
          Fields that link to another record are left for you.
        </p>
      </div>
      <Textarea
        rows={5}
        value={text}
        maxLength={6000}
        aria-label="Text to fill the form from"
        placeholder="For example: New guard Ramesh Patil, joining 1 November at the Narmada plant, mobile 98765 43210…"
        onChange={(event) => setText(event.target.value)}
      />
      <div className="flex flex-wrap gap-2">
        <Button
          size="sm"
          loading={task.busy}
          disabled={text.trim().length < 10}
          onClick={() => task.run((cloudOnce) => api.entityFillAi(entity, text, cloudOnce))}
        >
          Suggest values
        </Button>
        <Button
          size="sm"
          variant="ghost"
          onClick={() => {
            task.reset()
            setOpen(false)
          }}
        >
          Close
        </Button>
      </div>
      <AiNotice task={task} />
      {task.phase === 'ok' && found && (
        <div className="space-y-2 rounded-lg border border-[color:var(--color-border)] bg-surface p-3 text-sm">
          <div className="flex items-center justify-between gap-2">
            <p className="text-xs font-semibold">{keys.length ? `Found ${keys.length} ${keys.length === 1 ? 'value' : 'values'}` : 'Nothing to fill in'}</p>
            <AiProvenance where={found.where} provider={found.provider} />
          </div>
          {keys.length > 0 ? (
            <>
              <dl className="grid grid-cols-[10rem_1fr] gap-x-3 gap-y-1 text-xs">
                {keys.map((key) => (
                  <div key={key} className="contents">
                    <dt className="text-[color:var(--color-text-muted)]">{found.labels[key] ?? key}</dt>
                    <dd className="break-words">{String(found.values[key])}</dd>
                  </div>
                ))}
              </dl>
              <Button
                size="sm"
                onClick={() => {
                  onFill(found.values)
                  task.reset()
                  setOpen(false)
                  setText('')
                }}
              >
                Put these in the form
              </Button>
            </>
          ) : (
            <p className="text-xs text-[color:var(--color-text-muted)]">The text did not contain anything this form asks for.</p>
          )}
        </div>
      )}
    </section>
  )
}
