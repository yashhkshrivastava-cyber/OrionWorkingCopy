import { useCallback, useEffect, useRef, useState } from 'react'
import { Download, Eye, FileText, Trash2, Upload } from 'lucide-react'
import { api } from '../../api/client'
import { formatDateTime } from '../../formatTime'
import type { EmployeeDocument, EmployeeDocumentList } from '../../types'
import { Alert } from '../ui/Alert'
import { Button } from '../ui/Button'
import { Field, Input } from '../ui/Field'
import { Modal } from '../ui/Modal'
import { PdfFrame, saveBlob } from '../ui/PdfPreview'

const size = (bytes: number) => (bytes >= 1024 * 1024 ? `${(bytes / (1024 * 1024)).toFixed(1)} MB` : `${Math.max(1, Math.round(bytes / 1024))} KB`)

/** What a browser can draw by itself; anything else is saved rather than shown. */
const canShow = (type: string) => type === 'application/pdf' || type.startsWith('image/')

/** A file chosen on the Add screen, held until the employee has been saved and has a code to attach it to. */
export type StagedDocument = { key: number; file: File; docType: string; title: string }

let nextKey = 1

/** What differs between the records that keep files: which calls to make, and how to say it. */
const KINDS = {
  employee: {
    noun: 'employee',
    intro: 'Aadhaar and PAN scans, and anything else worth keeping. Only people who can change operational data can see these.',
    otherExample: 'For example Experience letter',
    options: api.employeeDocumentOptions,
    list: api.employeeDocuments,
    upload: api.uploadEmployeeDocument,
    file: api.employeeDocumentFile,
    remove: api.deleteEmployeeDocument,
  },
  emd: {
    noun: 'EMD',
    intro: 'The payment receipt, a copy of the demand draft or bank guarantee, the FDR receipt, the tender notice, the refund request and the proof of refund.',
    otherExample: "For example Bank's acknowledgement",
    options: api.emdDocumentOptions,
    list: api.emdDocuments,
    upload: api.uploadEmdDocument,
    file: api.emdDocumentFile,
    remove: api.deleteEmdDocument,
  },
} as const

/** Which kind of record keeps files, for the record types that do. */
export const DOCUMENT_KINDS: Record<string, keyof typeof KINDS> = { Employee: 'employee', EMD: 'emd' }

/**
 * The files kept against one record (an employee: Aadhaar and PAN scans and the like; an EMD: its receipt, instrument and refund papers). Only people
 * who can change operational data add or delete (the server decides), and the files never leave the app except as a download.
 *
 * With a `code` it is the live list. Without one (the Add screen) files are only queued in `staged`, and the
 * page uploads them as soon as the employee is saved.
 */
export function EmployeeDocuments({
  code,
  kind = 'employee',
  staged = [],
  onStagedChange,
}: {
  code: string | null
  kind?: keyof typeof KINDS
  staged?: StagedDocument[]
  onStagedChange?: (next: StagedDocument[]) => void
}) {
  const k = KINDS[kind]
  const [data, setData] = useState<EmployeeDocumentList | null>(null)
  const [error, setError] = useState('')
  const [docType, setDocType] = useState('')
  const [title, setTitle] = useState('')
  const [file, setFile] = useState<File | null>(null)
  const [uploading, setUploading] = useState(false)
  const [viewing, setViewing] = useState<{ doc: EmployeeDocument; blob: Blob } | null>(null)
  const [opening, setOpening] = useState<number | null>(null)
  const picker = useRef<HTMLInputElement>(null)

  const load = useCallback(() => {
    const request = code
      ? k.list(code)
      : k.options().then((options) => ({ ...options, documents: [] as EmployeeDocument[] }))
    request
      .then((list) => {
        setData(list)
        setError('')
      })
      .catch((e: Error) => setError(e.message))
  }, [code, k])

  useEffect(() => {
    setData(null)
    setFile(null)
    setTitle('')
    setDocType('')
    load()
  }, [load])

  const clearChoice = () => {
    setFile(null)
    setTitle('')
    setDocType('')
    if (picker.current) picker.current.value = ''
  }

  /** On the Add screen: check what the server would check about the file's name and size, then queue it. */
  const stage = () => {
    if (!file || !docType || !data) return
    const extension = file.name.includes('.') ? `.${file.name.split('.').pop()!.toLowerCase()}` : ''
    if (!data.accepted.split(', ').includes(extension)) {
      setError(`A file of that type cannot be kept. Upload one of: ${data.accepted}.`)
      return
    }
    if (file.size > data.max_mb * 1024 * 1024) {
      setError(`That file is larger than ${data.max_mb} MB.`)
      return
    }
    setError('')
    onStagedChange?.([...staged, { key: nextKey++, file, docType, title: title.trim() }])
    clearChoice()
  }

  const upload = async () => {
    if (!code || !file || !docType) return
    setUploading(true)
    setError('')
    try {
      await k.upload(code, file, docType, title)
      clearChoice()
      load()
    } catch (e) {
      setError((e as Error).message)
    } finally {
      setUploading(false)
    }
  }

  const open = async (doc: EmployeeDocument) => {
    if (!code) return
    setOpening(doc.id)
    setError('')
    try {
      const blob = await k.file(code, doc.id)
      if (canShow(doc.content_type)) setViewing({ doc, blob })
      else saveBlob(blob, doc.file_name)
    } catch (e) {
      setError((e as Error).message)
    } finally {
      setOpening(null)
    }
  }

  const remove = async (doc: EmployeeDocument) => {
    if (!code) return
    if (!window.confirm(`Delete ${doc.title || doc.doc_type} (${doc.file_name})? This cannot be undone.`)) return
    setError('')
    try {
      await k.remove(code, doc.id)
      load()
    } catch (e) {
      setError((e as Error).message)
    }
  }

  const documents = data?.documents ?? []

  return (
    <section className="mt-8 max-w-3xl rounded-2xl border border-[color:var(--color-border)] bg-surface p-4 sm:p-5">
      <h3 className="t-h3 flex items-center gap-2 text-[color:var(--color-text)]">
        <FileText className="h-4 w-4 text-accent" /> Documents
        {data && (
          <span className="text-xs font-normal text-[color:var(--color-text-muted)]">
            {code ? `${documents.length} kept` : `${staged.length} to upload`}
          </span>
        )}
      </h3>
      <p className="mt-1 text-xs text-[color:var(--color-text-muted)]">
        {k.intro}
      </p>

      {error && (
        <div className="mt-3">
          <Alert variant="error" onDismiss={() => setError('')}>
            {error}
          </Alert>
        </div>
      )}

      {data && code && documents.length === 0 && (
        <p className="mt-4 rounded-lg bg-muted px-3 py-2 text-sm text-[color:var(--color-text-muted)]">No documents kept yet.</p>
      )}
      {!code && (
        <p className="mt-4 rounded-lg bg-muted px-3 py-2 text-sm text-[color:var(--color-text-muted)]">
          Choose the files now. They are uploaded to the {k.noun} as soon as you save.
        </p>
      )}
      {staged.length > 0 && (
        <ul className="mt-3 divide-y divide-[color:var(--color-border)] rounded-lg border border-[color:var(--color-border)]">
          {staged.map((item) => (
            <li key={item.key} className="flex items-center gap-3 px-3 py-2.5">
              <div className="min-w-0 flex-1">
                <p className="truncate text-sm font-medium text-[color:var(--color-text)]">
                  {item.docType}
                  {item.title ? <span className="font-normal text-[color:var(--color-text-muted)]"> · {item.title}</span> : null}
                </p>
                <p className="truncate text-xs text-[color:var(--color-text-muted)]">
                  {item.file.name} · {size(item.file.size)}
                </p>
              </div>
              <button
                type="button"
                aria-label={`Remove ${item.file.name}`}
                onClick={() => onStagedChange?.(staged.filter((other) => other.key !== item.key))}
                className="rounded p-1.5 text-[color:var(--color-text-faint)] hover:bg-muted hover:text-negative"
              >
                <Trash2 className="h-4 w-4" />
              </button>
            </li>
          ))}
        </ul>
      )}
      {documents.length > 0 && (
        <ul className="mt-4 divide-y divide-[color:var(--color-border)] rounded-lg border border-[color:var(--color-border)]">
          {documents.map((doc) => (
            <li key={doc.id} className="flex flex-wrap items-center gap-x-3 gap-y-1 px-3 py-2.5">
              <div className="min-w-0 flex-1">
                <p className="truncate text-sm font-medium text-[color:var(--color-text)]">
                  {doc.doc_type}
                  {doc.title ? <span className="font-normal text-[color:var(--color-text-muted)]"> · {doc.title}</span> : null}
                </p>
                <p className="truncate text-xs text-[color:var(--color-text-muted)]">
                  {doc.file_name} · {size(doc.size_bytes)} · {formatDateTime(doc.uploaded_timestamp)}
                  {doc.uploaded_by_name ? ` · ${doc.uploaded_by_name}` : ''}
                </p>
              </div>
              <div className="flex items-center gap-1">
                <Button variant="secondary" size="sm" loading={opening === doc.id} onClick={() => open(doc)}>
                  {canShow(doc.content_type) ? <Eye className="h-4 w-4" /> : <Download className="h-4 w-4" />}
                  {canShow(doc.content_type) ? 'View' : 'Download'}
                </Button>
                <button
                  type="button"
                  aria-label={`Delete ${doc.file_name}`}
                  onClick={() => remove(doc)}
                  className="rounded p-1.5 text-[color:var(--color-text-faint)] hover:bg-muted hover:text-negative"
                >
                  <Trash2 className="h-4 w-4" />
                </button>
              </div>
            </li>
          ))}
        </ul>
      )}

      {data && (
        <div className="mt-5 grid gap-3 sm:grid-cols-2">
          <Field label="Kind of document" required>
            <select
              value={docType}
              onChange={(e) => setDocType(e.target.value)}
              className="h-10 w-full rounded-lg border border-[color:var(--color-border)] bg-surface px-2 text-sm text-[color:var(--color-text)]"
            >
              <option value="">— Choose —</option>
              {data.types.map((type) => (
                <option key={type} value={type}>
                  {type}
                </option>
              ))}
            </select>
          </Field>
          <Field label={docType === 'Other' ? 'What is it?' : 'Note (optional)'} required={docType === 'Other'}>
            <Input
              value={title}
              maxLength={100}
              placeholder={docType === 'Other' ? k.otherExample : 'For example Back side'}
              onChange={(e) => setTitle(e.target.value)}
            />
          </Field>
          <div className="sm:col-span-2">
            <Field label="File">
              <input
                ref={picker}
                type="file"
                accept={data.accepted}
                onChange={(e) => setFile(e.target.files?.[0] ?? null)}
                className="block w-full text-sm text-[color:var(--color-text-muted)] file:mr-3 file:rounded-lg file:border-0 file:bg-muted file:px-3 file:py-2 file:text-sm file:font-medium file:text-[color:var(--color-text)]"
              />
            </Field>
            <p className="mt-1 text-xs text-[color:var(--color-text-muted)]">
              {data.accepted}, up to {data.max_mb} MB each.
            </p>
          </div>
          <div className="sm:col-span-2">
            <Button
              onClick={code ? upload : stage}
              loading={uploading}
              disabled={!file || !docType || (docType === 'Other' && !title.trim())}
            >
              <Upload className="h-4 w-4" /> {code ? 'Upload document' : `Add to this ${k.noun}`}
            </Button>
          </div>
        </div>
      )}

      <Modal
        open={viewing !== null}
        title={viewing ? `${viewing.doc.doc_type}${viewing.doc.title ? ` · ${viewing.doc.title}` : ''}` : ''}
        size="2xl"
        onClose={() => setViewing(null)}
        footer={
          <>
            <Button variant="secondary" onClick={() => setViewing(null)}>
              Close
            </Button>
            <Button onClick={() => viewing && saveBlob(viewing.blob, viewing.doc.file_name)}>
              <Download className="h-4 w-4" /> Download
            </Button>
          </>
        }
      >
        {viewing &&
          (viewing.doc.content_type === 'application/pdf' ? (
            <PdfFrame blob={viewing.blob} title={viewing.doc.file_name} className="h-[min(40rem,calc(100dvh-16rem))]" />
          ) : (
            <BlobImage blob={viewing.blob} alt={viewing.doc.file_name} />
          ))}
      </Modal>
    </section>
  )
}

function BlobImage({ blob, alt }: { blob: Blob; alt: string }) {
  const [url, setUrl] = useState('')
  useEffect(() => {
    const next = URL.createObjectURL(blob)
    setUrl(next)
    return () => URL.revokeObjectURL(next)
  }, [blob])
  return url ? <img src={url} alt={alt} className="mx-auto max-h-[min(40rem,calc(100dvh-16rem))] max-w-full rounded-lg object-contain" /> : null
}
