import { useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import { ArrowRight, Inbox, Search, ShieldCheck, UserCheck, UserX, Users } from 'lucide-react'
import { IconTile } from '../../lumen/IconTile'
import { UserAvatar } from '../UserAvatar'
import type { AppUser, SignupRequest } from '../../types'

/** What a person may use, in words, from the flags on their account. The first four are shown on their card, the rest are counted. */
const AREAS: [keyof AppUser, string][] = [
  ['orion_dashboard_access', 'Dashboards'],
  ['ods_access', 'Orion data'],
  ['billing_access', 'Billing'],
  ['bank_access', 'Bank'],
  ['documents_access', 'Documents'],
  ['letterhead_access', 'Letterhead'],
  ['tenders_access', 'Tenders'],
  ['attendance_access', 'Attendance'],
  ['tally_access', 'Tally'],
  ['tally_dashboard_access', 'Tally dashboards'],
  ['etl_access', 'ETL'],
  ['ai_access', 'AI Copilot'],
]

const ROLE_HUE: Record<string, string> = { admin: 'coral', editor: 'teal', viewer: 'indigo' }

type Show = 'all' | 'active' | 'disabled' | 'admins'

/** How long ago, in a few words ("today", "3 days ago"). */
function ago(value: string): string {
  const days = Math.floor((Date.now() - new Date(value).getTime()) / 86_400_000)
  if (!Number.isFinite(days) || days <= 0) return 'today'
  if (days === 1) return 'yesterday'
  if (days < 30) return `${days} days ago`
  return new Date(value).toLocaleDateString([], { day: 'numeric', month: 'short', year: 'numeric' })
}

function Count({ label, value, hue, hint, onClick }: { label: string; value: number; hue: string; hint?: string; onClick?: () => void }) {
  const body = (
    <>
      <p className="t-caption font-semibold text-[color:var(--color-text-muted)]">{label}</p>
      <p className="lumen-figure font-display font-semibold tabular-nums">{value}</p>
      {hint && <p className="t-caption text-[color:var(--color-text-faint)]">{hint}</p>}
    </>
  )
  const style = { '--hue': `var(--lumen-${hue})` } as React.CSSProperties
  const cls = 'panel lumen-kpi relative flex flex-col gap-1 overflow-hidden !p-5 text-left'
  return onClick ? (
    <button type="button" style={style} onClick={onClick} className={`${cls} interactive`}>
      {body}
    </button>
  ) : (
    <div style={style} className={cls}>
      {body}
    </div>
  )
}

/**
 * Everyone with an account, as people rather than rows: how many there are and how many are waiting to be let in, a search, one-tap filters, and a card for
 * each person with their role, whether they are active, and what they can reach. Opening a card is how a person is managed.
 */
export function PeopleDirectory({ users, pending, onManage, onRequests }: { users: AppUser[]; pending: number; onManage: (id: number) => void; onRequests: () => void }) {
  const [query, setQuery] = useState('')
  const [show, setShow] = useState<Show>('all')
  const needle = query.trim().toLowerCase()
  const counts = useMemo(
    () => ({ all: users.length, active: users.filter((u) => u.is_active).length, disabled: users.filter((u) => !u.is_active).length, admins: users.filter((u) => u.role === 'admin').length }),
    [users],
  )
  const shown = useMemo(
    () =>
      users
        .filter((u) => (show === 'active' ? u.is_active : show === 'disabled' ? !u.is_active : show === 'admins' ? u.role === 'admin' : true))
        .filter((u) => !needle || `${u.display_name} ${u.username} ${u.email ?? ''}`.toLowerCase().includes(needle))
        .sort((a, b) => Number(b.is_active) - Number(a.is_active) || a.display_name.localeCompare(b.display_name)),
    [users, show, needle],
  )

  const chip = (id: Show, label: string, n: number) => (
    <button
      key={id}
      type="button"
      aria-pressed={show === id}
      onClick={() => setShow(id)}
      className={`interactive rounded-full border px-3.5 py-1.5 text-sm font-semibold ${show === id ? 'border-transparent text-on-primary [background-image:var(--orion-primary-fill)] shadow-card' : 'border-[color:var(--color-border)] text-[color:var(--color-text-muted)] hover:bg-muted'}`}
    >
      {label} <span className="opacity-80">{n}</span>
    </button>
  )

  return (
    <div className="space-y-5">
      <div className="lumen-kpi-grid grid grid-cols-2 gap-3 lg:grid-cols-4">
        <Count label="People" value={counts.all} hue="indigo" hint="with an account" />
        <Count label="Active" value={counts.active} hue="green" hint={counts.disabled ? `${counts.disabled} disabled` : 'nobody disabled'} />
        <Count label="Administrators" value={counts.admins} hue="coral" hint="can change anything" />
        <Count label="Waiting to be let in" value={pending} hue={pending ? 'amber' : 'teal'} hint={pending ? 'open the requests' : 'nobody is waiting'} onClick={pending ? onRequests : undefined} />
      </div>

      <div className="flex flex-wrap items-center gap-3">
        <div className="relative min-w-[16rem] flex-1">
          <Search className="pointer-events-none absolute left-3.5 top-1/2 h-4 w-4 -translate-y-1/2 text-[color:var(--color-text-faint)]" aria-hidden="true" />
          <input
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            placeholder="Search by name, username or email"
            aria-label="Search people"
            className="w-full rounded-2xl border border-transparent bg-muted py-2.5 pl-10 pr-3 text-sm outline-none placeholder:text-[color:var(--color-text-faint)] focus:border-accent"
          />
        </div>
        <div role="group" aria-label="Show" className="flex flex-wrap gap-2">
          {chip('all', 'Everyone', counts.all)}
          {chip('active', 'Active', counts.active)}
          {counts.disabled > 0 && chip('disabled', 'Disabled', counts.disabled)}
          {chip('admins', 'Administrators', counts.admins)}
        </div>
      </div>

      {shown.length === 0 ? (
        <p className="panel !p-8 text-center text-sm text-[color:var(--color-text-muted)]">No one matches.</p>
      ) : (
        <ul className="grid gap-3 md:grid-cols-2 xl:grid-cols-3" aria-label="People">
          {shown.map((person) => {
            const areas = AREAS.filter(([key]) => Boolean(person[key])).map(([, label]) => label)
            return (
              <li key={person.id} className={`panel flex flex-col gap-3 !p-4 ${person.is_active ? '' : 'opacity-70'}`}>
                <div className="flex items-start gap-3">
                  <UserAvatar user={person} size="xl" />
                  <div className="min-w-0 flex-1">
                    <p className="font-display truncate text-base font-semibold">{person.display_name}</p>
                    <p className="t-caption truncate text-[color:var(--color-text-muted)]">@{person.username}</p>
                    <p className="t-caption mt-0.5 truncate text-[color:var(--color-text-faint)]">{person.email || 'No email'}</p>
                  </div>
                  <span className="flex flex-col items-end gap-1.5">
                    <span style={{ '--hue': `var(--lumen-${ROLE_HUE[person.role] ?? 'indigo'})` } as React.CSSProperties} className="lumen-chip rounded-full px-2.5 py-0.5 text-xs font-bold capitalize">
                      {person.role}
                    </span>
                    <span className={`inline-flex items-center gap-1 text-xs font-semibold ${person.is_active ? 'text-positive' : 'text-[color:var(--color-text-faint)]'}`}>
                      {person.is_active ? <UserCheck className="h-3.5 w-3.5" aria-hidden="true" /> : <UserX className="h-3.5 w-3.5" aria-hidden="true" />}
                      {person.is_active ? 'Active' : 'Disabled'}
                    </span>
                  </span>
                </div>
                <p className="flex flex-wrap gap-1.5" aria-label={`${person.display_name} can use`}>
                  {areas.length === 0 && <span className="t-caption text-[color:var(--color-text-faint)]">No areas switched on</span>}
                  {areas.slice(0, 4).map((label) => (
                    <span key={label} className="rounded-full bg-muted px-2.5 py-0.5 text-xs font-medium text-[color:var(--color-text-muted)]">
                      {label}
                    </span>
                  ))}
                  {areas.length > 4 && (
                    <span className="rounded-full bg-muted px-2.5 py-0.5 text-xs font-medium text-[color:var(--color-text-faint)]" title={areas.slice(4).join(', ')}>
                      +{areas.length - 4} more
                    </span>
                  )}
                </p>
                <div className="mt-auto flex items-center justify-between gap-2 pt-1">
                  <button type="button" onClick={() => onManage(person.id)} className="btn-primary interactive inline-flex h-9 items-center gap-2 rounded-full px-4 text-sm font-semibold">
                    <ShieldCheck className="h-4 w-4" aria-hidden="true" /> Manage
                  </button>
                  <Link to={`/admin/users/${person.id}`} className="inline-flex items-center gap-1 text-sm font-semibold text-accent hover:underline">
                    Account page <ArrowRight className="h-3.5 w-3.5" aria-hidden="true" />
                  </Link>
                </div>
              </li>
            )
          })}
        </ul>
      )}
    </div>
  )
}

/** The people waiting to be let in, as cards you open: who they are, how to reach them and how long ago they asked. */
export function RequestCards({ requests, selectedId, onSelect }: { requests: SignupRequest[]; selectedId: number | null; onSelect: (id: number) => void }) {
  if (requests.length === 0) {
    return (
      <div className="panel flex flex-col items-center gap-2 !p-10 text-center">
        <IconTile icon={Inbox} hue="teal" className="h-10 w-10" />
        <p className="font-display text-lg font-semibold">Nobody is waiting</p>
        <p className="t-small max-w-sm text-[color:var(--color-text-muted)]">When someone asks for an account from the sign-in page, their request appears here to be approved or turned down.</p>
      </div>
    )
  }
  return (
    <ul className="grid gap-3 md:grid-cols-2 xl:grid-cols-3" aria-label="Account requests">
      {requests.map((request) => (
        <li key={request.id}>
          <button
            type="button"
            onClick={() => onSelect(request.id)}
            aria-pressed={selectedId === request.id}
            className={`panel interactive flex w-full items-center gap-3 !p-4 text-left ${selectedId === request.id ? 'ring-2 ring-[color:var(--color-accent)]' : ''}`}
          >
            <span className="grid h-12 w-12 shrink-0 place-items-center rounded-2xl bg-warning-dim text-lg font-bold text-warning" aria-hidden="true">
              {request.display_name.trim()[0]?.toUpperCase() ?? '?'}
            </span>
            <span className="min-w-0 flex-1">
              <span className="font-display block truncate text-base font-semibold">{request.display_name}</span>
              <span className="t-caption block truncate text-[color:var(--color-text-muted)]">@{request.username} · {request.email}</span>
              <span className="t-caption block text-[color:var(--color-text-faint)]">Asked {ago(request.requested_timestamp)}</span>
            </span>
            <Users className="h-4 w-4 shrink-0 text-[color:var(--color-text-faint)]" aria-hidden="true" />
          </button>
        </li>
      ))}
    </ul>
  )
}
