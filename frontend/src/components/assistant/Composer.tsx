import { useEffect, useRef, useState } from 'react'
import { ArrowUp, MapPin, Square, X } from 'lucide-react'
import { describeContext } from '../../ai/pageContext'
import type { AiPageContext } from '../../types'

const MAX = 4000

/** The message box. Enter sends, Shift+Enter adds a line, Escape stops an answer that is being written. */
export function Composer({
  streaming,
  disabled,
  context,
  share,
  onShare,
  onSend,
  onStop,
  focusKey,
  footnote,
}: {
  streaming: boolean
  disabled?: boolean
  context: AiPageContext
  share: boolean
  onShare: (share: boolean) => void
  onSend: (text: string) => void
  onStop: () => void
  /** Changes when the box should take focus (the panel opened, a new chat began). */
  focusKey: unknown
  /** Where answers are made, in a line. */
  footnote: string
}) {
  const [text, setText] = useState('')
  const box = useRef<HTMLTextAreaElement>(null)
  const where = describeContext(context)

  useEffect(() => {
    box.current?.focus({ preventScroll: true })
  }, [focusKey])

  // Grows with what is typed, up to a few lines.
  useEffect(() => {
    const node = box.current
    if (!node) return
    node.style.height = 'auto'
    node.style.height = `${Math.min(node.scrollHeight, 168)}px`
  }, [text])

  const submit = () => {
    const value = text.trim()
    if (!value || streaming || disabled) return
    onSend(value)
    setText('')
  }

  return (
    <div className="border-t border-[color:var(--color-border)] bg-surface px-3 pb-[max(0.75rem,env(safe-area-inset-bottom))] pt-2.5">
      {where && (
        <div className="mb-2 flex">
          {share ? (
            <span className="inline-flex max-w-full items-center gap-1.5 rounded-full bg-accent-dim py-0.5 pl-2.5 pr-1 text-[11px] font-medium text-accent">
              <MapPin className="h-3 w-3 shrink-0" aria-hidden="true" />
              <span className="truncate" title="This is sent with your question so the Copilot knows what you are looking at">
                {where}
              </span>
              <button
                type="button"
                onClick={() => onShare(false)}
                aria-label="Do not share what I am looking at"
                className="interactive grid h-4 w-4 shrink-0 place-items-center rounded-full hover:bg-surface/60"
              >
                <X className="h-3 w-3" />
              </button>
            </span>
          ) : (
            <button type="button" onClick={() => onShare(true)} className="interactive inline-flex items-center gap-1.5 rounded-full border border-dashed border-[color:var(--color-border-strong)] px-2.5 py-0.5 text-[11px] font-medium text-[color:var(--color-text-muted)] hover:text-[color:var(--color-text)]">
              <MapPin className="h-3 w-3" aria-hidden="true" />
              Include what I'm looking at
            </button>
          )}
        </div>
      )}
      <div className="flex items-end gap-2 rounded-2xl border border-[color:var(--color-border-strong)] bg-[color:var(--color-bg)] py-1.5 pl-3.5 pr-1.5 focus-within:border-[color:var(--color-primary)] focus-within:shadow-[var(--orion-glow)]">
        <textarea
          ref={box}
          value={text}
          rows={1}
          maxLength={MAX}
          disabled={disabled}
          placeholder={disabled ? 'The Copilot is not available' : 'Ask about your business, or tell me what to do…'}
          aria-label="Message the Copilot"
          onChange={(event) => setText(event.target.value)}
          onKeyDown={(event) => {
            if (event.key === 'Enter' && !event.shiftKey && !event.nativeEvent.isComposing) {
              event.preventDefault()
              submit()
            } else if (event.key === 'Escape') {
              if (streaming) {
                event.stopPropagation()
                onStop()
              } else event.currentTarget.blur()
            }
          }}
          className="t-body max-h-[168px] min-h-[28px] flex-1 resize-none bg-transparent py-1 outline-none placeholder:text-[color:var(--color-text-faint)] disabled:opacity-60"
        />
        {streaming ? (
          <button
            type="button"
            onClick={onStop}
            aria-label="Stop answering"
            title="Stop (Esc)"
            className="interactive grid h-8 w-8 shrink-0 place-items-center rounded-full bg-[color:var(--color-text)] text-[color:var(--color-bg)] hover:opacity-85"
          >
            <Square className="h-3.5 w-3.5 fill-current" />
          </button>
        ) : (
          <button
            type="button"
            onClick={submit}
            disabled={!text.trim() || disabled}
            aria-label="Send"
            title="Send (Enter)"
            className="btn-primary interactive grid h-8 w-8 shrink-0 place-items-center rounded-full disabled:pointer-events-none disabled:opacity-40"
          >
            <ArrowUp className="h-4 w-4" />
          </button>
        )}
      </div>
      <p className="mt-1.5 flex items-center justify-between gap-2 px-1 text-[10.5px] text-[color:var(--color-text-faint)]">
        <span>{footnote}</span>
        {text.length > MAX - 400 && <span className="t-num">{MAX - text.length} left</span>}
      </p>
    </div>
  )
}
