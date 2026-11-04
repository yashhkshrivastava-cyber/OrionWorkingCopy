import { useEffect, useRef, useState, type DragEvent } from 'react'
import { ArrowDown, ArrowUp, FileText, FileUp, GripVertical, LockKeyhole, X } from 'lucide-react'
import { Button } from '../../components/ui/Button'
import { Input } from '../../components/ui/Field'
import { PasswordInput } from '../../components/ui/PasswordInput'
import type { PdfFileInfo } from '../../types'
import { formatBytes, plural } from './format'

/** A file the person has chosen for a tool, with what the server said about it. */
export interface Item {
  id: string
  file: File
  info: PdfFileInfo | null
  /** Being looked at by the server. */
  checking: boolean
  password: string
  /** Merge: the pages of this file to take (empty: all). */
  range: string
}

function Thumb({ file }: { file: File }) {
  const [url, setUrl] = useState<string | null>(null)
  const [broken, setBroken] = useState(false)
  useEffect(() => {
    const made = URL.createObjectURL(file)
    setUrl(made)
    setBroken(false)
    return () => URL.revokeObjectURL(made)
  }, [file])
  return broken || !url ? (
    <span className="flex h-14 w-14 shrink-0 items-center justify-center rounded-lg bg-muted text-accent" aria-hidden="true">
      <FileText className="h-6 w-6" />
    </span>
  ) : (
    <img src={url} alt="" className="h-14 w-14 shrink-0 rounded-lg border border-[color:var(--color-border)] object-cover" onError={() => setBroken(true)} />
  )
}

/**
 * The drop zone and the files in it. For a tool that takes several files they can be put in order (drag one, or use the arrows),
 * which is the order of the result; a locked PDF asks for its password here; a merge can take only some pages of each.
 */
export function FileList({
  items,
  kind,
  accept,
  maxFiles,
  maxMb,
  onAdd,
  onRemove,
  onMove,
  onChange,
  onOpen,
  disabled,
}: {
  items: Item[]
  kind: 'pdfs' | 'pdf' | 'images'
  accept: string
  maxFiles: number
  maxMb: number
  onAdd: (files: File[]) => void
  onRemove: (id: string) => void
  onMove: (from: number, to: number) => void
  onChange: (id: string, patch: Partial<Item>) => void
  /** Look at a locked file again with the password typed for it. */
  onOpen: (id: string) => void
  disabled?: boolean
}) {
  const picker = useRef<HTMLInputElement>(null)
  const dragging = useRef<number | null>(null)
  const [over, setOver] = useState(false)
  const many = kind !== 'pdf'
  const noun = kind === 'images' ? 'pictures' : 'PDFs'

  const drop = (event: DragEvent<HTMLElement>) => {
    event.preventDefault()
    setOver(false)
    if (!disabled) onAdd(Array.from(event.dataTransfer.files))
  }

  return (
    <div className="space-y-3">
      <div
        onDragOver={(event) => {
          event.preventDefault()
          if (dragging.current === null) setOver(true)
        }}
        onDragLeave={() => setOver(false)}
        onDrop={(event) => (dragging.current === null ? drop(event) : undefined)}
        className={`rounded-xl border-2 border-dashed px-4 py-7 text-center transition-colors ${
          over ? 'border-[color:var(--color-accent)] bg-accent-dim/50' : 'border-[color:var(--color-border-strong)]'
        }`}
      >
        <FileUp className="mx-auto h-7 w-7 text-accent" aria-hidden="true" />
        <p className="mt-2 text-sm font-medium text-[color:var(--color-text)]">
          {many ? `Drop ${noun} here` : 'Drop a PDF here'}
        </p>
        <p className="mt-0.5 text-xs text-[color:var(--color-text-muted)]">
          or choose {many ? 'them' : 'one'} from this computer. Up to {maxMb} MB each{many ? `, ${maxFiles} files at most` : ''}. Nothing is kept on the server.
        </p>
        <input
          ref={picker}
          type="file"
          multiple={many}
          accept={accept}
          className="sr-only"
          aria-label={many ? `Choose ${noun}` : 'Choose a PDF'}
          onChange={(event) => {
            onAdd(Array.from(event.target.files ?? []))
            event.target.value = ''
          }}
        />
        <Button variant="secondary" size="sm" className="mt-3" onClick={() => picker.current?.click()} disabled={disabled}>
          {items.length && !many ? 'Choose another' : many ? `Choose ${noun}` : 'Choose a PDF'}
        </Button>
      </div>

      {items.length > 0 && (
        <>
          {many && items.length > 1 && (
            <p className="text-xs text-[color:var(--color-text-muted)]">The result follows this order. Drag a file, or use the arrows, to change it.</p>
          )}
          <ul className="space-y-2">
            {items.map((item, index) => {
              const info = item.info
              return (
                <li
                  key={item.id}
                  draggable={many && !disabled}
                  onDragStart={() => (dragging.current = index)}
                  onDragEnd={() => (dragging.current = null)}
                  onDragOver={(event) => {
                    if (dragging.current !== null) event.preventDefault()
                  }}
                  onDrop={(event) => {
                    if (dragging.current === null) return
                    event.preventDefault()
                    event.stopPropagation()
                    onMove(dragging.current, index)
                    dragging.current = null
                  }}
                  className="rounded-xl border border-[color:var(--color-border)] bg-surface p-3"
                >
                  <div className="flex items-center gap-3">
                    {many && <GripVertical className="hidden h-4 w-4 shrink-0 cursor-grab text-[color:var(--color-text-faint)] sm:block" aria-hidden="true" />}
                    {kind === 'images' ? (
                      <Thumb file={item.file} />
                    ) : (
                      <span className="flex h-14 w-11 shrink-0 flex-col items-center justify-center rounded-md border border-[color:var(--color-border-strong)] bg-muted text-accent" aria-hidden="true">
                        {info?.locked ? <LockKeyhole className="h-5 w-5" /> : <FileText className="h-5 w-5" />}
                        <span className="text-[10px] font-semibold leading-none">PDF</span>
                      </span>
                    )}
                    <div className="min-w-0 flex-1">
                      <p className="truncate text-sm font-medium text-[color:var(--color-text)]" title={item.file.name}>
                        {many && <span className="mr-1.5 text-[color:var(--color-text-faint)]">{index + 1}.</span>}
                        {item.file.name}
                      </p>
                      <p className="text-xs text-[color:var(--color-text-muted)]">
                        {formatBytes(item.file.size)}
                        {item.checking && ' · looking at it…'}
                        {!item.checking && info?.pages ? ` · ${plural(info.pages, 'page', 'pages')}` : ''}
                        {!item.checking && info?.was_locked ? ' · was locked' : ''}
                      </p>
                      {!item.checking && info?.error && !info.locked && (
                        <p role="alert" className="mt-0.5 text-xs text-negative">
                          {info.error}
                        </p>
                      )}
                    </div>
                    {many && items.length > 1 && (
                      <div className="flex shrink-0 flex-col sm:flex-row">
                        <button
                          type="button"
                          aria-label={`Move ${item.file.name} up`}
                          disabled={index === 0 || disabled}
                          onClick={() => onMove(index, index - 1)}
                          className="rounded-md p-1.5 text-[color:var(--color-text-muted)] hover:bg-muted hover:text-[color:var(--color-text)] disabled:opacity-30"
                        >
                          <ArrowUp className="h-4 w-4" />
                        </button>
                        <button
                          type="button"
                          aria-label={`Move ${item.file.name} down`}
                          disabled={index === items.length - 1 || disabled}
                          onClick={() => onMove(index, index + 1)}
                          className="rounded-md p-1.5 text-[color:var(--color-text-muted)] hover:bg-muted hover:text-[color:var(--color-text)] disabled:opacity-30"
                        >
                          <ArrowDown className="h-4 w-4" />
                        </button>
                      </div>
                    )}
                    <button
                      type="button"
                      aria-label={`Remove ${item.file.name}`}
                      disabled={disabled}
                      onClick={() => onRemove(item.id)}
                      className="shrink-0 rounded-md p-1.5 text-[color:var(--color-text-muted)] hover:bg-muted hover:text-negative"
                    >
                      <X className="h-4 w-4" />
                    </button>
                  </div>

                  {!item.checking && info?.locked && (
                    <form
                      className="mt-3 flex flex-wrap items-end gap-2 border-t border-[color:var(--color-border)] pt-3"
                      onSubmit={(event) => {
                        event.preventDefault()
                        onOpen(item.id)
                      }}
                    >
                      <div className="min-w-48 flex-1 space-y-1.5">
                        <label htmlFor={`pw-${item.id}`} className="t-label block text-[color:var(--color-text)]">
                          This PDF is locked. Its password
                        </label>
                        <PasswordInput
                          id={`pw-${item.id}`}
                          value={item.password}
                          autoComplete="off"
                          maxLength={128}
                          onChange={(event) => onChange(item.id, { password: event.target.value })}
                          aria-invalid={Boolean(item.password) || undefined}
                        />
                      </div>
                      <Button variant="secondary" disabled={!item.password || disabled} onClick={() => onOpen(item.id)}>
                        Open it
                      </Button>
                      {info.error.includes('does not open') && (
                        <p role="alert" className="basis-full text-xs text-negative">
                          That password does not open it.
                        </p>
                      )}
                    </form>
                  )}

                  {kind === 'pdfs' && !item.checking && info && !info.error && (
                    <div className="mt-3 border-t border-[color:var(--color-border)] pt-3">
                      <label htmlFor={`range-${item.id}`} className="t-label block text-[color:var(--color-text)]">
                        Pages to take from this file
                      </label>
                      <Input
                        id={`range-${item.id}`}
                        className="mt-1.5"
                        value={item.range}
                        placeholder={info.pages ? `All ${info.pages} pages` : 'All pages'}
                        spellCheck={false}
                        autoComplete="off"
                        maxLength={300}
                        onChange={(event) => onChange(item.id, { range: event.target.value })}
                      />
                    </div>
                  )}
                </li>
              )
            })}
          </ul>
        </>
      )}
    </div>
  )
}
