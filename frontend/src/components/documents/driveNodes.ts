/** A place in Google Drive, written as a node of the Document Center's address: `gdrive` is the top of My Drive, `gdrive:<id>` a folder. */
export const isDriveNode = (node: string): boolean => node === 'gdrive' || node.startsWith('gdrive:')

export const driveNode = (folderId: string): string => (!folderId || folderId === 'root' ? 'gdrive' : `gdrive:${folderId}`)

/** The Drive folder id a node names ("root" for the top of My Drive). */
export const driveFolderOf = (node: string): string => (node.startsWith('gdrive:') ? node.slice('gdrive:'.length) : 'root')
