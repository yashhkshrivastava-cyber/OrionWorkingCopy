import { useEffect, useRef, useState, type RefObject } from 'react'
import { Check, Sparkles } from 'lucide-react'
import { api } from '../../api/client'
import { AiNotice, AiProvenance, useAiTask } from '../ai/AiTask'
import { Button } from '../ui/Button'
import { Field, Select, Textarea } from '../ui/Field'
import { Modal } from '../ui/Modal'
import { Tabs } from '../ui/Tabs'

type Mode = 'draft' | 'improve'
type Action = 'tone' | 'shorter' | 'longer' | 'grammar' | 'translate'

const TONES = [
  { id: 'professional', label: 'Professional' },
  { id: 'friendly', label: 'Friendly' },
  { id: 'firm', label: 'Firm' },
  { id: 'concise', label: 'Brief' },
  { id: 'formal', label: 'Formal (tender, government)' },
]
const LANGUAGES = ['English', 'Hindi', 'Gujarati', 'Marathi', 'Bengali', 'Tamil', 'Telugu']

/**
 * AI help for a letter: write the body from a few points, or improve what is written (the selected text, or the whole
 * letter). The answer is shown first and goes into the letter only when the person chooses where; it can be undone
 * with the editor's own undo, and the server rebuilds it from paragraphs and lists, so it can carry no markup of its own.
 */
export function LetterAiModal({
  open,
  editor,
  onClose,
  onApplied,
}: {
  open: boolean
  editor: RefObject<HTMLDivElement | null>
  onClose: () => void
  onApplied: () => void
}) {
  const [mode, setMode] = useState<Mode>('draft')
  const [brief, setBrief] = useState('')
  const [tone, setTone] = useState('professional')
  const [action, setAction] = useState<Action>('tone')
  const [language, setLanguage] = useState('Hindi')
  const [selected, setSelected] = useState('')
  const [whole, setWhole] = useState('')
  const range = useRef<Range | null>(null)
  const task = useAiTask<{ html: string; text: string }>()

  // Remember where the cursor or selection was in the letter, since opening this dialog moves focus away from it.
  useEffect(() => {
    if (!open) return
    const root = editor.current
    const selection = window.getSelection()
    range.current = null
    setSelected('')
    if (root && selection && selection.rangeCount && root.contains(selection.anchorNode)) {
      range.current = selection.getRangeAt(0).cloneRange()
      setSelected(selection.toString().trim())
    }
    setWhole((root?.innerText ?? '').trim())
    task.reset()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open])

  const target = selected || whole
  const words = target ? target.split(/\s+/).length : 0

  const start = () => {
    task.run((cloudOnce) =>
      mode === 'draft'
        ? api.letterAi({ mode: 'draft', brief, tone, allow_cloud_once: cloudOnce })
        : api.letterAi({ mode: 'improve', text: target, action, tone, language, allow_cloud_once: cloudOnce }),
    )
  }

  const place = (how: 'cursor' | 'selection' | 'all') => {
    const root = editor.current
    const html = task.result?.html
    if (!root || !html) return
    root.focus()
    const selection = window.getSelection()
    if (!selection) return
    selection.removeAllRanges()
    const next = document.createRange()
    if (how === 'all') {
      next.selectNodeContents(root)
    } else if (range.current && root.contains(range.current.commonAncestorContainer)) {
      next.setStart(range.current.startContainer, range.current.startOffset)
      next.setEnd(range.current.endContainer, range.current.endOffset)
      if (how === 'cursor') next.collapse(false)
    } else {
      next.selectNodeContents(root)
      next.collapse(false)
    }
    selection.addRange(next)
    // Going through the editor's own command keeps the browser's undo working.
    document.execCommand('insertHTML', false, html)
    onApplied()
    onClose()
  }

  const canWrite = mode === 'draft' ? brief.trim().length >= 8 : words > 0

  return (
    <Modal
      open={open}
      title="Write with AI"
      size="xl"
      onClose={onClose}
      footer={
        <>
          <Button variant="secondary" onClick={onClose}>
            Close
          </Button>
          <Button onClick={start} loading={task.busy} disabled={!canWrite}>
            <Sparkles className="h-4 w-4" aria-hidden="true" />
            {mode === 'draft' ? 'Write the letter' : 'Improve the text'}
          </Button>
        </>
      }
    >
      <div className="space-y-4">
        <Tabs
          tabs={[
            { id: 'draft' as Mode, label: 'Write from a few points' },
            { id: 'improve' as Mode, label: 'Improve what is written' },
          ]}
          active={mode}
          onChange={(next) => {
            setMode(next)
            task.reset()
          }}
        />

        {mode === 'draft' ? (
          <Field label="What should the letter say?" required>
            <Textarea
              rows={5}
              value={brief}
              maxLength={1500}
              placeholder="For example: we guard the Narmada plant; the contract ends 31 March; we want to renew it for another year at the same rates and ask for the revised work order by 15 March."
              onChange={(event) => setBrief(event.target.value)}
            />
            <p className="text-xs text-[color:var(--color-text-muted)]">
              Write only the body. The date, reference, addressee, subject and signature stay as they are on the page.
            </p>
          </Field>
        ) : (
          <>
            <p className="rounded-lg bg-muted px-3 py-2 text-sm">
              {selected ? (
                <>
                  Working on the <strong>selected text</strong> ({words} {words === 1 ? 'word' : 'words'}).
                </>
              ) : words ? (
                <>
                  Working on <strong>the whole letter</strong> ({words} words). Select some text first to change only that.
                </>
              ) : (
                'The letter is empty. Write something, or switch to “Write from a few points”.'
              )}
            </p>
            <div className="grid gap-3 sm:grid-cols-2">
              <Field label="What to do">
                <Select value={action} onChange={(event) => setAction(event.target.value as Action)}>
                  <option value="tone">Change the tone</option>
                  <option value="shorter">Make it shorter</option>
                  <option value="longer">Make it fuller</option>
                  <option value="grammar">Fix spelling and grammar</option>
                  <option value="translate">Translate</option>
                </Select>
              </Field>
              {action === 'tone' && (
                <Field label="Tone">
                  <Select value={tone} onChange={(event) => setTone(event.target.value)}>
                    {TONES.map((item) => (
                      <option key={item.id} value={item.id}>
                        {item.label}
                      </option>
                    ))}
                  </Select>
                </Field>
              )}
              {action === 'translate' && (
                <Field label="Into">
                  <Select value={language} onChange={(event) => setLanguage(event.target.value)}>
                    {LANGUAGES.map((item) => (
                      <option key={item}>{item}</option>
                    ))}
                  </Select>
                </Field>
              )}
            </div>
          </>
        )}

        {mode === 'draft' && (
          <Field label="Tone">
            <Select value={tone} onChange={(event) => setTone(event.target.value)}>
              {TONES.map((item) => (
                <option key={item.id} value={item.id}>
                  {item.label}
                </option>
              ))}
            </Select>
          </Field>
        )}

        <AiNotice task={task} />

        {task.phase === 'ok' && task.result && (
          <section className="space-y-3 rounded-xl border border-[color:var(--color-border)] p-4" aria-label="The AI's text">
            <div className="flex items-center justify-between gap-2">
              <h3 className="text-sm font-semibold">Here is the text</h3>
              <AiProvenance where={task.result.where} provider={task.result.provider} />
            </div>
            <p className="max-h-72 overflow-y-auto whitespace-pre-wrap rounded-lg bg-muted px-3 py-2.5 text-sm leading-relaxed">{task.result.text}</p>
            <div className="flex flex-wrap items-center gap-2">
              {mode === 'improve' && selected ? (
                <Button size="sm" onClick={() => place('selection')}>
                  <Check className="h-4 w-4" aria-hidden="true" /> Replace the selected text
                </Button>
              ) : mode === 'improve' ? (
                <Button size="sm" onClick={() => place('all')}>
                  <Check className="h-4 w-4" aria-hidden="true" /> Replace the whole letter
                </Button>
              ) : null}
              <Button size="sm" variant={mode === 'draft' ? 'primary' : 'secondary'} onClick={() => place('cursor')}>
                {mode === 'draft' ? 'Put it in the letter at the cursor' : 'Insert at the cursor instead'}
              </Button>
              <p className="text-xs text-[color:var(--color-text-faint)]">You can edit it in the letter, or undo with Ctrl+Z.</p>
            </div>
          </section>
        )}
      </div>
    </Modal>
  )
}
