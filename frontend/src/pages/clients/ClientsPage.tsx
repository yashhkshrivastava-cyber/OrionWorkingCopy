import { useEffect, useMemo, useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { ChevronLeft, MapPin, Search } from 'lucide-react'
import { clientsApi } from '../../api/client'
import { inr } from '../../components/dashboard/format'
import { Alert } from '../../components/ui/Alert'
import { EmptyState, Skeleton } from '../../components/ui/EmptyState'
import { Mark } from '../../components/profile/parts'
import type { ClientDirectoryRow } from '../../types'

type Show = 'active' | 'owing' | 'all'

export { Mark as ClientMark } from '../../components/profile/parts'

/** Every client, as cards: who they are, how many cases, and (for someone who may see billing) what they owe. Opening one shows the client's page. */
export function ClientsPage() {
  const navigate = useNavigate()
  const [typed, setTyped] = useState('')
  const [search, setSearch] = useState('')
  const [show, setShow] = useState<Show>('active')
  const [clients, setClients] = useState<ClientDirectoryRow[] | null>(null)
  const [error, setError] = useState('')

  useEffect(() => {
    const timer = window.setTimeout(() => setSearch(typed.trim()), 250)
    return () => window.clearTimeout(timer)
  }, [typed])

  useEffect(() => {
    let live = true
    clientsApi
      .list(search)
      .then((r) => live && (setClients(r.clients), setError('')))
      .catch((e: Error) => live && setError(e.message))
    return () => {
      live = false
    }
  }, [search])

  const hasMoney = Boolean(clients?.some((c) => c.owed !== undefined))
  const shown = useMemo(
    () => (clients ?? []).filter((c) => (show === 'active' ? c.client_status !== 'Inactive' : show === 'owing' ? (c.owed ?? 0) > 0 : true)),
    [clients, show],
  )
  const owingCount = (clients ?? []).filter((c) => (c.owed ?? 0) > 0).length

  const chips: { id: Show; label: string }[] = [
    { id: 'active', label: 'Active' },
    ...(hasMoney ? [{ id: 'owing' as const, label: `Owing ${owingCount}` }] : []),
    { id: 'all', label: 'Everyone' },
  ]

  return (
    <div className="mx-auto max-w-6xl space-y-5 pb-6">
      <div>
        <Link to="/data/orion" className="interactive mb-2 inline-flex items-center gap-1 text-sm font-semibold text-accent hover:underline">
          <ChevronLeft className="h-4 w-4" /> Data
        </Link>
        <p className="eyebrow">Orion data</p>
        <h1 className="t-h1">Clients</h1>
        <p className="t-small mt-1 max-w-2xl text-[color:var(--color-text-muted)]">Everyone we work for. Open a client to see their cases, their people{hasMoney ? ', what has been billed and what is still owed' : ''}.</p>
      </div>

      <div className="flex flex-wrap items-center gap-3">
        <label className="relative min-w-[14rem] flex-1 sm:max-w-sm">
          <span className="sr-only">Find a client</span>
          <Search className="pointer-events-none absolute left-4 top-1/2 h-4 w-4 -translate-y-1/2 text-[color:var(--color-text-faint)]" aria-hidden="true" />
          <input value={typed} onChange={(e) => setTyped(e.target.value)} placeholder="Find a client or group" className="h-11 w-full rounded-full pr-4 text-sm" style={{ paddingLeft: '2.75rem' }} />
        </label>
        <div role="group" aria-label="Show" className="flex flex-wrap gap-2">
          {chips.map((chip) => (
            <button
              key={chip.id}
              type="button"
              aria-pressed={show === chip.id}
              onClick={() => setShow(chip.id)}
              className={`interactive rounded-full border px-3.5 py-1.5 text-sm font-semibold ${show === chip.id ? 'border-transparent text-on-primary [background-image:var(--orion-primary-fill)] shadow-card' : 'border-[color:var(--color-border)] text-[color:var(--color-text-muted)] hover:bg-muted'}`}
            >
              {chip.label}
            </button>
          ))}
        </div>
      </div>

      {error && <Alert variant="error">{error}</Alert>}
      {!clients && !error && (
        <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">
          {[0, 1, 2, 3, 4, 5].map((i) => (
            <Skeleton key={i} className="h-28" />
          ))}
        </div>
      )}
      {clients && shown.length === 0 && <EmptyState compact title="No client matches">Try another name, or choose Everyone.</EmptyState>}

      {shown.length > 0 && (
        <ul className="grid gap-3 md:grid-cols-2 xl:grid-cols-3" aria-label="Clients">
          {shown.map((client) => (
            <li key={client.client_code}>
              <button type="button" onClick={() => navigate(`/data/clients/${client.client_code}`)} className="panel interactive flex h-full w-full items-start gap-4 !p-4 text-left focus-visible:ring-2 focus-visible:ring-accent">
                <Mark name={client.client_name} />
                <span className="min-w-0 flex-1">
                  <span className="font-display block truncate text-base font-semibold">{client.client_name}</span>
                  <span className="t-caption block truncate text-[color:var(--color-text-muted)]">
                    {[client.group_name ? `Group: ${client.group_name}` : '', client.client_type].filter(Boolean).join(' · ') || client.client_code}
                  </span>
                  <span className="mt-2 flex flex-wrap items-center gap-1.5 text-[11px] font-bold">
                    {client.client_status === 'Inactive' && <span className="rounded-full bg-muted px-2 py-0.5 text-[color:var(--color-text-muted)]">Inactive</span>}
                    <span className="rounded-full bg-accent-dim px-2 py-0.5 text-[color:var(--color-text)]">
                      {client.cases} {client.cases === 1 ? 'case' : 'cases'}
                      {client.cases !== client.active_cases ? ` · ${client.active_cases} active` : ''}
                    </span>
                    {client.firm_priority && <span className="rounded-full bg-muted px-2 py-0.5 text-[color:var(--color-text-muted)]">{client.firm_priority}</span>}
                    {(client.client_location_city || client.client_location_state) && (
                      <span className="inline-flex items-center gap-0.5 font-medium text-[color:var(--color-text-faint)]">
                        <MapPin className="h-3 w-3" aria-hidden="true" /> {[client.client_location_city, client.client_location_state].filter(Boolean).join(', ')}
                      </span>
                    )}
                  </span>
                </span>
                {client.owed !== undefined && (
                  <span className="shrink-0 text-right">
                    <span className={`font-display block text-lg font-semibold tabular-nums ${client.owed > 0 ? '' : 'text-[color:var(--color-text-faint)]'}`}>{client.owed > 0 ? inr(client.owed) : '—'}</span>
                    <span className="t-caption block text-[color:var(--color-text-faint)]">{client.owed > 0 ? `owed${client.oldest_days != null ? ` · ${client.oldest_days}d` : ''}` : 'nothing owed'}</span>
                  </span>
                )}
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}
