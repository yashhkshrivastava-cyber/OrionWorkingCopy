import { useRef, useState, type DragEvent } from 'react'
import { Download, FileUp, RotateCcw } from 'lucide-react'
import { api } from '../../api/client'
import { Alert } from '../../components/ui/Alert'
import { Button } from '../../components/ui/Button'
import { Checkbox, Field, Select } from '../../components/ui/Field'
import { PdfFrame, PdfPreview, saveBlob } from '../../components/ui/PdfPreview'
import { Segmented } from '../../components/ui/Segmented'

const MAX_BYTES = 25 * 1024 * 1024

type Fit = 'fit' | 'keep'
type Pages = 'all' | 'first'

/**
 * Puts a PDF made somewhere else (Word, Excel, Tally, a scan) onto the letterhead, and makes blank letterhead
 * paper. The file is sent to the server, comes back stamped, and is not kept there.
 */
export function StampPdfPage() {
  const picker = useRef<HTMLInputElement>(null)
  const [file, setFile] = useState<File | null>(null)
  const [fit, setFit] = useState<Fit>('fit')
  const [pages, setPages] = useState<Pages>('all')
  const [header, setHeader] = useState(true)
  const [footer, setFooter] = useState(true)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [result, setResult] = useState<{ blob: Blob; pages: number; name: string } | null>(null)
  const [over, setOver] = useState(false)
  const [blankPages, setBlankPages] = useState(1)
  const [blank, setBlank] = useState<{ blob: Blob | null; error: string } | null>(null)

  const choose = (picked: File | undefined | null) => {
    setError('')
    setResult(null)
    if (!picked) return
    if (picked.type !== 'application/pdf' && !picked.name.toLowerCase().endsWith('.pdf')) {
      setError('Choose a PDF file. A Word or Excel file can be saved as a PDF first (File, Save As, PDF).')
      return
    }
    if (picked.size > MAX_BYTES) {
      setError('That PDF is larger than 25 MB.')
      return
    }
    setFile(picked)
  }

  const drop = (event: DragEvent<HTMLDivElement>) => {
    event.preventDefault()
    setOver(false)
    choose(event.dataTransfer.files[0])
  }

  const stamp = async () => {
    if (!file) return
    setBusy(true)
    setError('')
    try {
      const done = await api.stampPdf(file, { fit: fit === 'fit', firstPageOnly: pages === 'first', header, footer })
      setResult({ ...done, name: `${file.name.replace(/\.pdf$/i, '')} on letterhead.pdf` })
    } catch (e) {
      setError((e as Error).message)
    } finally {
      setBusy(false)
    }
  }

  const startAgain = () => {
    setFile(null)
    setResult(null)
    setError('')
    if (picker.current) picker.current.value = ''
  }

  const openBlank = () => {
    setBlank({ blob: null, error: '' })
    api
      .pdfBlob(`/letterhead/blank.pdf?pages=${blankPages}`)
      .then((blob) => setBlank({ blob, error: '' }))
      .catch((e: Error) => setBlank({ blob: null, error: e.message }))
  }

  return (
    <div className="space-y-4">
      <div>
        <h2 className="text-lg font-semibold tracking-tight text-[color:var(--color-text)]">Put a PDF on the letterhead</h2>
        <p className="text-sm text-[color:var(--color-text-muted)]">
          For anything made outside Orion: choose its PDF and get it back with the company header and footer on its
          pages. The file is not kept on the server.
        </p>
      </div>

      {error && <Alert variant="error">{error}</Alert>}

      <div className="grid gap-4 xl:grid-cols-[22rem_minmax(0,1fr)]">
        <section className="space-y-4 self-start rounded-xl border border-[color:var(--color-border)] bg-surface p-4">
          <div
            onDragOver={(event) => {
              event.preventDefault()
              setOver(true)
            }}
            onDragLeave={() => setOver(false)}
            onDrop={drop}
            className={`rounded-xl border-2 border-dashed px-4 py-6 text-center transition-colors ${
              over ? 'border-[color:var(--color-accent)] bg-accent-dim/50' : 'border-[color:var(--color-border-strong)]'
            }`}
          >
            <FileUp className="mx-auto h-6 w-6 text-accent" aria-hidden="true" />
            <p className="mt-2 break-words text-sm font-medium text-[color:var(--color-text)]">
              {file ? file.name : 'Drop a PDF here'}
            </p>
            <p className="mt-0.5 text-xs text-[color:var(--color-text-muted)]">
              {file ? `${(file.size / 1024 / 1024).toFixed(1)} MB` : 'or choose one from this computer. Up to 25 MB.'}
            </p>
            <input
              ref={picker}
              type="file"
              accept="application/pdf,.pdf"
              className="sr-only"
              onChange={(event) => choose(event.target.files?.[0])}
            />
            <Button variant="secondary" size="sm" className="mt-3" onClick={() => picker.current?.click()}>
              {file ? 'Choose another' : 'Choose a PDF'}
            </Button>
          </div>

          <Field label="Each page of the PDF">
            <Segmented
              label="Each page of the PDF"
              value={fit}
              options={[
                { id: 'fit', label: 'Shrink to fit' },
                { id: 'keep', label: 'Keep full size' },
              ]}
              onChange={setFit}
            />
            <p className="text-xs text-[color:var(--color-text-muted)]">
              {fit === 'fit'
                ? 'The page is made smaller so all of it sits between the header and the footer. Nothing is covered.'
                : 'The page stays as it is and the header and footer are laid over its top and bottom. Use this when the document already leaves that room.'}
            </p>
          </Field>

          <Field label="Letterhead on">
            <Segmented
              label="Letterhead on"
              value={pages}
              options={[
                { id: 'all', label: 'Every page' },
                { id: 'first', label: 'First page only' },
              ]}
              onChange={setPages}
            />
          </Field>

          <div className="space-y-2">
            <p className="text-[13px] font-medium text-[color:var(--color-text)]">Add</p>
            <Checkbox label="The header" checked={header} onChange={setHeader} />
            <Checkbox label="The footer" checked={footer} onChange={setFooter} />
          </div>

          <div className="flex flex-wrap gap-2">
            <Button onClick={stamp} loading={busy} disabled={!file || (!header && !footer)}>
              Put it on the letterhead
            </Button>
            {(file || result) && (
              <Button variant="ghost" onClick={startAgain}>
                <RotateCcw className="h-4 w-4" /> Start again
              </Button>
            )}
          </div>

          <div className="space-y-2 border-t border-[color:var(--color-border)] pt-4">
            <p className="text-[13px] font-medium text-[color:var(--color-text)]">Blank letterhead paper</p>
            <p className="text-xs text-[color:var(--color-text-muted)]">
              The letterhead with nothing on it, as a PDF, to print a stack of or to write on by hand.
            </p>
            <div className="flex items-center gap-2">
              <div className="w-28">
                <Select
                  aria-label="How many pages"
                  value={blankPages}
                  onChange={(event) => setBlankPages(Number(event.target.value))}
                >
                  {[1, 2, 5, 10, 25, 50].map((count) => (
                    <option key={count} value={count}>
                      {count} {count === 1 ? 'page' : 'pages'}
                    </option>
                  ))}
                </Select>
              </div>
              <Button variant="secondary" size="sm" onClick={openBlank}>
                Open
              </Button>
            </div>
          </div>
        </section>

        <section className="min-w-0 rounded-xl border border-[color:var(--color-border)] bg-surface p-4">
          {result ? (
            <div className="space-y-3">
              <div className="flex flex-wrap items-center justify-between gap-2">
                <p className="text-sm text-[color:var(--color-text)]">
                  <span className="font-semibold">{result.name}</span>
                  <span className="text-[color:var(--color-text-muted)]">
                    {' '}
                    · {result.pages} {result.pages === 1 ? 'page' : 'pages'}. Print it with the printer button at the top
                    right of the page below.
                  </span>
                </p>
                <Button size="sm" onClick={() => saveBlob(result.blob, result.name)}>
                  <Download className="h-4 w-4" /> Download PDF
                </Button>
              </div>
              <PdfFrame blob={result.blob} title={result.name} className="h-[min(52rem,calc(100dvh-14rem))]" />
            </div>
          ) : (
            <div className="flex h-full min-h-64 items-center justify-center text-center">
              <p className="max-w-sm text-sm text-[color:var(--color-text-muted)]">
                {busy ? 'Putting it on the letterhead…' : 'The result appears here, ready to check, print or download.'}
              </p>
            </div>
          )}
        </section>
      </div>

      <PdfPreview
        open={blank !== null}
        title="Blank letterhead"
        blob={blank?.blob ?? null}
        error={blank?.error}
        filename="Letterhead.pdf"
        onClose={() => setBlank(null)}
      />
    </div>
  )
}
