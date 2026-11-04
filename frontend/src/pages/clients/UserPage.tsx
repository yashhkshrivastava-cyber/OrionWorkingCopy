import { useEffect, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { ChevronLeft, Mail, Phone, ShieldCheck } from 'lucide-react'
import { employeesApi } from '../../api/client'
import { StatTile } from '../../components/billing/StatTile'
import { Nothing, Section } from '../../components/profile/parts'
import { Alert, Badge } from '../../components/ui/Alert'
import { Button } from '../../components/ui/Button'
import { Skeleton } from '../../components/ui/EmptyState'
import { UserAvatar } from '../../components/UserAvatar'
import { formatDateTime, timeAgo } from '../../formatTime'
import type { AppUser, UserOverview } from '../../types'

type Level = 'change' | 'see' | 'none'

/** Each area an account can be given, in words, and the two flags that decide what it may do there. */
const AREAS: { label: string; hint: string; see: keyof AppUser; change?: keyof AppUser }[] = [
  { label: 'Operational data', hint: 'Clients, cases, people and money records', see: 'ods_access', change: 'ods_write' },
  { label: 'Warehouse', hint: 'The copy the dashboards read', see: 'dw_access', change: 'dw_write' },
  { label: 'Tally working copy', hint: 'The books copied from Tally', see: 'tally_access', change: 'tally_write' },
  { label: 'Tally warehouse', hint: 'Tally figures for the dashboards', see: 'tally_dw_access', change: 'tally_dw_write' },
  { label: 'Orion dashboards', hint: 'Revenue, people, pipeline and cash', see: 'orion_dashboard_access' },
  { label: 'Tally dashboards', hint: 'Billing and books from Tally', see: 'tally_dashboard_access' },
  { label: 'Billing', hint: 'Bills, receivables, TDS, GST, credit notes', see: 'billing_access', change: 'billing_write' },
  { label: 'Bank', hint: 'Balance, ledger, payroll and payables', see: 'bank_access', change: 'bank_write' },
  { label: 'Documents', hint: 'The Document Center', see: 'documents_access', change: 'documents_write' },
  { label: 'Letterhead', hint: 'Letters on the company letterhead', see: 'letterhead_access', change: 'letterhead_write' },
  { label: 'Attendance', hint: 'Registers and the pay that follows', see: 'attendance_access', change: 'attendance_write' },
  { label: 'Tenders', hint: 'GeM and MP Tenders searches', see: 'tenders_access', change: 'tenders_write' },
  { label: 'ETL', hint: 'Pipelines that load the warehouse', see: 'etl_access', change: 'etl_write' },
  { label: 'AI Copilot', hint: 'The assistant', see: 'ai_access' },
]

function levelOf(user: AppUser, area: (typeof AREAS)[number]): Level {
  if (area.change && user[area.change]) return 'change'
  return user[area.see] ? 'see' : 'none'
}

const LEVEL_STYLE: Record<Level, string> = {
  change: 'bg-accent-dim text-[color:var(--color-text)]',
  see: 'bg-muted text-[color:var(--color-text-muted)]',
  none: 'text-[color:var(--color-text-faint)]',
}

/**
 * One account on one page, for an administrator: who it is, what it can do in each part of Orion in words, when and from where it was last used and what work is on it.
 * Read only; roles, access and passwords are changed under Manage user.
 */
export function UserPage() {
  const { id = '' } = useParams()
  const [data, setData] = useState<UserOverview | null>(null)
  const [error, setError] = useState('')

  useEffect(() => {
    let live = true
    setData(null)
    employeesApi
      .account(Number(id))
      .then((r) => live && (setData(r), setError('')))
      .catch((e: Error) => live && setError(e.message))
    return () => {
      live = false
    }
  }, [id])

  const back = (
    <Link to="/admin" className="interactive inline-flex items-center gap-1 text-sm font-semibold text-accent hover:underline">
      <ChevronLeft className="h-4 w-4" /> Admin
    </Link>
  )
  if (error)
    return (
      <div className="mx-auto max-w-5xl space-y-4">
        {back}
        <Alert variant="error">{error}</Alert>
      </div>
    )
  if (!data)
    return (
      <div className="mx-auto max-w-5xl space-y-4">
        {back}
        <Skeleton className="h-32" />
        <Skeleton className="h-64" />
      </div>
    )

  const { user, sessions, tasks } = data
  const admin = user.role === 'admin'

  return (
    <div className="mx-auto max-w-5xl space-y-5 pb-6">
      {back}

      <header className="panel flex flex-wrap items-center gap-5 !p-5 sm:!p-6">
        <UserAvatar user={user} size="lg" />
        <div className="min-w-0 flex-1 basis-64">
          <p className="eyebrow normal-case">@{user.username}</p>
          <h1 className="t-h1 break-words">{user.display_name}</h1>
          <p className="mt-2 flex flex-wrap items-center gap-2 text-xs font-bold">
            <Badge variant={admin ? 'rose' : user.role === 'editor' ? 'cyan' : 'violet'}>{user.role}</Badge>
            <Badge variant={user.is_active ? 'emerald' : 'rose'}>{user.is_active ? 'Active' : 'Disabled'}</Badge>
          </p>
          <p className="mt-2 flex flex-wrap gap-x-4 gap-y-1 text-sm">
            {user.email && (
              <a href={`mailto:${user.email}`} className="inline-flex items-center gap-1 text-accent hover:underline">
                <Mail className="h-3.5 w-3.5" aria-hidden="true" /> {user.email}
              </a>
            )}
            {user.phone && (
              <a href={`tel:${user.phone}`} className="inline-flex items-center gap-1 text-accent hover:underline">
                <Phone className="h-3.5 w-3.5" aria-hidden="true" /> {user.phone}
              </a>
            )}
          </p>
        </div>
        <Link to="/admin">
          <Button variant="secondary">
            <ShieldCheck className="h-4 w-4" /> Manage in Admin
          </Button>
        </Link>
      </header>

      <div className="grid grid-cols-2 gap-3 xl:grid-cols-4">
        <StatTile label="Last used" text={sessions.last_seen ? timeAgo(sessions.last_seen) : 'Never'} hint={sessions.last_signed_in ? `Signed in ${timeAgo(sessions.last_signed_in)}` : 'Has not signed in'} />
        <StatTile label="Signed in now" text={String(sessions.active)} hint={sessions.active === 1 ? 'One device' : 'Devices'} />
        <StatTile label="Open tasks" text={String(tasks.open)} hint={tasks.in_review ? `${tasks.in_review} in review` : `${tasks.projects} ${tasks.projects === 1 ? 'project' : 'projects'}`} />
        <StatTile label="Overdue tasks" text={String(tasks.overdue)} hint={tasks.overdue ? 'Needs a nudge' : 'Nothing is late'} tone={tasks.overdue ? 'text-negative' : 'text-positive'} />
      </div>

      <div className="grid gap-5 lg:grid-cols-[minmax(0,1.2fr)_minmax(0,1fr)]">
        <Section title="What they can do" hint={admin ? 'An administrator can do everything' : 'Change means they can add and edit there; see means read only'}>
          <ul className="divide-y divide-[color:var(--color-border)]">
            {AREAS.map((area) => {
              const level = admin ? 'change' : levelOf(user, area)
              return (
                <li key={area.label} className="flex items-center gap-3 py-2 text-sm">
                  <span className="min-w-0 flex-1">
                    <span className={`block font-medium ${level === 'none' ? 'text-[color:var(--color-text-faint)]' : ''}`}>{area.label}</span>
                    <span className="t-caption block truncate text-[color:var(--color-text-faint)]">{area.hint}</span>
                  </span>
                  <span className={`shrink-0 rounded-full px-2.5 py-1 text-xs font-bold ${LEVEL_STYLE[level]}`}>{level === 'change' ? (area.change ? 'Can change' : 'Can use') : level === 'see' ? (area.change ? 'Can see' : 'Can use') : 'No access'}</span>
                </li>
              )
            })}
          </ul>
        </Section>

        <Section title="Recent sign-ins" hint="Where and when this account was used">
          {sessions.recent.length === 0 ? (
            <Nothing>This account has never signed in.</Nothing>
          ) : (
            <ul className="space-y-2">
              {sessions.recent.map((s) => (
                <li key={s.id} className="rounded-2xl border border-[color:var(--color-border)] p-3">
                  <p className="flex flex-wrap items-center gap-2 text-sm font-semibold">
                    {formatDateTime(s.signed_in)}
                    <span className={`rounded-full px-2 py-0.5 text-[11px] font-bold ${s.ended ? 'bg-muted text-[color:var(--color-text-muted)]' : 'bg-positive-dim text-positive'}`}>{s.ended ? 'Ended' : 'Signed in'}</span>
                  </p>
                  <p className="t-caption mt-0.5 truncate text-[color:var(--color-text-muted)]" title={s.device}>
                    {[s.ip, s.device].filter(Boolean).join(' · ') || 'No details kept'}
                  </p>
                  <p className="t-caption text-[color:var(--color-text-faint)]">Last seen {timeAgo(s.last_seen)}</p>
                </li>
              ))}
            </ul>
          )}
        </Section>
      </div>
    </div>
  )
}
