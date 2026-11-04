import { useCallback, useEffect, useState } from 'react'
import { FolderOpen } from 'lucide-react'
import { api } from '../../api/client'
import type { SourceLocations } from '../../types'
import { FolderPicker } from '../documents/FolderPicker'
import { Alert } from '../ui/Alert'
import { Button } from '../ui/Button'
import { TabLink } from '../ui/TabLink'

/**
 * Where an issued bill is kept in the Document Center, each place a link that opens there, and (for people who may change documents) a
 * button to keep it somewhere else. Changing it moves the filed copy only; the bill itself is not edited and gets no new version.
 */
export function BillFiledIn({ billCode, canChange, refreshKey }: { billCode: string; canChange: boolean; refreshKey: number }) {
  const [found, setFound] = useState<SourceLocations | null>(null)
  const [error, setError] = useState('')
  const [picking, setPicking] = useState(false)
  const [busy, setBusy] = useState(false)

  const load = useCallback(() => {
    api
      .sourceLocations('bill', billCode)
      .then((r) => {
        setFound(r)
        setError('')
      })
      .catch(() => setFound(null)) // not filed yet: nothing to show
  }, [billCode])

  useEffect(load, [load, refreshKey])

  const choose = async (to: string | null) => {
    setBusy(true)
    setError('')
    try {
      setFound(await api.chooseSourceHome('bill', billCode, to))
    } catch (e) {
      setError((e as Error).message)
    } finally {
      setBusy(false)
    }
  }

  if (!found || found.deleted || found.locations.length === 0) return null

  return (
    <section className="rounded-xl border border-[color:var(--color-border)] bg-surface px-4 py-3">
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div>
          <p className="text-sm font-semibold text-[color:var(--color-text)]">Kept in Documents</p>
          <p className="mt-0.5 text-xs text-[color:var(--color-text-muted)]">
            {found.chosen ? 'In the folder chosen for it.' : 'Where Orion files every bill by itself.'}
          </p>
        </div>
        {canChange && (
          <div className="flex gap-2">
            {found.chosen && (
              <Button variant="ghost" size="sm" loading={busy} onClick={() => void choose(null)}>
                Back to the usual place
              </Button>
            )}
            <Button variant="secondary" size="sm" onClick={() => setPicking(true)}>
              <FolderOpen className="h-4 w-4" /> Keep it somewhere else
            </Button>
          </div>
        )}
      </div>
      {error && (
        <div className="mt-2">
          <Alert variant="error" onDismiss={() => setError('')}>
            {error}
          </Alert>
        </div>
      )}
      <ul className="mt-2 space-y-1 text-sm">
        {found.locations.map((place) => (
          <li key={place.node + place.label} className="flex items-start gap-2">
            <span className={`mt-1.5 h-1.5 w-1.5 shrink-0 rounded-full ${place.home ? 'bg-accent' : 'bg-[color:var(--color-text-faint)]'}`} aria-hidden="true" />
            <TabLink
              to={`/documents?node=${encodeURIComponent(place.node)}`}
              className="min-w-0 break-words text-[color:var(--color-text)] underline-offset-2 hover:text-accent hover:underline"
            >
              {place.label}
            </TabLink>
          </li>
        ))}
      </ul>

      <FolderPicker
        open={picking}
        title="Keep this bill in…"
        hint="Open the case or the client, then the folder, and choose it. The bill is also kept in its other usual place."
        confirmLabel="Keep the bill here"
        startNode={found.locations[0]?.node ?? 'root'}
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
