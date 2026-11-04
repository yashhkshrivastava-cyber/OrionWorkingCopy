import { useEffect, useState } from 'react'
import { api } from '../../api/client'
import { formatDateTime } from '../../formatTime'
import { Alert } from '../ui/Alert'
import { Button } from '../ui/Button'
import { Modal } from '../ui/Modal'
import { useLumen } from '../../lumen/useLumen'
import type { HistoryChange, HistoryEntry, RecordHistory } from '../../types'

const shown = (value: HistoryChange['from']): string => {
  if (value === null || value === '') return 'empty'
  if (typeof value === 'boolean') return value ? 'Yes' : 'No'
  if (typeof value === 'number') return value.toLocaleString('en-IN')
  return String(value)
}

const VERB: Record<HistoryEntry['kind'], string> = {
  created: 'Created',
  changed: 'Changed',
  deleted: 'Deleted',
}

/**
 * Who created, changed or deleted one record, and what they changed, read from the warehouse.
 * The warehouse loads on a schedule, so the newest save may not be listed yet; the dialog says so.
 */
export function RecordHistoryModal({
  open,
  entity,
  recordId,
  recordLabel,
  onClose,
}: {
  open: boolean
  entity: string
  recordId: string
  recordLabel: string
  onClose: () => void
}) {
  const lumen = useLumen()
  const [history, setHistory] = useState<RecordHistory | null>(null)
  const [error, setError] = useState('')

  useEffect(() => {
    if (!open || !recordId) return
    setHistory(null)
    setError('')
    api
      .recordHistory(entity, recordId)
      .then(setHistory)
      .catch((e: Error) => setError(e.message))
  }, [open, entity, recordId])

  return (
    <Modal
      open={open}
      title={`History of ${recordLabel || recordId}`}
      size="xl"
      onClose={onClose}
      footer={
        <Button variant="secondary" onClick={onClose}>
          Close
        </Button>
      }
    >
      <div className="space-y-4">
        {error && <Alert variant="error">{error}</Alert>}
        {!history && !error && <div className="shimmer h-24 rounded-lg bg-muted" aria-busy="true" />}

        {history?.pending && (
          <Alert variant="info">
            This record was saved after the warehouse was last loaded
            {history.loaded ? ` (${formatDateTime(history.loaded)})` : ''}, so its newest change is not listed yet. The
            warehouse loads by itself every hour, or run the Orion warehouse from the ETL page.
          </Alert>
        )}

        {history && history.entries.length === 0 && !history.pending && (
          <p className="text-sm text-[color:var(--color-text-muted)]">
            The warehouse has no history for this record yet.
          </p>
        )}

        {history && history.entries.length > 0 && (
          <ol className={lumen ? 'lumen-timeline space-y-4' : 'space-y-3'}>
            {history.entries.map((entry, index) => (
              <li
                key={index}
                className={lumen ? 'lumen-timeline-item relative rounded-2xl border border-[color:var(--color-border)] bg-surface px-4 py-3' : 'rounded-xl border border-[color:var(--color-border)] bg-surface px-4 py-3'}
              >
                <p className="text-sm font-semibold text-[color:var(--color-text)]">
                  {VERB[entry.kind]}
                  <span className="font-normal text-[color:var(--color-text-muted)]">
                    {' '}
                    {entry.by ? `by ${entry.by}` : 'by someone, before changes were tracked'}
                    {entry.when ? ` · ${formatDateTime(entry.when)}` : ''}
                  </span>
                </p>
                {entry.kind === 'changed' && entry.changes.length === 0 && (
                  <p className="mt-1 text-xs text-[color:var(--color-text-muted)]">
                    Something not shown on this record&apos;s form was changed.
                  </p>
                )}
                {entry.changes.length > 0 && (
                  <ul className="mt-2 space-y-1 text-sm">
                    {entry.changes.map((change) => (
                      <li key={change.field} className="flex flex-wrap items-baseline gap-x-2">
                        <span className="w-40 shrink-0 text-xs font-medium text-[color:var(--color-text-muted)]">
                          {change.label}
                        </span>
                        <span className={lumen ? 'rounded-full bg-negative-dim px-2.5 py-0.5 text-xs text-negative line-through' : 'text-[color:var(--color-text-muted)] line-through decoration-[color:var(--color-text-faint)]'}>
                          {change.from_label ?? shown(change.from)}
                        </span>
                        <span aria-hidden="true">→</span>
                        <span className={lumen ? 'rounded-full bg-positive-dim px-2.5 py-0.5 text-xs font-semibold text-positive' : 'font-medium text-[color:var(--color-text)]'}>{change.to_label ?? shown(change.to)}</span>
                      </li>
                    ))}
                  </ul>
                )}
              </li>
            ))}
          </ol>
        )}

        {history?.loaded && (
          <p className="text-xs text-[color:var(--color-text-faint)]">
            Read from the warehouse, last loaded {formatDateTime(history.loaded)}. If a record is changed more than once
            between two loads, only the final change is listed.
          </p>
        )}
      </div>
    </Modal>
  )
}
