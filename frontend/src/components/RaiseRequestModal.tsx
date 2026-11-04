import { FormEvent, useMemo, useRef, useState } from 'react'
import { Paperclip, X } from 'lucide-react'
import { api } from '../api/client'
import { Modal } from './ui/Modal'
import { Button } from './ui/Button'
import { Alert } from './ui/Alert'
import { Field, Input, Textarea } from './ui/Field'

const MAX_FILES = 5
const ACCEPT = 'image/*,.pdf,.doc,.docx,.xls,.xlsx,.csv,.txt,.zip,.ppt,.pptx,.mp4,.mov,.webm'

function fileLabel(file: File) {
  const mb = file.size / (1024 * 1024)
  const size = mb >= 0.1 ? `${mb.toFixed(1)} MB` : `${Math.max(1, Math.round(file.size / 1024))} KB`
  return `${file.name} · ${size}`
}

export function RaiseRequestModal({
  open,
  onClose,
}: {
  open: boolean
  onClose: () => void
}) {
  const [subject, setSubject] = useState('')
  const [details, setDetails] = useState('')
  const [files, setFiles] = useState<File[]>([])
  const [error, setError] = useState('')
  const [done, setDone] = useState(false)
  const [submitting, setSubmitting] = useState(false)
  const inputRef = useRef<HTMLInputElement>(null)
  const previews = useMemo(
    () =>
      files.map((file) => ({
        file,
        url: file.type.startsWith('image/') ? URL.createObjectURL(file) : null,
      })),
    [files],
  )

  const reset = () => {
    setSubject('')
    setDetails('')
    setFiles([])
    setError('')
    setDone(false)
    setSubmitting(false)
  }

  const handleClose = () => {
    reset()
    onClose()
  }

  const addFiles = (list: FileList | null) => {
    if (!list?.length) return
    setError('')
    setFiles((current) => {
      const next = [...current]
      for (const file of Array.from(list)) {
        if (next.length >= MAX_FILES) break
        if (next.some((item) => item.name === file.name && item.size === file.size)) continue
        next.push(file)
      }
      return next
    })
  }

  const handleSubmit = async (event?: FormEvent) => {
    event?.preventDefault()
    setError('')
    if (!subject.trim() || !details.trim()) {
      setError('Enter a subject and describe the issue.')
      return
    }
    setSubmitting(true)
    try {
      await api.raiseRequest({
        subject: subject.trim(),
        details: details.trim(),
        files,
      })
      setDone(true)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not send the request')
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <Modal
      open={open}
      title="Raise a request"
      onClose={handleClose}
      footer={
        done ? (
          <Button onClick={handleClose}>Close</Button>
        ) : (
          <>
            <Button variant="secondary" onClick={handleClose} disabled={submitting}>
              Cancel
            </Button>
            <Button onClick={handleSubmit} loading={submitting} disabled={submitting}>
              Send request
            </Button>
          </>
        )
      }
    >
      {done ? (
        <Alert variant="success">
          We received your request. The helpdesk will follow up from prakashsecuritiesorionhelpdesk@gmail.com.
        </Alert>
      ) : (
        <form className="space-y-4" onSubmit={handleSubmit}>
          <p className="text-sm text-[color:var(--color-text-muted)]">
            Tell us what went wrong. You can attach screenshots or files. We get an email alert on the helpdesk inbox.
          </p>
          {error && <Alert variant="error">{error}</Alert>}
          <Field label="Subject" required>
            <Input
              value={subject}
              onChange={(event) => setSubject(event.target.value)}
              maxLength={160}
              placeholder="Short summary of the issue"
            />
          </Field>
          <Field label="What happened" required>
            <Textarea
              value={details}
              onChange={(event) => setDetails(event.target.value)}
              rows={5}
              maxLength={8000}
              placeholder="What you were doing, what you expected, and what you saw instead"
            />
          </Field>
          <Field label="Attachments">
            <input
              ref={inputRef}
              type="file"
              multiple
              accept={ACCEPT}
              className="hidden"
              onChange={(event) => {
                addFiles(event.target.files)
                event.target.value = ''
              }}
            />
            <button
              type="button"
              onClick={() => inputRef.current?.click()}
              disabled={files.length >= MAX_FILES}
              className="flex w-full items-center justify-center gap-2 rounded-lg border border-dashed border-[color:var(--color-border-strong)] px-3 py-3 text-sm text-[color:var(--color-text-muted)] hover:border-accent hover:text-[color:var(--color-text)] disabled:opacity-50"
            >
              <Paperclip className="h-4 w-4" />
              {files.length >= MAX_FILES ? 'Maximum of 5 files' : 'Attach images or files'}
            </button>
            {previews.length > 0 && (
              <ul className="mt-2 space-y-2">
                {previews.map(({ file, url }) => (
                  <li
                    key={`${file.name}-${file.size}`}
                    className="flex items-center gap-2 rounded-lg border border-[color:var(--color-border)] bg-muted/40 px-2 py-1.5"
                  >
                    {url ? (
                      <img src={url} alt="" className="h-10 w-10 rounded object-cover" />
                    ) : (
                      <span className="flex h-10 w-10 items-center justify-center rounded bg-muted text-[color:var(--color-text-faint)]">
                        <Paperclip className="h-4 w-4" />
                      </span>
                    )}
                    <span className="min-w-0 flex-1 truncate text-sm">{fileLabel(file)}</span>
                    <button
                      type="button"
                      aria-label={`Remove ${file.name}`}
                      onClick={() => setFiles((current) => current.filter((item) => item !== file))}
                      className="rounded p-1 text-[color:var(--color-text-faint)] hover:bg-muted hover:text-[color:var(--color-text)]"
                    >
                      <X className="h-4 w-4" />
                    </button>
                  </li>
                ))}
              </ul>
            )}
          </Field>
        </form>
      )}
    </Modal>
  )
}
