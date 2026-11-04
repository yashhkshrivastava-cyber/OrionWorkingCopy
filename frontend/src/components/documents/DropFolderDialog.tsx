import { useState } from 'react'
import { AlertTriangle, Folder, FolderX } from 'lucide-react'
import { Button } from '../ui/Button'
import { Modal } from '../ui/Modal'
import type { FolderContents } from '../../types'

function size(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${Math.round(bytes / 1024)} KB`
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`
}

const plural = (n: number, one: string, many: string) => `${n} ${n === 1 ? one : many}`

/**
 * What deleting folders together with what is in them would take away, said before anything is deleted: how many documents (and versions, and how
 * much), how many folders inside, and where the documents go (the trash, from which they can be restored). A folder that cannot be dropped says why
 * and is left alone. Nothing happens until the red button is pressed.
 */
export function DropFolderDialog({
  items,
  alsoDocuments,
  onClose,
  onConfirm,
}: {
  items: FolderContents[]
  /** Documents that were selected along with the folders: they go to the trash too. */
  alsoDocuments: number
  onClose: () => void
  onConfirm: () => Promise<void>
}) {
  const [busy, setBusy] = useState(false)
  const droppable = items.filter((item) => item.can_drop)
  const totals = droppable.reduce((sum, item) => ({ documents: sum.documents + item.documents, folders: sum.folders + 1 + item.subfolders }), { documents: 0, folders: 0 })

  const go = async () => {
    setBusy(true)
    try {
      await onConfirm()
    } finally {
      setBusy(false)
    }
  }

  return (
    <Modal
      open
      onClose={() => !busy && onClose()}
      title={droppable.length === 1 ? `Delete “${droppable[0].name}” and everything in it?` : droppable.length ? 'Delete these folders and everything in them?' : 'These folders cannot be deleted'}
      footer={
        <>
          <Button variant="secondary" onClick={onClose} disabled={busy}>
            {droppable.length ? 'Keep them' : 'Close'}
          </Button>
          {droppable.length > 0 && (
            <Button variant="danger" onClick={() => void go()} loading={busy}>
              Delete {plural(totals.folders, 'folder', 'folders')}
              {totals.documents ? ` and ${plural(totals.documents, 'document', 'documents')}` : ''}
            </Button>
          )}
        </>
      }
    >
      <div className="space-y-4 px-5 py-4">
        {items.map((item) => (
          <section key={item.folder_id} className={`rounded-xl border p-4 ${item.can_drop ? 'border-[color:var(--color-border)]' : 'border-warning/40 bg-warning-dim'}`}>
            <h3 className="flex items-center gap-2 text-sm font-bold">
              {item.can_drop ? <Folder className="h-4 w-4 text-accent" aria-hidden="true" /> : <FolderX className="h-4 w-4 text-warning" aria-hidden="true" />}
              {item.name}
            </h3>
            {item.can_drop ? (
              <div className="mt-2 space-y-2 text-sm">
                <p>
                  {item.documents + item.subfolders === 0 ? (
                    <>It has no documents in it.</>
                  ) : (
                    <>
                      You would lose <strong>{plural(item.documents, 'document', 'documents')}</strong>
                      {item.documents > 0 && (
                        <span className="text-[color:var(--color-text-muted)]">
                          {' '}
                          ({plural(item.versions, 'file version', 'file versions')}, {size(item.size_bytes)})
                        </span>
                      )}
                      {item.subfolders > 0 && (
                        <>
                          {' '}
                          and <strong>{plural(item.subfolders, 'folder', 'folders')}</strong> inside it
                        </>
                      )}
                      .
                    </>
                  )}
                </p>
                {item.document_titles.length > 0 && (
                  <ul className="list-disc space-y-0.5 pl-5 text-xs text-[color:var(--color-text-muted)]">
                    {item.document_titles.map((title) => (
                      <li key={title} className="truncate">
                        {title}
                      </li>
                    ))}
                    {item.documents > item.document_titles.length && <li className="list-none">…and {item.documents - item.document_titles.length} more</li>}
                  </ul>
                )}
                {item.subfolder_names.length > 0 && (
                  <p className="text-xs text-[color:var(--color-text-muted)]">
                    Folders inside: {item.subfolder_names.join(', ')}
                    {item.subfolders > item.subfolder_names.length ? ` and ${item.subfolders - item.subfolder_names.length} more` : ''}
                  </p>
                )}
                {item.trashed > 0 && <p className="text-xs text-[color:var(--color-text-muted)]">{plural(item.trashed, 'document is', 'documents are')} already in the trash and stay there.</p>}
              </div>
            ) : (
              <p className="mt-2 flex items-start gap-2 text-sm">
                <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0 text-warning" aria-hidden="true" />
                <span>{item.reason}</span>
              </p>
            )}
          </section>
        ))}
        {droppable.length > 0 && (
          <p className="rounded-xl bg-muted px-4 py-3 text-xs leading-relaxed text-[color:var(--color-text-muted)]">
            The documents go to the <strong>Trash</strong>, where they can be restored (to the top level of their place) until someone deletes them from there for good. The folders themselves are deleted.
            {alsoDocuments > 0 && ` The ${plural(alsoDocuments, 'document', 'documents')} you also selected go to the trash too.`}
          </p>
        )}
      </div>
    </Modal>
  )
}
