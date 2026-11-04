import { useRef, useState, type DragEvent } from 'react'
import { CircleAlert, CircleCheck, FileSpreadsheet, TriangleAlert, Upload } from 'lucide-react'
import { ApiError, bankApi } from '../../api/client'
import { day, money } from '../../bank/format'
import type { BankImportResult, BankStatementPreview } from '../../types'
import { Alert } from '../ui/Alert'
import { Button } from '../ui/Button'
import { Select } from '../ui/Field'

const FIELDS: { key: string; label: string; hint: string }[] = [
  { key: 'date', label: 'Date', hint: 'Required' },
  { key: 'description', label: 'Narration', hint: 'What the bank wrote' },
  { key: 'reference', label: 'Reference', hint: 'Cheque or UTR number' },
  { key: 'debit', label: 'Money out', hint: 'Withdrawals' },
  { key: 'credit', label: 'Money in', hint: 'Deposits' },
  { key: 'amount', label: 'Amount', hint: 'When there is one column for both' },
  { key: 'type', label: 'Dr / Cr', hint: 'Says which way an Amount went' },
  { key: 'balance', label: 'Balance', hint: 'Lets Orion check it read the file right' },
]

/**
 * A bank statement from the bank's own website (a CSV or an Excel file), read and shown before anything is saved: the period, how many lines are new,
 * and whether the running balance column follows from line to line, which is how Orion knows it read the file right. If it guessed a column wrong,
 * the person picks the right one and it reads the file again. The file itself is not kept, only its lines.
 */
export function StatementUpload({ onImported, accountId }: { onImported: (result: BankImportResult) => void; accountId?: number }) {
  const [file, setFile] = useState<File | null>(null)
  const [preview, setPreview] = useState<BankStatementPreview | null>(null)
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  const [over, setOver] = useState(false)
  const input = useRef<HTMLInputElement>(null)
  const working = useRef(false)

  const read = async (chosen: File, mapping?: Record<string, number>, headerRow?: number) => {
    setBusy(true)
    setError('')
    try {
      setPreview(await bankApi.previewStatement(chosen, mapping, headerRow, accountId))
    } catch (err) {
      setPreview(null)
      setError(err instanceof Error ? err.message : 'That file could not be read.')
    } finally {
      setBusy(false)
    }
  }

  const choose = (chosen: File | undefined) => {
    if (!chosen) return
    setFile(chosen)
    setPreview(null)
    void read(chosen)
  }

  const drop = (event: DragEvent) => {
    event.preventDefault()
    setOver(false)
    choose(event.dataTransfer.files[0])
  }

  const reset = () => {
    setFile(null)
    setPreview(null)
    setError('')
    if (input.current) input.current.value = ''
  }

  const pick = (key: string, value: string) => {
    if (!file || !preview) return
    const next = { ...preview.mapping }
    if (value === '') delete next[key]
    else next[key] = Number(value)
    void read(file, next, preview.header_row)
  }

  const importIt = async () => {
    if (!file || !preview || working.current) return
    working.current = true
    setBusy(true)
    setError('')
    try {
      const result = await bankApi.importStatement(file, preview.mapping, preview.header_row, accountId)
      reset()
      onImported(result)
    } catch (err) {
      setError(err instanceof ApiError || err instanceof Error ? err.message : 'That did not import. Try again.')
    } finally {
      working.current = false
      setBusy(false)
    }
  }

  return (
    <section aria-label="Upload a statement" className="panel space-y-4 p-5">
      <div>
        <h2 className="t-h3">Upload a bank statement</h2>
        <p className="t-caption mt-0.5">
          Download the statement from your bank’s website as CSV or Excel. Orion matches each line to a payment, expense or entry it already has, and shows you what it cannot find. Uploading the same period twice
          is safe.
        </p>
      </div>

      {!file && (
        <label
          onDragOver={(e) => {
            e.preventDefault()
            setOver(true)
          }}
          onDragLeave={() => setOver(false)}
          onDrop={drop}
          className={`interactive flex cursor-pointer flex-col items-center gap-2 rounded-xl border-2 border-dashed px-6 py-10 text-center ${over ? 'border-accent bg-accent-dim/40' : 'border-[color:var(--color-border-strong)] hover:border-accent'}`}
        >
          <Upload className="h-6 w-6 text-accent" aria-hidden="true" />
          <span className="text-sm font-medium">Drop the statement here, or choose a file</span>
          <span className="t-caption">CSV or Excel (.xlsx), up to 6 MB. A PDF cannot be read: ask the bank for the Excel or CSV download.</span>
          <input ref={input} type="file" accept=".csv,.txt,.xlsx" className="sr-only" onChange={(e) => choose(e.target.files?.[0])} />
        </label>
      )}

      {file && (
        <div className="flex flex-wrap items-center justify-between gap-2 rounded-xl bg-muted px-3 py-2 text-sm">
          <span className="flex min-w-0 items-center gap-2">
            <FileSpreadsheet className="h-4 w-4 shrink-0 text-accent" aria-hidden="true" />
            <span className="truncate font-medium">{file.name}</span>
            <span className="t-caption">{Math.max(1, Math.round(file.size / 1024))} KB</span>
          </span>
          <Button variant="ghost" size="sm" onClick={reset} disabled={busy}>
            Choose another
          </Button>
        </div>
      )}

      {busy && !preview && (
        <p className="t-small text-[color:var(--color-text-muted)]" role="status">
          Reading the statement…
        </p>
      )}
      {error && <Alert variant="error">{error}</Alert>}

      {preview && (
        <div className={`space-y-4 ${busy ? 'opacity-60' : ''}`} aria-busy={busy}>
          <dl className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
            <div className="rounded-xl bg-muted/60 p-3">
              <dt className="t-label text-[color:var(--color-text-muted)]">Period</dt>
              <dd className="mt-0.5 text-sm font-semibold">{day(preview.period_from)} – {day(preview.period_to)}</dd>
            </div>
            <div className="rounded-xl bg-muted/60 p-3">
              <dt className="t-label text-[color:var(--color-text-muted)]">Lines</dt>
              <dd className="mt-0.5 text-sm font-semibold">
                {preview.line_count.toLocaleString('en-IN')} · <span className="text-positive">{preview.new_lines.toLocaleString('en-IN')} new</span>
                {preview.known_lines > 0 && <span className="font-normal text-[color:var(--color-text-muted)]"> · {preview.known_lines.toLocaleString('en-IN')} already held</span>}
              </dd>
            </div>
            <div className="rounded-xl bg-muted/60 p-3">
              <dt className="t-label text-[color:var(--color-text-muted)]">Money in / out</dt>
              <dd className="mt-0.5 text-sm font-semibold tabular-nums">
                <span className="text-positive">{money(preview.money_in)}</span> / <span className="text-negative">{money(preview.money_out)}</span>
              </dd>
            </div>
            <div className="rounded-xl bg-muted/60 p-3">
              <dt className="t-label text-[color:var(--color-text-muted)]">Closing balance</dt>
              <dd className="mt-0.5 text-sm font-semibold tabular-nums">{preview.closing_balance === null ? 'Not in the file' : money(preview.closing_balance)}</dd>
            </div>
          </dl>

          {preview.balanced === true && (
            <p className="flex items-start gap-2 text-sm text-positive">
              <CircleCheck className="mt-0.5 h-4 w-4 shrink-0" aria-hidden="true" />
              <span>
                The running balance follows from line to line ({preview.balance_checked.toLocaleString('en-IN')} checks, none failed), so Orion has read every amount and direction correctly.
                {preview.newest_first && ' The file lists the newest line first; Orion put them in order.'}
              </span>
            </p>
          )}
          {preview.balanced === false && (
            <p className="flex items-start gap-2 text-sm text-negative">
              <CircleAlert className="mt-0.5 h-4 w-4 shrink-0" aria-hidden="true" />
              <span>
                The balance does not follow at {preview.balance_breaks} of {preview.balance_checked} lines, so a column may have been read wrongly. Check the columns below before importing.
              </span>
            </p>
          )}
          {preview.balanced === null && (
            <p className="flex items-start gap-2 text-sm text-[color:var(--color-text-muted)]">
              <TriangleAlert className="mt-0.5 h-4 w-4 shrink-0 text-warning" aria-hidden="true" />
              <span>This file has no balance column, so Orion cannot check its reading. Look at the first lines below.</span>
            </p>
          )}
          {preview.opening_balance !== null && preview.book_balance_before_period !== null && Math.abs(preview.opening_balance - preview.book_balance_before_period) > 0.004 && (
            <Alert variant="info">
              The statement says the balance was {money(preview.opening_balance)} before {day(preview.period_from)}; Orion’s book says {money(preview.book_balance_before_period)}. The difference of{' '}
              {money(preview.opening_balance - preview.book_balance_before_period)} is something not yet entered (or a different opening balance). It will show on Reconcile.
            </Alert>
          )}
          {preview.before_opening_date > 0 && (
            <p className="t-caption">
              {preview.before_opening_date} line{preview.before_opening_date === 1 ? ' is' : 's are'} dated before the opening date ({day(preview.opening_date)}) and will be set aside: they are already inside the opening balance.
            </p>
          )}
          {preview.issues.length > 0 && (
            <ul className="space-y-1 text-sm">
              {preview.issues.slice(0, 6).map((issue, at) => (
                <li key={at} className={`flex items-start gap-2 ${issue.severity === 'error' ? 'text-negative' : 'text-[color:var(--color-text-muted)]'}`}>
                  <TriangleAlert className="mt-0.5 h-4 w-4 shrink-0 text-warning" aria-hidden="true" />
                  <span>
                    {issue.row ? `Row ${issue.row}: ` : ''}
                    {issue.message}
                  </span>
                </li>
              ))}
              {preview.issues.length > 6 && <li className="t-caption">…and {preview.issues.length - 6} more.</li>}
            </ul>
          )}

          <details className="rounded-xl border border-[color:var(--color-border)] p-3" open={preview.balanced === false}>
            <summary className="cursor-pointer text-sm font-medium">How the columns were read</summary>
            <div className="mt-3 grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
              {FIELDS.map((field) => (
                <label key={field.key} className="block text-xs">
                  <span className="t-label block text-[color:var(--color-text)]">{field.label}</span>
                  <Select value={preview.mapping[field.key] === undefined ? '' : String(preview.mapping[field.key])} onChange={(e) => pick(field.key, e.target.value)} disabled={busy} aria-label={field.label}>
                    <option value="">Not in the file</option>
                    {preview.headers.map((header, at) => (
                      <option key={at} value={at}>
                        {header || `Column ${at + 1}`}
                      </option>
                    ))}
                  </Select>
                  <span className="t-caption">{field.hint}</span>
                </label>
              ))}
            </div>
            {preview.sample.length > 0 && (
              <div className="mt-3 overflow-x-auto">
                <table className="w-full text-xs">
                  <caption className="sr-only">The first rows of the file</caption>
                  <tbody>
                    {preview.sample.map((row, r) => (
                      <tr key={r} className={r === 0 ? 'font-semibold' : ''}>
                        {row.map((cell, c) => (
                          <td key={c} className="whitespace-nowrap border-b border-[color:var(--color-border)]/60 px-2 py-1">
                            {cell}
                          </td>
                        ))}
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </details>

          {preview.already_imported && <Alert variant="info">This exact file has already been imported.</Alert>}
          <div className="flex flex-wrap items-center gap-3">
            <Button onClick={importIt} loading={busy} disabled={!preview.can_import || preview.new_lines === 0}>
              {preview.new_lines > 0 ? `Import ${preview.new_lines.toLocaleString('en-IN')} new line${preview.new_lines === 1 ? '' : 's'}` : 'Nothing new to import'}
            </Button>
            <Button variant="ghost" onClick={reset} disabled={busy}>
              Cancel
            </Button>
          </div>
        </div>
      )}
    </section>
  )
}
