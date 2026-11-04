import { useEffect, useState } from 'react'
import { api } from '../../api/client'
import type { DriveLink } from '../../types'

/** "Also in Google Drive": the copies of this document that are in Drive, or that it was copied from. Nothing when there are none. */
export function DocumentDriveLinks({ documentId }: { documentId: number }) {
  const [links, setLinks] = useState<DriveLink[]>([])
  useEffect(() => {
    let live = true
    api
      .driveLinks('document', String(documentId))
      .then((r) => live && setLinks(r.links.filter((l) => l.state !== 'stopped')))
      .catch(() => live && setLinks([])) // no Drive on this server is not an error here
    return () => {
      live = false
    }
  }, [documentId])
  if (!links.length) return null
  return (
    <div className="rounded-xl border border-[color:var(--color-border)] px-3 py-2 text-sm">
      <p className="eyebrow">Google Drive</p>
      <ul className="mt-1 space-y-0.5 text-[color:var(--color-text)]">
        {links.map((link) => (
          <li key={link.id}>
            {link.direction === 'from_drive' ? 'Copied from Drive' : 'Copied to Drive'}
            {link.folder_label ? ` · ${link.folder_label}` : ''}
            {link.url && (
              <>
                {' · '}
                <a href={link.url} target="_blank" rel="noopener noreferrer" className="text-accent underline-offset-2 hover:underline">
                  Open in Drive
                </a>
              </>
            )}
          </li>
        ))}
      </ul>
    </div>
  )
}
