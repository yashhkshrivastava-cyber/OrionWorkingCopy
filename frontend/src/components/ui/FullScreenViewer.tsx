import { useEffect, useRef, useState } from 'react'
import { createPortal } from 'react-dom'
import { Download, ExternalLink, X, ZoomIn, ZoomOut } from 'lucide-react'
import { Button } from './Button'
import { saveBlob } from './PdfPreview'

/**
 * A file shown over the whole window: a PDF in the browser's own viewer, or a picture that can be fitted to the screen or seen at full size.
 * It asks the browser for real full screen too (the address bar and tabs go away); if that is refused it still covers the page.
 * Escape closes it, and it closes the viewer only, not the panel under it.
 */
export function FullScreenViewer({ blob, type, title, filename, onClose }: { blob: Blob; type: string; title: string; filename: string; onClose: () => void }) {
  const [url, setUrl] = useState('')
  // made inside the effect so a second run of it (React's development check) makes a fresh one instead of using a revoked one
  useEffect(() => {
    const made = URL.createObjectURL(blob)
    setUrl(made)
    return () => URL.revokeObjectURL(made)
  }, [blob])
  const root = useRef<HTMLDivElement>(null)
  const [actualSize, setActualSize] = useState(false)
  const close = useRef(onClose)
  close.current = onClose
  const isPdf = type === 'application/pdf'

  useEffect(() => {
    const node = root.current
    const previousOverflow = document.body.style.overflow
    document.body.style.overflow = 'hidden'
    node?.requestFullscreen?.().catch(() => {
      // refused (a setting, or no gesture): the viewer still fills the page
    })
    const onKey = (event: KeyboardEvent) => {
      if (event.key !== 'Escape') return
      event.stopPropagation()
      close.current()
    }
    const onFullscreen = () => {
      if (!document.fullscreenElement) close.current()
    }
    window.addEventListener('keydown', onKey, true)
    document.addEventListener('fullscreenchange', onFullscreen)
    return () => {
      window.removeEventListener('keydown', onKey, true)
      document.removeEventListener('fullscreenchange', onFullscreen)
      document.body.style.overflow = previousOverflow
      if (document.fullscreenElement) void document.exitFullscreen().catch(() => undefined)
    }
  }, [])

  return createPortal(
    <div ref={root} role="dialog" aria-modal="true" aria-label={title} className="fixed inset-0 z-[120] flex flex-col bg-[color:var(--color-bg)]">
      <header className="flex flex-wrap items-center gap-2 border-b border-[color:var(--color-border)] bg-surface px-4 py-2">
        <p className="min-w-0 flex-1 truncate text-sm font-semibold text-[color:var(--color-text)]">{title}</p>
        {!isPdf && (
          <Button variant="secondary" size="sm" onClick={() => setActualSize((value) => !value)}>
            {actualSize ? <ZoomOut className="h-4 w-4" /> : <ZoomIn className="h-4 w-4" />} {actualSize ? 'Fit to screen' : 'Full size'}
          </Button>
        )}
        <Button variant="secondary" size="sm" onClick={() => window.open(url, '_blank', 'noopener')}>
          <ExternalLink className="h-4 w-4" /> New tab
        </Button>
        <Button variant="secondary" size="sm" onClick={() => saveBlob(blob, filename)}>
          <Download className="h-4 w-4" /> Download
        </Button>
        <Button size="sm" onClick={onClose} data-autofocus>
          <X className="h-4 w-4" /> Close
        </Button>
      </header>
      <div className={`min-h-0 flex-1 ${isPdf ? '' : 'overflow-auto bg-muted/40 p-4'}`}>
        {isPdf ? (
          url && <iframe src={url} title={title} className="h-full w-full border-0 bg-white" />
        ) : (
          url && <img src={url} alt={title} className={actualSize ? 'mx-auto max-w-none' : 'mx-auto h-full w-full object-contain'} />
        )}
      </div>
    </div>,
    document.body,
  )
}
