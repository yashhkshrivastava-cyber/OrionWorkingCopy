import { useEffect, useState } from 'react'
import { HardDrive } from 'lucide-react'
import { api } from '../../api/client'
import type { DriveLink, DriveStatus } from '../../types'
import { driveFolderOf } from '../documents/driveNodes'
import { FolderPicker } from '../documents/FolderPicker'
import { Alert } from '../ui/Alert'
import { Button } from '../ui/Button'
import { Checkbox } from '../ui/Field'
import { formatDateTime } from '../../formatTime'

/** The Drive status, read once per screen. Null until it arrives or when Drive cannot be reached. */
export function useDriveStatus(): DriveStatus | null {
  const [status, setStatus] = useState<DriveStatus | null>(null)
  useEffect(() => {
    let live = true
    api
      .driveStatus()
      .then((found) => live && setStatus(found))
      .catch(() => undefined) // no Drive is not an error on a bill
    return () => {
      live = false
    }
  }, [])
  return status
}

export interface DriveChoice {
  /** The tick: also save this bill to Google Drive. */
  save: boolean
  folder: { id: string; label: string } | null
}

/**
 * "Also save to Google Drive" on a new bill: a tick and the Drive folder. It starts as the company's setting says (off, ticked only if the
 * person ticks it, or ticked with the company's folder), and only appears when Drive is connected and the company has not turned it off for bills.
 */
export function BillDrive({
  status,
  value,
  onChange,
  canChoose,
}: {
  status: DriveStatus | null
  value: DriveChoice
  onChange: (next: DriveChoice) => void
  canChoose: boolean
}) {
  const [picking, setPicking] = useState(false)
  if (!status || !status.connected || status.bills.mode === 'off') return null
  return (
    <section className="rounded-xl border border-[color:var(--color-border)] bg-surface p-4">
      <div className="flex items-start gap-3">
        <HardDrive className="mt-0.5 h-5 w-5 shrink-0 text-accent" aria-hidden="true" />
        <div className="min-w-0 flex-1 space-y-2">
          <Checkbox
            label="Also save a copy to Google Drive"
            checked={value.save}
            onChange={(save) => (canChoose ? onChange({ ...value, save }) : undefined)}
          />
          <p className="text-xs text-[color:var(--color-text-muted)]">
            {value.save
              ? 'The PDF of this bill is put in the folder below, and kept up to date if the bill is edited or cancelled.'
              : 'The bill stays in Orion only. You can save it to Drive later from the bill’s page.'}
            {status.mode === 'fake' ? ' (The practice Drive on this computer.)' : ''}
          </p>
          {value.save && (
            <div className="flex flex-wrap items-center gap-2">
              <span className="min-w-0 flex-1 truncate rounded-lg border border-[color:var(--color-border)] px-3 py-1.5 text-sm text-[color:var(--color-text)]" title={value.folder?.label}>
                {value.folder?.label ?? 'No folder chosen'}
              </span>
              {canChoose && (
                <Button variant="secondary" size="sm" onClick={() => setPicking(true)}>
                  {value.folder ? 'Change folder' : 'Choose folder'}
                </Button>
              )}
            </div>
          )}
          {!canChoose && <p className="text-xs text-[color:var(--color-text-faint)]">Only people who may change documents can choose this.</p>}
        </div>
      </div>
      <FolderPicker
        open={picking}
        title="Save this bill in Google Drive"
        confirmLabel="Use this folder"
        source="drive"
        startNode="gdrive"
        canMakeFolders={canChoose}
        onClose={() => setPicking(false)}
        onPick={(node, label) => {
          onChange({ save: true, folder: { id: driveFolderOf(node), label } })
          setPicking(false)
        }}
      />
    </section>
  )
}

/** What a new bill starts with, from the company's setting. */
export function startingChoice(status: DriveStatus | null): DriveChoice {
  const on = status?.bills.mode === 'on' && Boolean(status.bills.folder_id)
  return {
    save: on,
    folder: status?.bills.folder_id ? { id: status.bills.folder_id, label: status.bills.folder_label ?? 'Drive folder' } : null,
  }
}

/**
 * On an issued bill's page: whether its PDF is in Google Drive, where, and whether it is up to date, with the buttons to put it there, move it,
 * retry after a failure, or stop keeping it up to date. Nothing here changes the bill.
 */
export function BillDriveLink({ billCode, canChange, refreshKey }: { billCode: string; canChange: boolean; refreshKey: number }) {
  const status = useDriveStatus()
  const [link, setLink] = useState<DriveLink | null>(null)
  const [picking, setPicking] = useState(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [tick, setTick] = useState(0)

  useEffect(() => {
    if (!status?.connected) return
    api
      .driveBillLink(billCode)
      .then((r) => setLink(r.link))
      .catch(() => setLink(null))
  }, [billCode, status?.connected, refreshKey, tick])

  if (!status || !status.connected) return null

  const run = async (action: () => Promise<{ link: DriveLink | null }>) => {
    setBusy(true)
    setError('')
    try {
      setLink((await action()).link)
    } catch (e) {
      setError((e as Error).message)
    } finally {
      setBusy(false)
      setTick((n) => n + 1)
    }
  }

  const choose = (node: string) => run(() => api.driveSaveBill(billCode, driveFolderOf(node)))

  return (
    <section className="rounded-xl border border-[color:var(--color-border)] bg-surface px-4 py-3">
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div className="min-w-0">
          <p className="flex items-center gap-2 text-sm font-semibold text-[color:var(--color-text)]">
            <HardDrive className="h-4 w-4 text-accent" aria-hidden="true" /> Google Drive
          </p>
          {!link ? (
            <p className="mt-0.5 text-xs text-[color:var(--color-text-muted)]">This bill is not saved to Drive.</p>
          ) : link.state === 'stopped' ? (
            <p className="mt-0.5 text-xs text-[color:var(--color-text-muted)]">Saved in {link.folder_label}, but no longer kept up to date.</p>
          ) : link.state === 'failed' ? (
            <p className="mt-0.5 text-xs text-negative">Not saved yet{link.folder_label ? ` to ${link.folder_label}` : ''}: {link.error ?? 'Drive did not answer.'}</p>
          ) : (
            <p className="mt-0.5 text-xs text-[color:var(--color-text-muted)]">
              Saved as <span className="font-medium text-[color:var(--color-text)]">{link.name}</span> in {link.folder_label}
              {link.updated ? ` · updated ${formatDateTime(link.updated)}` : ''}. It follows the bill.
            </p>
          )}
        </div>
        <div className="flex flex-wrap gap-2">
          {link?.url && (
            <a href={link.url} target="_blank" rel="noopener noreferrer" className="inline-flex items-center rounded-lg border border-[color:var(--color-border-strong)] px-3 py-1.5 text-sm font-medium text-[color:var(--color-text)] hover:bg-muted">
              Open in Drive
            </a>
          )}
          {canChange && link?.state === 'failed' && (
            <Button size="sm" loading={busy} onClick={() => void run(() => api.driveSyncBill(billCode))}>
              Try again
            </Button>
          )}
          {canChange && link?.state === 'stopped' && (
            <Button size="sm" loading={busy} onClick={() => void choose(link.folder_id ? `gdrive:${link.folder_id}` : 'gdrive')}>
              Keep it up to date
            </Button>
          )}
          {canChange && link && link.state === 'synced' && (
            <Button variant="ghost" size="sm" loading={busy} onClick={() => void run(() => api.driveStopBill(billCode))}>
              Stop updating
            </Button>
          )}
          {canChange && (
            <Button variant="secondary" size="sm" onClick={() => setPicking(true)}>
              {link ? 'Change folder' : 'Save to Drive…'}
            </Button>
          )}
        </div>
      </div>
      {error && (
        <div className="mt-2">
          <Alert variant="error" onDismiss={() => setError('')}>
            {error}
          </Alert>
        </div>
      )}
      <FolderPicker
        open={picking}
        title="Save this bill in Google Drive"
        confirmLabel="Save here"
        source="drive"
        startNode={link?.folder_id ? `gdrive:${link.folder_id}` : status.bills.folder_id ? `gdrive:${status.bills.folder_id}` : 'gdrive'}
        canMakeFolders={canChange}
        onClose={() => setPicking(false)}
        onPick={async (node) => {
          await choose(node)
          setPicking(false)
        }}
      />
    </section>
  )
}
