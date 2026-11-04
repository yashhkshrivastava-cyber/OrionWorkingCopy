import { useState, type DragEvent, type RefObject } from 'react'
import { FileSpreadsheet, UploadCloud, X } from 'lucide-react'

/** A place to drop a file or click to choose one. The real file input is inside it (and keeps its ref), so the keyboard and screen readers still work. */
export function DropZone({
  file,
  onFile,
  accept,
  inputRef,
  title = 'Drop the file here',
  hint = 'or click to choose it from this computer',
}: {
  file: File | null
  onFile: (file: File | null) => void
  accept: string
  inputRef?: RefObject<HTMLInputElement | null>
  title?: string
  hint?: string
}) {
  const [over, setOver] = useState(false)
  const drop = (event: DragEvent) => {
    event.preventDefault()
    setOver(false)
    const dropped = event.dataTransfer.files?.[0]
    if (dropped) onFile(dropped)
  }
  return (
    <div
      onDragOver={(event) => {
        event.preventDefault()
        setOver(true)
      }}
      onDragLeave={() => setOver(false)}
      onDrop={drop}
      className={`relative rounded-[1.75rem] border-2 border-dashed p-8 text-center transition-all duration-300 ${over ? 'scale-[1.01] border-[color:var(--color-accent)] bg-accent-dim/60' : 'border-[color:var(--color-border-strong)] bg-[color:color-mix(in_srgb,var(--orion-surface)_60%,transparent)] hover:border-[color:var(--color-accent)]'}`}
    >
      <input
        ref={inputRef}
        type="file"
        accept={accept}
        aria-label="Choose a file"
        className="absolute inset-0 h-full w-full cursor-pointer opacity-0"
        onChange={(event) => onFile(event.target.files?.[0] ?? null)}
      />
      {file ? (
        <div className="relative z-10 flex items-center justify-center gap-3">
          <span className="grid h-12 w-12 place-items-center rounded-2xl bg-positive-dim text-positive">
            <FileSpreadsheet className="h-6 w-6" />
          </span>
          <div className="text-left">
            <p className="font-display text-base font-semibold">{file.name}</p>
            <p className="t-caption text-[color:var(--color-text-muted)]">{(file.size / 1024).toFixed(0)} KB · ready to upload</p>
          </div>
          <button
            type="button"
            aria-label="Remove the file"
            onClick={() => {
              if (inputRef?.current) inputRef.current.value = ''
              onFile(null)
            }}
            className="interactive relative z-20 grid h-8 w-8 place-items-center rounded-full text-[color:var(--color-text-faint)] hover:bg-muted"
          >
            <X className="h-4 w-4" />
          </button>
        </div>
      ) : (
        <div className="pointer-events-none">
          <span className={`lumen-orb mx-auto grid h-16 w-16 place-items-center rounded-3xl text-white shadow-lg [background:linear-gradient(135deg,var(--lumen-indigo),var(--lumen-pink))] ${over ? 'scale-110' : ''}`}>
            <UploadCloud className="h-8 w-8" />
          </span>
          <p className="font-display mt-4 text-lg font-semibold">{title}</p>
          <p className="t-caption mt-1 text-[color:var(--color-text-muted)]">{hint}</p>
        </div>
      )}
    </div>
  )
}
