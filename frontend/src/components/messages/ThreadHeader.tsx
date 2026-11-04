import { useEffect, useRef, useState } from 'react'
import { Link } from 'react-router-dom'
import { Archive, BellOff, Bell, ChevronLeft, MoreVertical, Phone, Pin, PinOff, Search, Trash2, ArchiveRestore, PanelRight, Video } from 'lucide-react'
import { UserAvatar } from '../UserAvatar'
import { GroupAvatar } from './GroupAvatar'
import type { ChatPeer, ChatSettings } from '../../types'

type Props = {
  peer: ChatPeer | null
  online: boolean
  typing: boolean
  /** A new conversation that has no messages yet. */
  fresh: boolean
  settings: ChatSettings | null
  searchOpen: boolean
  panelOpen: boolean
  onToggleSearch: () => void
  onTogglePanel: () => void
  onSettings: (changes: Partial<ChatSettings>) => void
  onDelete: () => void
  /** Ring this person. Absent for a conversation that has no messages yet, and for a group. */
  onCall?: (kind: 'voice' | 'video') => void
  /** Set for a group: its name, how many people, how many are around, and who is typing. */
  group?: { title: string; count: number; around: number; typing: string[] }
}

function Item({ icon, label, onClick, danger = false }: { icon: React.ReactNode; label: string; onClick: () => void; danger?: boolean }) {
  return (
    <button
      type="button"
      role="menuitem"
      onClick={onClick}
      className={`interactive flex w-full items-center gap-2.5 rounded-lg px-2.5 py-2 text-left text-sm ${
        danger ? 'text-negative hover:bg-negative-dim' : 'hover:bg-muted'
      }`}
    >
      <span className="opacity-75" aria-hidden="true">
        {icon}
      </span>
      {label}
    </button>
  )
}

/** Who this conversation is with, whether they are around, and what can be done to the conversation as a whole. */
export function ThreadHeader({ peer, online, typing, fresh, settings, searchOpen, panelOpen, onToggleSearch, onTogglePanel, onSettings, onDelete, onCall, group }: Props) {
  const [menu, setMenu] = useState(false)
  const box = useRef<HTMLDivElement>(null)

  useEffect(() => {
    if (!menu) return
    const onPointer = (event: PointerEvent) => {
      if (!box.current?.contains(event.target as Node)) setMenu(false)
    }
    const onKey = (event: KeyboardEvent) => {
      if (event.key === 'Escape') setMenu(false)
    }
    document.addEventListener('pointerdown', onPointer)
    document.addEventListener('keydown', onKey)
    return () => {
      document.removeEventListener('pointerdown', onPointer)
      document.removeEventListener('keydown', onKey)
    }
  }, [menu])

  const status = group ? (
    group.typing.length ? (
      <span className="text-accent">{group.typing.length === 1 ? `${group.typing[0]} is typing…` : `${group.typing.length} people are typing…`}</span>
    ) : (
      <span>
        {group.count} people{group.around > 0 ? ` · ${group.around} online` : ''}
      </span>
    )
  ) : typing ? (
    <span className="text-accent">typing…</span>
  ) : online ? (
    <span className="inline-flex items-center gap-1.5">
      <span className="h-1.5 w-1.5 rounded-full bg-positive" aria-hidden="true" />
      Online
    </span>
  ) : (
    <span>{fresh ? 'New conversation' : peer?.role ? peer.role.charAt(0).toUpperCase() + peer.role.slice(1) : 'Offline'}</span>
  )

  const run = (action: () => void) => () => {
    setMenu(false)
    action()
  }
  const button = 'interactive rounded-full p-2.5 max-sm:p-2 text-[color:var(--color-text-muted)] hover:bg-muted hover:text-[color:var(--color-text)]'

  return (
    <header className="chat-head flex items-center gap-1 border-b border-[color:var(--color-border)] bg-surface px-2 py-2.5 sm:gap-1.5 sm:px-4">
      <Link to="/messages" aria-label="Back to conversations" className={`${button} md:hidden`}>
        <ChevronLeft className="h-5 w-5" />
      </Link>
      <button
        type="button"
        onClick={onTogglePanel}
        aria-label={group ? 'Show group details' : 'Show contact details'}
        className="interactive flex min-w-0 flex-1 items-center gap-3.5 rounded-2xl px-2 py-1 text-left hover:bg-muted max-sm:gap-2.5 max-sm:px-1"
      >
        {group && <GroupAvatar title={group.title} size="row" className="max-sm:h-10 max-sm:w-10" />}
        {!group && peer && (
          <span className="relative shrink-0">
            <UserAvatar user={peer} size="row" className="max-sm:h-10 max-sm:w-10" />
            {online && <span className="absolute bottom-0 right-0 h-3.5 w-3.5 rounded-full border-[2.5px] border-[color:var(--color-surface)] bg-positive" aria-hidden="true" />}
          </span>
        )}
        <span className="min-w-0">
          <span className="block truncate text-base font-bold leading-tight">{group?.title || peer?.display_name || 'Message'}</span>
          <span className="block truncate text-[13px] text-[color:var(--color-text-muted)]" aria-live="polite">
            {status}
          </span>
        </span>
      </button>
      {settings?.muted && <BellOff className="h-4 w-4 text-[color:var(--color-text-faint)]" aria-label="Muted" />}
      {onCall && !fresh && (
        <>
          <button type="button" onClick={() => onCall('voice')} aria-label={`Voice call ${peer?.display_name ?? ''}`} title="Voice call" className="chat-call-button interactive inline-flex h-10 items-center gap-2 rounded-full bg-accent-dim px-3.5 text-sm max-sm:h-9 max-sm:px-2.5 font-semibold text-accent hover:bg-muted">
            <Phone className="h-[18px] w-[18px]" />
            <span className="max-lg:hidden">Call</span>
          </button>
          <button type="button" onClick={() => onCall('video')} aria-label={`Video call ${peer?.display_name ?? ''}`} title="Video call" className="chat-call-button interactive inline-flex h-10 items-center gap-2 rounded-full bg-accent-dim px-3.5 text-sm max-sm:h-9 max-sm:px-2.5 font-semibold text-accent hover:bg-muted">
            <Video className="h-[18px] w-[18px]" />
            <span className="max-lg:hidden">Video</span>
          </button>
        </>
      )}
      {!fresh && (
        <button type="button" onClick={onToggleSearch} aria-label="Search this conversation" aria-pressed={searchOpen} title="Search (Ctrl+F)" className={`${button} ${searchOpen ? 'bg-accent-dim text-accent' : ''}`}>
          <Search className="h-5 w-5" />
        </button>
      )}
      <button type="button" onClick={onTogglePanel} aria-label="Conversation details" aria-pressed={panelOpen} title="Details" className={`${button} max-md:hidden ${panelOpen ? 'bg-accent-dim text-accent' : ''}`}>
        <PanelRight className="h-5 w-5" />
      </button>
      {!fresh && settings && (
        <div ref={box} className="relative">
          <button type="button" onClick={() => setMenu((open) => !open)} aria-label="Conversation options" aria-haspopup="menu" aria-expanded={menu} className={button}>
            <MoreVertical className="h-5 w-5" />
          </button>
          {menu && (
            <div role="menu" className="overlay pop-in absolute right-0 top-full z-30 mt-1 w-56 rounded-xl border border-[color:var(--color-border)] p-1.5 shadow-overlay">
              <Item
                icon={settings.pinned ? <PinOff className="h-4 w-4" /> : <Pin className="h-4 w-4" />}
                label={settings.pinned ? 'Unpin from the top' : 'Keep at the top'}
                onClick={run(() => onSettings({ pinned: !settings.pinned }))}
              />
              <Item
                icon={settings.muted ? <Bell className="h-4 w-4" /> : <BellOff className="h-4 w-4" />}
                label={settings.muted ? 'Unmute notifications' : 'Mute notifications'}
                onClick={run(() => onSettings({ muted: !settings.muted }))}
              />
              <Item
                icon={settings.archived ? <ArchiveRestore className="h-4 w-4" /> : <Archive className="h-4 w-4" />}
                label={settings.archived ? 'Move back to chats' : 'Archive'}
                onClick={run(() => onSettings({ archived: !settings.archived }))}
              />
              {!group && <div className="my-1 h-px bg-[color:var(--color-border)]" />}
              {!group && <Item icon={<Trash2 className="h-4 w-4" />} label="Delete conversation" onClick={run(onDelete)} danger />}
            </div>
          )}
        </div>
      )}
    </header>
  )
}
