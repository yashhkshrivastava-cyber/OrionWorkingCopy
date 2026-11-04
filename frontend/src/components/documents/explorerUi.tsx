import { useEffect, useRef, type ReactNode } from 'react'
import { createPortal } from 'react-dom'
import { Briefcase, Building2, Folder, FolderLock, HardDrive, Library, User, Users } from 'lucide-react'
import type { ExplorerEntry, ExplorerKind } from '../../types'
import { IconTile } from '../../lumen/IconTile'
import { useLumen } from '../../lumen/useLumen'

/** What is carried when something is dragged inside the explorer: the documents and folders, as ids. */
export const DRAG_TYPE = 'application/x-orion-items'

export interface DragPayload {
  ids: number[]
  folder_ids: number[]
}

/** Places something can be moved or kept in: a folder, or the top of the company, a case or a client. */
export const isDestination = (kind: ExplorerKind | ExplorerEntry['kind']) => ['company', 'client', 'case', 'folder', 'drive', 'driveFolder'].includes(kind)

/** What is carried when files of Google Drive are dragged: their ids there. */
export const DRIVE_DRAG_TYPE = 'application/x-orion-drive-files'

/** The icon of a folder, client, case or group of them, drawn the same in the tree, the list and the picker. */
export function EntryIcon({ kind, system, className = 'h-5 w-5' }: { kind: ExplorerEntry['kind'] | ExplorerKind; system?: boolean; className?: string }) {
  const lumen = useLumen()
  const [Icon, hue] =
    kind === 'drive'
      ? [HardDrive, 'blue']
      : kind === 'driveFolder'
        ? [Folder, 'blue']
        : kind === 'company'
          ? [Building2, 'indigo']
          : kind === 'clients'
            ? [Users, 'teal']
            : kind === 'cases'
              ? [Briefcase, 'coral']
              : kind === 'client'
                ? [User, 'teal']
                : kind === 'case'
                  ? [Briefcase, 'coral']
                  : kind === 'group' || kind === 'root'
                    ? [Library, 'violet']
                    : system
                      ? [FolderLock, 'slate']
                      : [Folder, 'amber']
  if (lumen) return <IconTile icon={Icon} hue={hue} className={className} />
  return <Icon className={className} aria-hidden="true" />
}

export interface MenuItem {
  label: string
  icon?: ReactNode
  onClick?: () => void
  disabled?: boolean
  danger?: boolean
  /** A line above this item. */
  divider?: boolean
}

/** A right-click menu, kept inside the window, closed by a click elsewhere, Escape, a scroll or choosing an item. */
export function ContextMenu({ x, y, items, onClose }: { x: number; y: number; items: MenuItem[]; onClose: () => void }) {
  const box = useRef<HTMLDivElement>(null)

  useEffect(() => {
    const close = () => onClose()
    const key = (event: KeyboardEvent) => event.key === 'Escape' && onClose()
    window.addEventListener('pointerdown', close)
    window.addEventListener('scroll', close, true)
    window.addEventListener('resize', close)
    window.addEventListener('keydown', key)
    return () => {
      window.removeEventListener('pointerdown', close)
      window.removeEventListener('scroll', close, true)
      window.removeEventListener('resize', close)
      window.removeEventListener('keydown', key)
    }
  }, [onClose])

  useEffect(() => {
    const node = box.current
    if (!node) return
    const { innerWidth, innerHeight } = window
    node.style.left = `${Math.max(8, Math.min(x, innerWidth - node.offsetWidth - 8))}px`
    node.style.top = `${Math.max(8, Math.min(y, innerHeight - node.offsetHeight - 8))}px`
    node.querySelector<HTMLButtonElement>('button:not(:disabled)')?.focus()
  }, [x, y, items])

  return createPortal(
    <div
      ref={box}
      role="menu"
      style={{ left: x, top: y }}
      onPointerDown={(event) => event.stopPropagation()}
      onContextMenu={(event) => event.preventDefault()}
      className="overlay fixed z-[90] min-w-[13rem] rounded-xl border border-[color:var(--color-border)] p-1.5 text-sm shadow-lg"
    >
      {items.map((item) => (
        <div key={item.label}>
          {item.divider && <div className="my-1 border-t border-[color:var(--color-border)]" role="separator" />}
          <button
            type="button"
            role="menuitem"
            disabled={item.disabled}
            onClick={() => {
              onClose()
              item.onClick?.()
            }}
            className={`flex w-full items-center gap-2.5 rounded-lg px-2.5 py-1.5 text-left transition-colors focus-visible:ring-2 focus-visible:ring-accent disabled:cursor-not-allowed disabled:opacity-45 enabled:hover:bg-muted ${
              item.danger ? 'text-negative' : 'text-[color:var(--color-text)]'
            }`}
          >
            <span className="h-4 w-4 shrink-0 text-[color:var(--color-text-muted)]">{item.icon}</span>
            {item.label}
          </button>
        </div>
      ))}
    </div>,
    document.body,
  )
}
