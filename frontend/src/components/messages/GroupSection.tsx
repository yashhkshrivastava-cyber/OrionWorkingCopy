import { useEffect, useMemo, useRef, useState } from 'react'
import { Check, MoreHorizontal, Pencil, ShieldCheck, ShieldOff, UserMinus, UserPlus, X } from 'lucide-react'
import { api } from '../../api/client'
import { Button } from '../ui/Button'
import { MultiSelect } from '../ui/MultiSelect'
import { useToast } from '../ui/Toast'
import { UserAvatar } from '../UserAvatar'
import type { ChatMember, ChatPeer, ChatThread } from '../../types'
import { GroupAvatar } from './GroupAvatar'
import { MAX_GROUP, MAX_TITLE, personLabel } from './NewGroupDialog'

/** The group's picture and name, with a way to rename it for an admin. */
export function GroupIdentity({ chat, admin }: { chat: ChatThread; admin: boolean }) {
  const toast = useToast()
  const [editing, setEditing] = useState(false)
  const [title, setTitle] = useState(chat.title ?? '')
  const [busy, setBusy] = useState(false)
  useEffect(() => setTitle(chat.title ?? ''), [chat.title])

  const save = async () => {
    const next = title.trim()
    if (!next || next === chat.title) {
      setEditing(false)
      return
    }
    setBusy(true)
    try {
      await api.renameGroup(chat.id, next)
      setEditing(false)
    } catch (err) {
      toast.show('Could not rename the group', { tone: 'error', detail: err instanceof Error ? err.message : undefined })
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="flex flex-col items-center px-4 py-5 text-center">
      <GroupAvatar title={chat.title ?? 'Group'} size="lg" />
      {editing ? (
        <form
          className="mt-3 flex w-full items-center gap-1.5"
          onSubmit={(event) => {
            event.preventDefault()
            void save()
          }}
        >
          <input
            autoFocus
            value={title}
            onChange={(event) => setTitle(event.target.value)}
            maxLength={MAX_TITLE}
            aria-label="Group name"
            className="min-w-0 flex-1 rounded-xl border border-[color:var(--color-border)] bg-[color:var(--color-bg)] px-3 py-2 text-sm outline-none focus:border-accent"
          />
          <button type="submit" disabled={busy || !title.trim()} aria-label="Save the name" className="interactive rounded-full bg-primary p-2 text-on-primary disabled:opacity-50">
            <Check className="h-4 w-4" />
          </button>
          <button type="button" onClick={() => setEditing(false)} aria-label="Cancel" className="interactive rounded-full p-2 hover:bg-muted">
            <X className="h-4 w-4" />
          </button>
        </form>
      ) : (
        <p className="mt-3 flex items-center gap-1.5 text-lg font-bold">
          {chat.title}
          {admin && (
            <button type="button" onClick={() => setEditing(true)} aria-label="Rename the group" title="Rename" className="interactive rounded-full p-1.5 text-[color:var(--color-text-muted)] hover:bg-muted">
              <Pencil className="h-3.5 w-3.5" />
            </button>
          )}
        </p>
      )}
      <p className="mt-1 text-xs text-[color:var(--color-text-muted)]">
        Group · {chat.members.length} {chat.members.length === 1 ? 'person' : 'people'}
      </p>
    </div>
  )
}

function MemberRow({ member, me, admin, online, onRole, onRemove }: { member: ChatMember; me: boolean; admin: boolean; online: boolean; onRole: (role: 'admin' | 'member') => void; onRemove: () => void }) {
  const [menu, setMenu] = useState(false)
  const box = useRef<HTMLLIElement>(null)
  useEffect(() => {
    if (!menu) return
    const close = (event: Event) => {
      if (!box.current?.contains(event.target as Node)) setMenu(false)
    }
    document.addEventListener('pointerdown', close)
    return () => document.removeEventListener('pointerdown', close)
  }, [menu])

  return (
    <li ref={box} className="relative flex items-center gap-3 rounded-xl px-2 py-1.5 hover:bg-muted">
      <span className="relative shrink-0">
        <UserAvatar user={member} size="md" />
        {online && <span className="absolute bottom-0 right-0 h-3 w-3 rounded-full border-2 border-[color:var(--color-surface)] bg-positive" aria-label="Online" />}
      </span>
      <span className="min-w-0 flex-1">
        <span className="block truncate text-sm font-semibold">
          {member.display_name}
          {me && <span className="ml-1 font-normal text-[color:var(--color-text-faint)]">(you)</span>}
        </span>
        <span className="block truncate text-xs text-[color:var(--color-text-faint)]">@{member.username}</span>
      </span>
      {member.group_role === 'admin' && <span className="rounded-full bg-accent-dim px-2 py-0.5 text-[11px] font-semibold text-accent">Admin</span>}
      {admin && !me && (
        <>
          <button type="button" onClick={() => setMenu((open) => !open)} aria-label={`Actions for ${member.display_name}`} aria-haspopup="menu" aria-expanded={menu} className="interactive rounded-full p-1.5 text-[color:var(--color-text-muted)] hover:bg-surface">
            <MoreHorizontal className="h-4 w-4" />
          </button>
          {menu && (
            <div role="menu" className="overlay pop-in absolute right-1 top-full z-30 mt-1 w-52 rounded-xl border border-[color:var(--color-border)] p-1.5 shadow-overlay">
              <button
                type="button"
                role="menuitem"
                onClick={() => {
                  setMenu(false)
                  onRole(member.group_role === 'admin' ? 'member' : 'admin')
                }}
                className="interactive flex w-full items-center gap-2.5 rounded-lg px-2.5 py-2 text-left text-sm hover:bg-muted"
              >
                {member.group_role === 'admin' ? <ShieldOff className="h-4 w-4 opacity-75" /> : <ShieldCheck className="h-4 w-4 opacity-75" />}
                {member.group_role === 'admin' ? 'Remove as admin' : 'Make admin'}
              </button>
              <button
                type="button"
                role="menuitem"
                onClick={() => {
                  setMenu(false)
                  onRemove()
                }}
                className="interactive flex w-full items-center gap-2.5 rounded-lg px-2.5 py-2 text-left text-sm text-negative hover:bg-negative-dim"
              >
                <UserMinus className="h-4 w-4" />
                Remove from group
              </button>
            </div>
          )}
        </>
      )}
    </li>
  )
}

/** Who is in the group: an admin adds, removes and promotes; anybody sees. */
export function GroupMembers({ chat, meId, directory, online, admin }: { chat: ChatThread; meId: number; directory: ChatPeer[]; online: number[]; admin: boolean }) {
  const toast = useToast()
  const [adding, setAdding] = useState(false)
  const [chosen, setChosen] = useState<string[]>([])
  const [busy, setBusy] = useState(false)
  const inGroup = useMemo(() => new Set(chat.members.map((m) => m.id)), [chat.members])
  const candidates = useMemo(() => directory.filter((p) => !inGroup.has(p.id)), [directory, inGroup])
  const byLabel = useMemo(() => new Map(candidates.map((p) => [personLabel(p), p])), [candidates])
  const sorted = useMemo(
    () => [...chat.members].sort((a, b) => Number(b.group_role === 'admin') - Number(a.group_role === 'admin') || a.display_name.localeCompare(b.display_name)),
    [chat.members],
  )

  const fail = (what: string, err: unknown) => toast.show(what, { tone: 'error', detail: err instanceof Error ? err.message : undefined })

  const add = async () => {
    const ids = chosen.map((label) => byLabel.get(label)?.id).filter((id): id is number => id !== undefined)
    if (!ids.length) return
    setBusy(true)
    try {
      await api.addGroupMembers(chat.id, ids)
      setChosen([])
      setAdding(false)
    } catch (err) {
      fail('Could not add them', err)
    } finally {
      setBusy(false)
    }
  }

  return (
    <section className="border-t border-[color:var(--color-border)] px-3 py-3" aria-label="People in the group">
      <div className="mb-2 flex items-center justify-between px-1">
        <h3 className="eyebrow">People</h3>
        {admin && candidates.length > 0 && chat.members.length < MAX_GROUP && (
          <button type="button" onClick={() => setAdding((open) => !open)} aria-expanded={adding} className="interactive inline-flex items-center gap-1.5 rounded-full bg-accent-dim px-3 py-1 text-xs font-semibold text-accent">
            <UserPlus className="h-3.5 w-3.5" aria-hidden="true" /> Add people
          </button>
        )}
      </div>
      {adding && (
        <div className="mb-3 space-y-2 rounded-xl border border-[color:var(--color-border)] p-3">
          <MultiSelect label="People to add" values={chosen} onChange={setChosen} options={candidates.map(personLabel)} noun={['person', 'people']} placeholder="Choose people to add" searchPlaceholder="Search people" max={MAX_GROUP - chat.members.length} />
          <p className="text-xs text-[color:var(--color-text-faint)]">They will be able to read everything said here, including earlier messages.</p>
          <div className="flex justify-end gap-2">
            <Button variant="secondary" size="sm" onClick={() => setAdding(false)} disabled={busy}>
              Cancel
            </Button>
            <Button size="sm" onClick={() => void add()} loading={busy} disabled={!chosen.length}>
              Add
            </Button>
          </div>
        </div>
      )}
      <ul className="space-y-0.5">
        {sorted.map((member) => (
          <MemberRow
            key={member.id}
            member={member}
            me={member.id === meId}
            admin={admin}
            online={member.online || online.includes(member.id)}
            onRole={(role) => void api.setGroupRole(chat.id, member.id, role).catch((err) => fail('Could not change that', err))}
            onRemove={() => void api.removeGroupMember(chat.id, member.id).catch((err) => fail('Could not remove them', err))}
          />
        ))}
      </ul>
    </section>
  )
}
