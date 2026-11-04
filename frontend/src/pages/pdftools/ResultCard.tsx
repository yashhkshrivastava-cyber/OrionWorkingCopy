import { useEffect, useState } from 'react'
import { Download, Eye, RotateCcw } from 'lucide-react'
import { Button } from '../../components/ui/Button'
import { Select } from '../../components/ui/Field'
import { PdfPreview, saveBlob } from '../../components/ui/PdfPreview'
import type { PdfToolResult } from '../../types'
import { formatBytes, plural } from './format'
import { TOOLS } from './tools'

/** What came out of a tool: how big, what to do with it (save it, look at it, carry on with it in another tool). */
export function ResultCard({
  result,
  toolId,
  onAgain,
  onContinue,
}: {
  result: PdfToolResult
  toolId: string
  onAgain: () => void
  onContinue: (nextTool: string) => void
}) {
  const [looking, setLooking] = useState(false)
  const [text, setText] = useState<string | null>(null)
  const isPdf = result.mediaType.includes('pdf')
  const isText = result.mediaType.startsWith('text/')
  const isZip = result.mediaType.includes('zip')

  useEffect(() => {
    let live = true
    setText(null)
    if (isText) {
      result.blob.text().then((body) => live && setText(body.replace(/^﻿/, '').slice(0, 6000)))
    }
    return () => {
      live = false
    }
  }, [result, isText])

  const facts = [
    isPdf && result.pages ? plural(result.pages, 'page', 'pages') : null,
    isZip && result.files ? plural(result.files, 'file', 'files') : null,
    formatBytes(result.bytesOut),
    result.bytesIn && toolId === 'compress' ? `was ${formatBytes(result.bytesIn)}` : null,
  ].filter(Boolean)

  const next = TOOLS.filter((tool) => tool.id !== toolId && (tool.accept === 'pdf' || tool.accept === 'pdfs'))

  return (
    <section className="page-enter space-y-3 rounded-xl border border-positive/30 bg-positive-dim/40 p-4" aria-label="The result" aria-live="polite">
      <div>
        <p className="text-sm font-semibold text-[color:var(--color-text)]">Done: {result.name}</p>
        <p className="text-xs text-[color:var(--color-text-muted)]">{facts.join(' · ')}</p>
        {result.note && <p className="mt-1 text-sm text-[color:var(--color-text)]">{result.note}</p>}
      </div>

      {isText && text !== null && (
        <pre className="max-h-64 overflow-auto whitespace-pre-wrap rounded-lg border border-[color:var(--color-border)] bg-surface p-3 text-xs text-[color:var(--color-text)]">
          {text}
          {result.bytesOut > 6000 ? '\n…' : ''}
        </pre>
      )}

      <div className="flex flex-wrap items-center gap-2">
        <Button onClick={() => saveBlob(result.blob, result.name)}>
          <Download className="h-4 w-4" /> Download
        </Button>
        {isPdf && (
          <Button variant="secondary" onClick={() => setLooking(true)}>
            <Eye className="h-4 w-4" /> Look at it
          </Button>
        )}
        <Button variant="ghost" onClick={onAgain}>
          <RotateCcw className="h-4 w-4" /> Start again
        </Button>
        {isPdf && (
          <div className="ml-auto flex items-center gap-2">
            <label htmlFor="pdf-continue" className="text-xs text-[color:var(--color-text-muted)]">
              Carry on with this file in
            </label>
            <div className="w-48">
              <Select id="pdf-continue" value="" onChange={(event) => event.target.value && onContinue(event.target.value)}>
                <option value="">Choose a tool…</option>
                {next.map((tool) => (
                  <option key={tool.id} value={tool.id}>
                    {tool.title}
                  </option>
                ))}
              </Select>
            </div>
          </div>
        )}
      </div>

      {isPdf && <PdfPreview open={looking} title={result.name} blob={result.blob} filename={result.name} onClose={() => setLooking(false)} />}
    </section>
  )
}
