import { useEffect, useRef, useState, type ClipboardEvent } from 'react'
import { useNavigate, useParams, useSearchParams } from 'react-router-dom'
import { ChevronLeft, Copy, Printer, Save, Sparkles, Trash2 } from 'lucide-react'
import { api } from '../../api/client'
import { formatDay } from '../../components/billing/BillDocument'
import { LetterAiModal } from '../../components/letterhead/LetterAiModal'
import { LetterToolbar } from '../../components/letterhead/LetterToolbar'
import { LetterheadPrint, LetterheadSheet, useLetterheadDesign } from '../../components/letterhead/LetterheadSheet'
import { cleanPastedHtml, isBlank, prepareEditor, run, textToHtml } from '../../components/letterhead/richText'
import { templateById, today } from '../../components/letterhead/templates'
import { Alert } from '../../components/ui/Alert'
import { Button } from '../../components/ui/Button'
import { Checkbox, Field, Input, Select } from '../../components/ui/Field'
import { Modal } from '../../components/ui/Modal'
import { Segmented } from '../../components/ui/Segmented'
import { useAuth } from '../../context/AuthContext'
import { useLumen } from '../../lumen/useLumen'
import type { Letter, LetterFont } from '../../types'

const SIZES = [9, 10, 11, 12, 13, 14]

/**
 * One letter, typed on the letterhead. The page on screen is the page that prints: the same HTML is handed
 * to the browser's print, on the same letterhead.
 */
export function LetterEditorPage() {
  const { id } = useParams()
  const [search] = useSearchParams()
  const navigate = useNavigate()
  const { user } = useAuth()
  const lumen = useLumen()
  const canWrite = Boolean(user?.can_letterhead_write)
  const { design, error: designError } = useLetterheadDesign()

  const editor = useRef<HTMLDivElement>(null)
  /** The text to put in the editor once it is on screen. Typing never goes through React state. */
  const [initial, setInitial] = useState<{ key: string; html: string } | null>(null)
  const [saved, setSaved] = useState<Letter | null>(null)
  const [title, setTitle] = useState('')
  const [refNo, setRefNo] = useState('')
  const [date, setDate] = useState(today())
  const [font, setFont] = useState<LetterFont>('sans')
  const [size, setSize] = useState(11)
  const [showHeader, setShowHeader] = useState(true)
  const [showFooter, setShowFooter] = useState(true)
  const [dirty, setDirty] = useState(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')
  const [printing, setPrinting] = useState<string | null>(null)
  const [deleting, setDeleting] = useState(false)
  const [aiOpen, setAiOpen] = useState(false)

  const apply = (letter: Letter) => {
    setSaved(letter)
    setTitle(letter.title)
    setRefNo(letter.ref_no ?? '')
    setDate(letter.letter_date)
    setFont(letter.font)
    setSize(letter.font_size)
    setShowHeader(letter.show_header)
    setShowFooter(letter.show_footer)
  }

  // Open a saved letter, a copy of one, or a new one from a template.
  useEffect(() => {
    setError('')
    setNotice(search.get('saved') ? 'Saved.' : '')
    setDirty(false)
    const from = search.get('from')
    if (id) {
      api
        .letter(id)
        .then((letter) => {
          apply(letter)
          setInitial({ key: `letter-${letter.letter_id}-${letter.last_updated_timestamp}`, html: letter.body_html })
        })
        .catch((e: Error) => setError(e.message))
    } else if (from) {
      api
        .letter(from)
        .then((letter) => {
          apply({ ...letter, title: `Copy of ${letter.title}`, letter_date: today() })
          setSaved(null)
          setDirty(true)
          setInitial({ key: `copy-${letter.letter_id}`, html: letter.body_html })
        })
        .catch((e: Error) => setError(e.message))
    } else {
      const template = templateById(search.get('template'))
      setSaved(null)
      setTitle(template.title)
      setInitial({ key: `new-${template.id}`, html: template.body(today()) })
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [id])

  // The editor is filled once per document; after that the browser owns its contents. The letterhead can
  // arrive (or be refreshed) after typing has begun, and that must not put the starting text back.
  const filled = useRef('')
  useEffect(() => {
    if (!initial || !editor.current || filled.current === initial.key) return
    editor.current.innerHTML = isBlank(initial.html) ? '<p><br></p>' : initial.html
    filled.current = initial.key
  }, [initial, design])

  const currentHtml = () => editor.current?.innerHTML ?? ''

  const paste = (event: ClipboardEvent<HTMLDivElement>) => {
    event.preventDefault()
    const html = event.clipboardData.getData('text/html')
    const text = event.clipboardData.getData('text/plain')
    if (html) run('insertHTML', cleanPastedHtml(html))
    else if (text.includes('\n')) run('insertHTML', textToHtml(text))
    else run('insertText', text)
    setDirty(true)
  }

  const save = async () => {
    if (!title.trim()) {
      setError('Give the letter a name, so it can be found again.')
      return
    }
    setBusy(true)
    setError('')
    setNotice('')
    const body = {
      title,
      ref_no: refNo.trim() || null,
      letter_date: date,
      body_html: currentHtml(),
      font,
      font_size: size,
      show_header: showHeader,
      show_footer: showFooter,
    }
    try {
      if (saved) {
        const letter = await api.updateLetter(saved.letter_id, body)
        apply(letter)
        // What was stored is what the server kept. If that differs from what is on screen, show the stored one.
        if (editor.current && editor.current.innerHTML !== letter.body_html && !isBlank(letter.body_html)) {
          editor.current.innerHTML = letter.body_html
        }
        setDirty(false)
        setNotice('Saved.')
      } else {
        const letter = await api.createLetter(body)
        navigate(`/letterhead/letters/${letter.letter_id}?saved=1`, { replace: true })
      }
    } catch (e) {
      setError((e as Error).message)
    } finally {
      setBusy(false)
    }
  }

  const remove = async () => {
    if (!saved) return
    setBusy(true)
    try {
      await api.deleteLetter(saved.letter_id)
      navigate('/letterhead/letters', { replace: true })
    } catch (e) {
      setError((e as Error).message)
      setDeleting(false)
    } finally {
      setBusy(false)
    }
  }

  const leave = () => {
    if (dirty && canWrite && !window.confirm('This letter has changes that are not saved. Leave without saving?')) return
    navigate('/letterhead/letters')
  }

  const actions = (
    <div className="flex flex-wrap items-center gap-2">
          {dirty && canWrite && <span className="text-xs font-medium text-warning">Not saved</span>}
          {saved && canWrite && (
            <>
              <Button variant="ghost" size="sm" onClick={() => setDeleting(true)}>
                <Trash2 className="h-4 w-4" /> Delete
              </Button>
              <Button variant="secondary" size="sm" onClick={() => navigate(`/letterhead/letters/new?from=${saved.letter_id}`)}>
                <Copy className="h-4 w-4" /> Make a copy
              </Button>
            </>
          )}
          {canWrite && (
            <Button variant="secondary" size="sm" onClick={() => setAiOpen(true)} disabled={!design}>
              <Sparkles className="h-4 w-4 text-accent" aria-hidden="true" /> Write with AI
            </Button>
          )}
          <Button variant="secondary" onClick={() => setPrinting(currentHtml())} disabled={!design || printing !== null}>
            <Printer className="h-4 w-4" /> Print or save as PDF
          </Button>
          {canWrite && (
            <Button onClick={save} loading={busy}>
              <Save className="h-4 w-4" /> Save
            </Button>
          )}
        </div>
  )

  const bodyClass = `lh-body lh-font-${font}`
  const bodyStyle = { fontSize: `${size}pt` }

  return (
    <div className="space-y-4">
      {lumen ? (
        <div className="panel sticky top-2 z-20 flex flex-wrap items-center gap-3 !rounded-[1.75rem] !p-3">
          <button type="button" onClick={leave} aria-label="Back to the letters" title="Back to the letters" className="interactive grid h-10 w-10 shrink-0 place-items-center rounded-full border border-[color:var(--color-border)] text-[color:var(--color-text-muted)] hover:bg-muted">
            <ChevronLeft className="h-4 w-4" />
          </button>
          <input
            aria-label="Letter name"
            value={title}
            maxLength={200}
            disabled={!canWrite}
            placeholder="Name this letter, so it can be found again"
            onChange={(event) => {
              setTitle(event.target.value)
              setDirty(true)
            }}
            className="font-display h-11 min-w-[12rem] flex-1 rounded-full px-4 text-base font-semibold"
          />
          {actions}
        </div>
      ) : (
        <div className="flex flex-wrap items-center justify-between gap-2">
          <button
            type="button"
            onClick={leave}
            className="inline-flex items-center gap-1 text-sm font-medium text-[color:var(--color-text-muted)] hover:text-[color:var(--color-text)]"
          >
            <ChevronLeft className="h-4 w-4" /> Letters
          </button>
          {actions}
        </div>
      )}

      {(error || designError) && <Alert variant="error">{error || designError}</Alert>}
      {notice && !dirty && (
        <Alert variant="success" onDismiss={() => setNotice('')}>
          {notice}
        </Alert>
      )}
      {!canWrite && (
        <Alert variant="info">You can read and print this letter. Changing it needs the Letterhead write permission.</Alert>
      )}

      <div className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_19rem]">
        <div className="min-w-0 space-y-3">
          {canWrite && (
            <div className={`sticky z-10 ${lumen ? 'top-[5.25rem]' : 'top-0'}`}>
              <LetterToolbar editor={editor} onChange={() => setDirty(true)} />
            </div>
          )}
          <div className={`overflow-x-auto bg-muted p-3 sm:p-5 ${lumen ? 'rounded-[1.75rem]' : 'rounded-xl'}`}>
            {design ? (
              <LetterheadSheet design={design} showHeader={showHeader} showFooter={showFooter}>
                <div
                  ref={editor}
                  role="textbox"
                  aria-multiline="true"
                  aria-label="The letter"
                  className={bodyClass}
                  style={{
                    ...bodyStyle,
                    // Fills the page between the strips, so clicking anywhere on it puts the cursor in the letter.
                    minHeight: `${design.page.height_mm - design.layout.top_space_mm - design.layout.bottom_space_mm}mm`,
                  }}
                  contentEditable={canWrite}
                  suppressContentEditableWarning
                  spellCheck
                  onFocus={prepareEditor}
                  onInput={() => setDirty(true)}
                  onPaste={paste}
                />
              </LetterheadSheet>
            ) : (
              <div className="shimmer mx-auto h-[60vh] max-w-[210mm] rounded-lg bg-surface" aria-busy="true" />
            )}
          </div>
        </div>

        <aside className={`space-y-4 self-start p-4 xl:sticky ${lumen ? 'panel xl:top-24' : 'rounded-xl border border-[color:var(--color-border)] bg-surface xl:top-0'}`}>
          {lumen && <p className="eyebrow">About this letter</p>}
          {!lumen && (
          <Field label="Name" required>
            <Input
              value={title}
              maxLength={200}
              disabled={!canWrite}
              placeholder="What this is, for the list"
              onChange={(event) => {
                setTitle(event.target.value)
                setDirty(true)
              }}
            />
          </Field>
          )}
          <Field label="Date">
            <Input
              type="date"
              value={date}
              disabled={!canWrite}
              onChange={(event) => {
                setDate(event.target.value)
                setDirty(true)
              }}
            />
          </Field>
          <Field label="Ref. no.">
            <Input
              value={refNo}
              maxLength={120}
              disabled={!canWrite}
              onChange={(event) => {
                setRefNo(event.target.value)
                setDirty(true)
              }}
            />
          </Field>
          <p className="-mt-2 text-xs text-[color:var(--color-text-muted)]">
            The name, date and reference are for finding the letter in the list. They print only where you type them
            in the letter.
          </p>

          {canWrite && (
            <>
              <Field label="Font">
                <Segmented
                  label="Font"
                  value={font}
                  options={[
                    { id: 'sans', label: 'Arial' },
                    { id: 'serif', label: 'Times New Roman' },
                  ]}
                  onChange={(next) => {
                    setFont(next)
                    setDirty(true)
                  }}
                />
              </Field>
              <Field label="Text size">
                <Select
                  value={size}
                  onChange={(event) => {
                    setSize(Number(event.target.value))
                    setDirty(true)
                  }}
                >
                  {SIZES.map((each) => (
                    <option key={each} value={each}>
                      {each} pt
                    </option>
                  ))}
                </Select>
              </Field>
              <div className="space-y-2">
                <p className="text-[13px] font-medium text-[color:var(--color-text)]">Print with</p>
                <Checkbox
                  label="The header"
                  checked={showHeader}
                  onChange={(next) => {
                    setShowHeader(next)
                    setDirty(true)
                  }}
                />
                <Checkbox
                  label="The footer"
                  checked={showFooter}
                  onChange={(next) => {
                    setShowFooter(next)
                    setDirty(true)
                  }}
                />
                <p className="text-xs text-[color:var(--color-text-muted)]">
                  Untick both to print on paper that already has the letterhead: the text keeps the same place and the
                  space is left blank.
                </p>
              </div>
            </>
          )}

          {saved && (
            <p className="border-t border-[color:var(--color-border)] pt-3 text-xs text-[color:var(--color-text-muted)]">
              Written {formatDay(saved.created_timestamp)}
              {saved.created_by_name ? ` by ${saved.created_by_name}` : ''}. Last changed{' '}
              {formatDay(saved.last_updated_timestamp)}
              {saved.last_updated_by_name ? ` by ${saved.last_updated_by_name}` : ''}.
            </p>
          )}
        </aside>
      </div>

      {design && printing !== null && (
        <LetterheadPrint
          design={design}
          title={title.trim() || 'Letter'}
          showHeader={showHeader}
          showFooter={showFooter}
          onDone={() => setPrinting(null)}
        >
          {/* The letter exactly as typed: this is the user's own text, taken from the editor on this page. */}
          <div className={bodyClass} style={bodyStyle} dangerouslySetInnerHTML={{ __html: printing }} />
        </LetterheadPrint>
      )}

      {canWrite && (
        <LetterAiModal open={aiOpen} editor={editor} onClose={() => setAiOpen(false)} onApplied={() => setDirty(true)} />
      )}

      <Modal
        open={deleting}
        title="Delete this letter?"
        onClose={() => setDeleting(false)}
        footer={
          <>
            <Button variant="secondary" onClick={() => setDeleting(false)}>
              Keep it
            </Button>
            <Button variant="danger" onClick={remove} loading={busy}>
              Delete the letter
            </Button>
          </>
        }
      >
        <p className="text-sm text-[color:var(--color-text-muted)]">
          "{saved?.title}" will be removed from the list for everyone. A copy that was already printed or saved as a PDF
          is not affected. This cannot be undone.
        </p>
      </Modal>
    </div>
  )
}
