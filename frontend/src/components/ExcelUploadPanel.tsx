import { DropZone } from '../lumen/DropZone'
import { useLumen } from '../lumen/useLumen'
import { useEffect, useRef, useState } from 'react'
import { Download, FileSpreadsheet } from 'lucide-react'
import { api, type ExcelUploadResult } from '../api/client'
import { CardHeader } from './ui/Card'
import { Button } from './ui/Button'
import { Alert } from './ui/Alert'
import { Field, Input } from './ui/Field'

export function ExcelUploadPanel({
  entityName,
  mergeKey,
  onInserted,
  hideHeader = false,
}: {
  entityName: string
  mergeKey?: string[]
  onInserted: (result: ExcelUploadResult) => void
  hideHeader?: boolean
}) {
  const lumen = useLumen()
  const inputRef = useRef<HTMLInputElement>(null)
  const [file, setFile] = useState<File | null>(null)
  const [downloading, setDownloading] = useState(false)
  const [uploading, setUploading] = useState(false)
  const [error, setError] = useState('')
  const [result, setResult] = useState<ExcelUploadResult | null>(null)

  useEffect(() => {
    setFile(null)
    setError('')
    setResult(null)
    if (inputRef.current) inputRef.current.value = ''
  }, [entityName])

  const downloadTemplate = async () => {
    setError('')
    setDownloading(true)
    try {
      await api.downloadExcelTemplate(entityName)
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Could not download the template')
    } finally {
      setDownloading(false)
    }
  }

  const upload = async () => {
    setError('')
    setResult(null)
    if (!file) {
      setError('Choose an Excel file first.')
      return
    }
    setUploading(true)
    try {
      const next = await api.uploadExcel(entityName, file)
      setResult(next)
      if (next.ok) {
        setFile(null)
        if (inputRef.current) inputRef.current.value = ''
        onInserted(next)
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Upload failed')
    } finally {
      setUploading(false)
    }
  }

  const errorPreview = result?.errors.slice(0, 20) || []

  return (
    <>
      {!hideHeader && (
        <CardHeader
          title="Upload Excel"
          subtitle={`Upload ${entityName.toLowerCase()} records from a spreadsheet. Matching merge keys update; new keys insert.`}
        />
      )}

      <div className="rounded-2xl border border-accent/20 bg-accent-dim/60 px-4 py-3 text-sm text-[color:var(--color-text-muted)]">
        Download the template for this dataset, fill the <span className="font-medium text-[color:var(--color-text)]">Records</span> sheet,
        then upload it. Lookup columns (case, client, car, and so on) can use the name or the code. Rows merge on{' '}
        <span className="font-medium text-[color:var(--color-text)]">
          {(mergeKey && mergeKey.length ? mergeKey : ['the generated code']).join(' + ')}
        </span>
        . Matching keys update; new keys insert.
      </div>

      <div className="mt-5 flex flex-wrap gap-3">
        <Button variant="secondary" loading={downloading} onClick={downloadTemplate}>
          <Download className="h-4 w-4" />
          Download template
        </Button>
      </div>

      {lumen ? (
        <div className="mt-5 max-w-xl">
          <DropZone
            file={file}
            inputRef={inputRef}
            accept=".xlsx,application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
            title="Drop the Excel file here"
            onFile={(chosen) => {
              setResult(null)
              setError('')
              setFile(chosen)
            }}
          />
        </div>
      ) : (
        <>
      <Field label="Excel file" className="mt-5 max-w-xl">
        <Input
          ref={inputRef}
          type="file"
          accept=".xlsx,application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
          onChange={(e) => {
            setResult(null)
            setError('')
            setFile(e.target.files?.[0] || null)
          }}
        />
      </Field>
      {file && (
        <p className="mt-2 flex items-center gap-2 text-sm text-[color:var(--color-text-muted)]">
          <FileSpreadsheet className="h-4 w-4 text-accent" />
          {file.name}
        </p>
      )}
        </>
      )}

      <div className="mt-6 space-y-3">
        {error && (
          <Alert variant="error" onDismiss={() => setError('')}>
            {error}
          </Alert>
        )}
        {result?.ok && (
          <Alert variant="success" onDismiss={() => setResult(null)}>
            {result.inserted} inserted, {result.updated ?? 0} updated.
          </Alert>
        )}
        {result?.ok && (result.warnings?.length ?? 0) > 0 && (
          <Alert variant="warning">
            <span className="font-medium">
              {result.warnings?.length} row{result.warnings?.length === 1 ? '' : 's'} look{result.warnings?.length === 1 ? 's' : ''} like another expense. They were saved; check they are not entered twice.
            </span>
            <ul className="mt-1 max-h-48 list-disc overflow-auto pl-5">
              {result.warnings?.slice(0, 20).map((item) => (
                <li key={`${item.row}-${item.message}`}>
                  Row {item.row}: {item.message}
                </li>
              ))}
            </ul>
          </Alert>
        )}
        {result && !result.ok && (
          <Alert variant="error" onDismiss={() => setResult(null)}>
            Nothing was uploaded. Fix the rows below and upload again.
          </Alert>
        )}
        {errorPreview.length > 0 && (
          <ul className="max-h-64 overflow-auto rounded-md border border-negative/30 bg-negative-dim px-4 py-3 text-sm text-negative">
            {errorPreview.map((item) => (
              <li key={`${item.row}-${item.message}`} className="py-0.5">
                Row {item.row}: {item.message}
              </li>
            ))}
            {result && result.errors.length > errorPreview.length && (
              <li className="pt-1 font-medium">
                …and {result.errors.length - errorPreview.length} more
              </li>
            )}
          </ul>
        )}
        <Button variant="primary" loading={uploading} disabled={!file} onClick={upload}>
          Upload records
        </Button>
      </div>
    </>
  )
}
