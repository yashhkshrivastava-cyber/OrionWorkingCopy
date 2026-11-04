/** A file about to be filed, and the folder it sits in inside what was chosen or dropped ('' when it was chosen on its own). */
export type PickedFile = { file: File; folder: string }

/** What a folder chosen or dropped from the computer holds: its files, any folders with nothing in them, and what was not read. */
export type Picked = { files: PickedFile[]; emptyFolders: string[]; hidden: number; tooMany: boolean }

/** The most files taken from one drop or choice, so a whole disk cannot be dragged in by mistake. */
export const MAX_PICKED_FILES = 1000

const TEMPORARY = /^(thumbs\.db|desktop\.ini|\.ds_store|~\$.*|.*\.tmp)$/i

/** A folder's name as the server will keep it: spaces tidied, no slashes or control characters, at most 80 characters. */
export function folderName(raw: string): string {
  // eslint-disable-next-line no-control-regex -- control characters are exactly what a folder name must not carry
  return raw.replace(/[\\/\x00-\x1f]/g, ' ').split(/\s+/).filter(Boolean).join(' ').slice(0, 80).trim()
}

function pathOf(parts: string[]): string {
  return parts.map(folderName).filter(Boolean).join('/')
}

const skipped = (name: string) => name.startsWith('.') || TEMPORARY.test(name)

/** Files from a "choose a folder" input: `webkitRelativePath` is `Top/Sub/file.pdf`. */
export function fromFileList(list: FileList | File[]): Picked {
  const files: PickedFile[] = []
  let hidden = 0
  for (const file of Array.from(list)) {
    const relative = file.webkitRelativePath || ''
    const parts = relative.split('/')
    parts.pop()
    if (skipped(file.name) || parts.some((part) => part.startsWith('.'))) {
      hidden += 1
      continue
    }
    files.push({ file, folder: pathOf(parts) })
  }
  return { files: files.slice(0, MAX_PICKED_FILES), emptyFolders: [], hidden, tooMany: files.length > MAX_PICKED_FILES }
}

const entryFile = (entry: FileSystemFileEntry) => new Promise<File>((resolve, reject) => entry.file(resolve, reject))

async function entriesOf(directory: FileSystemDirectoryEntry): Promise<FileSystemEntry[]> {
  const reader = directory.createReader()
  const all: FileSystemEntry[] = []
  // A reader gives its entries in batches (100 in Chrome) until it gives an empty one.
  for (;;) {
    const batch = await new Promise<FileSystemEntry[]>((resolve, reject) => reader.readEntries(resolve, reject))
    if (!batch.length) return all
    all.push(...batch)
  }
}

/**
 * Whatever was dropped from the computer: loose files and whole folders, folders read all the way down.
 * The dropped items are read before the first `await` (the browser empties them once the drop event has finished),
 * so call this straight from the drop handler.
 */
export async function fromDrop(transfer: DataTransfer): Promise<Picked> {
  const entries: FileSystemEntry[] = []
  for (const item of Array.from(transfer.items ?? [])) {
    if (item.kind !== 'file') continue
    const entry = item.webkitGetAsEntry?.()
    if (entry) entries.push(entry)
  }
  const fallback = Array.from(transfer.files)
  if (!entries.length) return { files: fallback.map((file) => ({ file, folder: '' })), emptyFolders: [], hidden: 0, tooMany: false }

  const out: Picked = { files: [], emptyFolders: [], hidden: 0, tooMany: false }
  const walk = async (entry: FileSystemEntry, parents: string[]): Promise<void> => {
    if (out.files.length >= MAX_PICKED_FILES) {
      out.tooMany = true
      return
    }
    if (entry.isFile) {
      if (skipped(entry.name)) {
        out.hidden += 1
        return
      }
      try {
        out.files.push({ file: await entryFile(entry as FileSystemFileEntry), folder: pathOf(parents) })
      } catch {
        out.hidden += 1 // a file the browser would not hand over (a shortcut, a file in use)
      }
      return
    }
    if (!entry.isDirectory || entry.name.startsWith('.')) return // a hidden folder (.git) is not a document folder
    const here = [...parents, entry.name]
    const inside = await entriesOf(entry as FileSystemDirectoryEntry)
    if (!inside.length) out.emptyFolders.push(pathOf(here))
    for (const child of inside) await walk(child, here)
  }
  for (const entry of entries) await walk(entry, [])
  return out
}

/** Where a picked folder's files will go, for the summary: how many files and how many distinct folders. */
export function describe(files: PickedFile[], emptyFolders: string[]): { files: number; folders: number } {
  const folders = new Set<string>(emptyFolders)
  for (const { folder } of files) {
    if (!folder) continue
    const parts = folder.split('/')
    for (let n = 1; n <= parts.length; n += 1) folders.add(parts.slice(0, n).join('/'))
  }
  return { files: files.filter((f) => f.folder).length, folders: folders.size }
}
