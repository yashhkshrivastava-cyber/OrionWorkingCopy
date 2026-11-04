import { useEffect, useState } from 'react'
import { Download } from 'lucide-react'
import { Alert } from './Alert'
import { Button } from './Button'
import { Modal } from './Modal'

/** Saves a file the app already holds, through a link the browser treats as a download. */
export function saveBlob(blob: Blob, filename: string) {
  const url = URL.createObjectURL(blob)
  const link = document.createElement('a')
  link.href = url
  link.download = filename
  document.body.appendChild(link)
  link.click()
  link.remove()
  setTimeout(() => URL.revokeObjectURL(url), 1000)
}

/** A PDF drawn by the browser's own viewer, whose toolbar has the print and save buttons. */
export function PdfFrame({ blob, title, className = '' }: { blob: Blob; title: string; className?: string }) {
  // The address is made and given back by the same effect, so a second mount (React's development check) gets a fresh one
  // instead of a revoked one.
  const [url, setUrl] = useState<string | null>(null)
  useEffect(() => {
    const made = URL.createObjectURL(blob)
    setUrl(made)
    return () => URL.revokeObjectURL(made)
  }, [blob])
  if (!url) return <div className={`shimmer rounded-lg bg-muted ${className}`} aria-busy="true" />
  return <iframe src={url} title={title} className={`w-full rounded-lg border border-[color:var(--color-border)] bg-white ${className}`} />
}

/**
 * Shows a PDF the server made, to check and then print or save. `blob` is null while it is being made.
 */
export function PdfPreview({
  open,
  title,
  blob,
  filename,
  error,
  onClose,
}: {
  open: boolean
  title: string
  blob: Blob | null
  filename: string
  error?: string
  onClose: () => void
}) {
  return (
    <Modal
      open={open}
      title={title}
      size="2xl"
      onClose={onClose}
      footer={
        <>
          <span className="mr-auto self-center text-xs text-[color:var(--color-text-muted)]">
            To print, use the printer button at the top right of the page shown above.
          </span>
          <Button variant="secondary" onClick={onClose}>
            Close
          </Button>
          <Button onClick={() => blob && saveBlob(blob, filename)} disabled={!blob}>
            <Download className="h-4 w-4" /> Download PDF
          </Button>
        </>
      }
    >
      {error ? (
        <Alert variant="error">{error}</Alert>
      ) : blob ? (
        <PdfFrame blob={blob} title={title} className="h-[min(40rem,calc(100dvh-16rem))]" />
      ) : (
        <div className="shimmer h-64 rounded-lg bg-muted" aria-busy="true" />
      )}
    </Modal>
  )
}
