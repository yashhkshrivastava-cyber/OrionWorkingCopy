import { useEffect, useState } from 'react'
import { FolderOpen } from 'lucide-react'
import { api } from '../../api/client'
import { FolderPicker } from '../documents/FolderPicker'
import { Button } from '../ui/Button'

/**
 * Where a bill will be kept in the Document Center, before it is issued: the places Orion files it by itself (its case, and its client),
 * or the folder the person chooses. The folder is picked the way it is in a file explorer, and a new folder can be made on the way.
 */
export function BillFiling({
  caseCode,
  billDate,
  node,
  canChoose,
  onChange,
}: {
  caseCode: string
  billDate: string
  /** The folder chosen for this bill ('' is where Orion files it by itself). */
  node: string
  canChoose: boolean
  onChange: (node: string) => void
}) {
  const [places, setPlaces] = useState<{ home: boolean; label: string }[] | null>(null)
  const [problem, setProblem] = useState('')
  const [picking, setPicking] = useState(false)

  useEffect(() => {
    if (!caseCode || !billDate) {
      setPlaces(null)
      return
    }
    let stale = false
    api
      .billFilingPreview(caseCode, billDate, node || null)
      .then((found) => {
        if (stale) return
        setPlaces(found.locations)
        setProblem('')
      })
      .catch((e: Error) => {
        if (stale) return
        setPlaces(null)
        setProblem(e.message)
      })
    return () => {
      stale = true
    }
  }, [caseCode, billDate, node])

  return (
    <section className="rounded-xl border border-[color:var(--color-border)] bg-surface p-4">
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div>
          <h3 className="text-sm font-semibold text-[color:var(--color-text)]">Keep the bill in Documents</h3>
          <p className="mt-0.5 text-xs text-[color:var(--color-text-muted)]">
            {node ? 'The bill will be kept in the folder you chose.' : 'Orion files every bill by itself, under its case and its client.'}
          </p>
        </div>
        {canChoose && (
          <div className="flex gap-2">
            {node && (
              <Button variant="ghost" size="sm" onClick={() => onChange('')}>
                Use the usual place
              </Button>
            )}
            <Button variant="secondary" size="sm" onClick={() => setPicking(true)}>
              <FolderOpen className="h-4 w-4" /> {node ? 'Choose another folder' : 'Choose a folder'}
            </Button>
          </div>
        )}
      </div>
      {!caseCode ? (
        <p className="mt-2 text-xs text-[color:var(--color-text-faint)]">Choose the case to see where it will be kept.</p>
      ) : problem ? (
        <p className="mt-2 text-xs text-negative">{problem}</p>
      ) : places ? (
        <ul className="mt-2 space-y-1 text-sm">
          {places.map((place) => (
            <li key={place.label} className="flex items-start gap-2 text-[color:var(--color-text)]">
              <span className={`mt-1.5 h-1.5 w-1.5 shrink-0 rounded-full ${place.home ? 'bg-accent' : 'bg-[color:var(--color-text-faint)]'}`} aria-hidden="true" />
              <span className="min-w-0 break-words">
                {place.label}
                {place.home && places.length > 1 ? <span className="ml-1.5 text-xs text-[color:var(--color-text-muted)]">(main place)</span> : null}
              </span>
            </li>
          ))}
        </ul>
      ) : (
        <p className="mt-2 text-xs text-[color:var(--color-text-faint)]">Looking…</p>
      )}
      {!canChoose && <p className="mt-2 text-xs text-[color:var(--color-text-faint)]">Only people who may change documents can choose a folder.</p>}

      <FolderPicker
        open={picking}
        title="Keep this bill in…"
        hint="Open the case or the client, then the folder, and choose it. The bill is also kept in its other usual place."
        confirmLabel="Keep the bill here"
        startNode={node || (caseCode ? `case:${caseCode}` : 'root')}
        canMakeFolders={canChoose}
        onClose={() => setPicking(false)}
        onPick={(picked) => {
          onChange(picked)
          setPicking(false)
        }}
      />
    </section>
  )
}
