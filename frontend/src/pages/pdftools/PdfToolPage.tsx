import { useCallback, useEffect, useRef, useState } from 'react'
import { Link, Navigate, useNavigate, useOutletContext, useParams } from 'react-router-dom'
import { ChevronLeft } from 'lucide-react'
import { api } from '../../api/client'
import { Alert } from '../../components/ui/Alert'
import { Button } from '../../components/ui/Button'
import type { PdfToolResult } from '../../types'
import { FileList, type Item } from './FileList'
import { isImageFile, isPdfFile, plural } from './format'
import { OptionFields } from './OptionFields'
import { ResultCard } from './ResultCard'
import type { PdfToolsContext } from './PdfToolsPage'
import { TOOL_BY_ID, type ToolDef, type Values } from './tools'

let counter = 0
const newId = () => `file-${(counter += 1)}`

const IMAGE_ACCEPT = 'image/*,.jpg,.jpeg,.png,.webp,.gif,.bmp,.tif,.tiff,.heic,.heif'

function Workspace({ tool }: { tool: ToolDef }) {
  const { carry, setCarry, limits } = useOutletContext<PdfToolsContext>()
  const navigate = useNavigate()
  const [items, setItems] = useState<Item[]>([])
  const [values, setValues] = useState<Values>(tool.defaults)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [result, setResult] = useState<PdfToolResult | null>(null)
  const prefilled = useRef(false)
  const itemsRef = useRef(items)
  itemsRef.current = items

  const maxFiles = limits?.max_files ?? 40
  const maxMb = limits?.max_file_mb ?? 40
  const maxTotalMb = limits?.max_total_mb ?? 120
  const single = tool.accept === 'pdf'
  const needsPdf = tool.accept !== 'images'

  const patch = useCallback((id: string, change: Partial<Item>) => setItems((list) => list.map((item) => (item.id === id ? { ...item, ...change } : item))), [])

  /** Asks the server about some files (pages, locked or not) and puts the answers on them. */
  const look = useCallback(
    async (targets: Item[]) => {
      try {
        const rows = await api.pdfInspect(
          targets.map((item) => item.file),
          targets.map((item) => item.password),
        )
        setItems((list) =>
          list.map((item) => {
            const at = targets.findIndex((target) => target.id === item.id)
            return at < 0 ? item : { ...item, info: rows[at], checking: false }
          }),
        )
        const first = rows[0]
        if (tool.prefillDetails && first?.details && !prefilled.current && targets.length === 1) {
          prefilled.current = true
          setValues((current) => ({ ...current, ...first.details }))
        }
      } catch (e) {
        setError((e as Error).message)
        setItems((list) => list.map((item) => (targets.some((target) => target.id === item.id) ? { ...item, checking: false } : item)))
      }
    },
    [tool.prefillDetails],
  )

  const add = useCallback(
    (files: File[]) => {
      setError('')
      setResult(null)
      const accepted: File[] = []
      const refused: string[] = []
      let total = single ? 0 : itemsRef.current.reduce((sum, item) => sum + item.file.size, 0)
      for (const file of files) {
        if (needsPdf ? !isPdfFile(file) : !isImageFile(file)) refused.push(`${file.name} is not ${needsPdf ? 'a PDF' : 'a picture'}.`)
        else if (file.size > maxMb * 1024 * 1024) refused.push(`${file.name} is larger than ${maxMb} MB.`)
        else if (total + file.size > maxTotalMb * 1024 * 1024) refused.push(`${file.name} would take the files past ${maxTotalMb} MB together.`)
        else {
          accepted.push(file)
          total += file.size
        }
      }
      const room = single ? 1 : maxFiles - itemsRef.current.length
      if (accepted.length > room) refused.push(single ? 'This tool works on one PDF at a time.' : `At most ${maxFiles} files at once.`)
      const taken = accepted.slice(0, Math.max(room, 0)).slice(0, single ? 1 : undefined)
      if (refused.length) setError(refused.join(' '))
      if (!taken.length) return
      const added: Item[] = taken.map((file) => ({ id: newId(), file, info: null, checking: needsPdf, password: '', range: '' }))
      prefilled.current = false
      setItems((list) => (single ? added : [...list, ...added]))
      if (needsPdf) void look(added)
    },
    [look, maxFiles, maxMb, maxTotalMb, needsPdf, single],
  )

  // A file carried over from the tool before this one is the first file here. Only the tool it was sent to takes it: the screen
  // being left can be drawn once more after the file is set down, and must not keep it.
  useEffect(() => {
    if (carry && carry.tool === tool.id && carry.files.length) {
      const files = carry.files
      setCarry(null)
      add(files)
    }
  }, [carry, setCarry, add, tool.id])

  const remove = (id: string) => {
    setItems((list) => list.filter((item) => item.id !== id))
    setResult(null)
  }
  const move = (from: number, to: number) =>
    setItems((list) => {
      if (to < 0 || to >= list.length || from === to) return list
      const next = [...list]
      next.splice(to, 0, next.splice(from, 1)[0])
      return next
    })
  const open = (id: string) => {
    const item = itemsRef.current.find((entry) => entry.id === id)
    if (!item) return
    patch(id, { checking: true })
    void look([{ ...item }])
  }

  const setValue = (key: string, next: string | boolean) => {
    setValues((current) => ({ ...current, [key]: next }))
    setResult(null)
  }

  const waiting = items.some((item) => item.checking)
  const blocked = items.find((item) => item.info?.error)
  const enough = tool.accept === 'pdfs' ? items.length >= 2 : items.length >= 1
  const why =
    !items.length
      ? ''
      : waiting
        ? 'Looking at the files…'
        : blocked
          ? blocked.info?.locked
            ? `${blocked.file.name} is locked: type its password and open it.`
            : `${blocked.file.name} cannot be used.`
          : !enough
            ? 'Choose at least two PDFs to merge.'
            : (tool.missing?.(values) ?? '')
  const ready = items.length > 0 && !why

  const go = async () => {
    setBusy(true)
    setError('')
    setResult(null)
    try {
      const options: Record<string, unknown> = { ...values }
      if (tool.accept === 'pdfs') {
        options.ranges = items.map((item) => item.range)
        options.passwords = items.map((item) => item.password)
      } else if (needsPdf) {
        options.password = items[0]?.password ?? ''
      }
      setResult(await api.pdfTool(tool.id, items.map((item) => item.file), options))
    } catch (e) {
      setError((e as Error).message)
    } finally {
      setBusy(false)
    }
  }

  const again = () => {
    setItems([])
    setResult(null)
    setError('')
    setValues(tool.defaults)
  }

  const carryOn = (nextTool: string) => {
    if (!result) return
    const name = result.name.endsWith('.pdf') ? result.name : `${result.name}.pdf`
    setCarry({ tool: nextTool, files: [new File([result.blob], name, { type: 'application/pdf' })] })
    navigate(`/pdf-tools/${nextTool}`)
  }

  const pageCount = single ? (items[0]?.info?.pages ?? null) : null
  const Icon = tool.icon

  return (
    <div className="mx-auto w-full max-w-4xl space-y-4">
      <div>
        <Link to="/pdf-tools" className="inline-flex items-center gap-1 text-sm text-[color:var(--color-text-muted)] hover:text-[color:var(--color-text)]">
          <ChevronLeft className="h-4 w-4" aria-hidden="true" /> All PDF tools
        </Link>
        <div className="mt-2 flex items-start gap-3">
          <span className="inline-flex rounded-xl bg-accent-dim p-2.5 text-accent" aria-hidden="true">
            <Icon className="h-6 w-6" />
          </span>
          <div>
            <h1 className="t-h2 text-[color:var(--color-text)]">{tool.title}</h1>
            <p className="text-sm text-[color:var(--color-text-muted)]">{tool.blurb}</p>
          </div>
        </div>
      </div>

      {error && <Alert variant="error" onDismiss={() => setError('')}>{error}</Alert>}

      <section className="space-y-3 rounded-xl border border-[color:var(--color-border)] bg-surface p-4">
        <h2 className="t-h3 text-[color:var(--color-text)]">
          {tool.accept === 'images' ? '1. Choose the pictures' : tool.accept === 'pdfs' ? '1. Choose the PDFs' : '1. Choose the PDF'}
        </h2>
        <FileList
          items={items}
          kind={tool.accept}
          accept={needsPdf ? 'application/pdf,.pdf' : IMAGE_ACCEPT}
          maxFiles={maxFiles}
          maxMb={maxMb}
          onAdd={add}
          onRemove={remove}
          onMove={move}
          onChange={patch}
          onOpen={open}
          disabled={busy}
        />
      </section>

      {tool.fields.length > 0 && (
        <section className="space-y-3 rounded-xl border border-[color:var(--color-border)] bg-surface p-4">
          <h2 className="t-h3 text-[color:var(--color-text)]">2. Choose how</h2>
          <OptionFields fields={tool.fields} values={values} onChange={setValue} pageCount={pageCount} />
        </section>
      )}

      <div className="flex flex-wrap items-center gap-3">
        <Button size="lg" onClick={go} loading={busy} disabled={!ready}>
          {tool.action(items.length)}
        </Button>
        {why && <p className="text-sm text-[color:var(--color-text-muted)]">{why}</p>}
        {!why && items.length > 0 && tool.accept !== 'pdf' && (
          <p className="text-sm text-[color:var(--color-text-muted)]">{plural(items.length, 'file', 'files')} chosen.</p>
        )}
      </div>

      {result && <ResultCard result={result} toolId={tool.id} onAgain={again} onContinue={carryOn} />}
    </div>
  )
}

/** One tool's screen: choose the files, say how, and get the result. The tool is the last part of the address. */
export function PdfToolPage() {
  const { tool: id } = useParams()
  const tool = id ? TOOL_BY_ID.get(id) : undefined
  if (!tool) return <Navigate to="/pdf-tools" replace />
  return <Workspace key={tool.id} tool={tool} />
}
