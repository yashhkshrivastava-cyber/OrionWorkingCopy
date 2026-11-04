import { useCallback, useEffect, useMemo, useState } from 'react'
import { Navigate, useSearchParams } from 'react-router-dom'
import { forecastApi } from '../../api/client'
import { DashboardHeader } from '../../components/dashboard/DashboardHeader'
import { ForecastBoard, type ForecastScope } from '../../components/dashboard/ForecastBoard'
import { DashboardSkeleton, ErrorState } from '../../components/dashboard/States'
import { ViewTabs } from '../../components/dashboard/ViewTabs'
import { ErrorBoundary } from '../../components/ErrorBoundary'
import { useAuth } from '../../context/AuthContext'
import { useDataRefresh } from '../../context/DataRefreshContext'
import { DASHBOARDS, TALLY_DASHBOARDS } from '../../dashboards/registry'
import type { ForecastPayload } from '../../types'

/** The choices that narrow a forecast to one slice of the business, and where the options for each come from in the answer. */
const SCOPES: Record<'orion' | 'tally', { key: string; label: string; all: string; from: string }[]> = {
  orion: [
    { key: 'client', label: 'Client', all: 'All clients', from: 'clients' },
    { key: 'business_domain', label: 'Business domain', all: 'All domains', from: 'domains' },
    { key: 'case', label: 'Case', all: 'All cases', from: 'cases' },
  ],
  tally: [
    { key: 'company', label: 'Company', all: 'All companies', from: 'companies' },
    { key: 'client', label: 'Client', all: 'All clients', from: 'clients' },
    { key: 'voucher_type', label: 'Document type', all: 'All types', from: 'voucher_types' },
    { key: 'income_line', label: 'Income line', all: 'All income', from: 'income_lines' },
    { key: 'cost_centre', label: 'Cost centre', all: 'All centres', from: 'cost_centres' },
  ],
}

/**
 * The Forecast tab of the Orion and Tally dashboards. It stands outside the dashboard shell on purpose: the shell's period filters, comparisons and key
 * figures are about a stretch of the past, and a forecast learns from all of it. What narrows it is who and what (a client, a domain, a case), kept in the
 * address like every other dashboard filter so a view can be shared.
 */
function ForecastPage({ source }: { source: 'orion' | 'tally' }) {
  const { user } = useAuth()
  const { generation } = useDataRefresh()
  const [params, setParams] = useSearchParams()
  const scopes = SCOPES[source]
  const [payload, setPayload] = useState<ForecastPayload | null>(null)
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)

  const filters = useMemo(() => {
    const found: Record<string, string> = {}
    for (const scope of scopes) {
      const value = params.get(scope.key)
      if (value) found[scope.key] = value
    }
    return found
  }, [params, scopes])
  const key = JSON.stringify(filters)

  useEffect(() => {
    let live = true
    setBusy(true)
    forecastApi
      .get(source, JSON.parse(key) as Record<string, string>)
      .then((result) => {
        if (!live) return
        setPayload(result)
        setError('')
      })
      .catch((err: Error) => live && setError(err.message))
      .finally(() => live && setBusy(false))
    return () => {
      live = false
    }
  }, [source, key, generation])

  const onFilter = useCallback(
    (name: string, value: string) => {
      const next = new URLSearchParams(params)
      if (value) next.set(name, value)
      else next.delete(name)
      setParams(next, { replace: true })
    },
    [params, setParams],
  )

  const allowed = source === 'orion' ? user?.can_orion_dashboard !== false : user?.can_tally_dashboard === true
  if (!allowed) return <Navigate to="/dashboard" replace />

  const tabs = source === 'orion' ? DASHBOARDS.filter((tab) => tab.view !== 'cash' || Boolean(user?.can_bank)) : TALLY_DASHBOARDS
  const shown: ForecastScope[] = scopes
    .map((scope) => ({ key: scope.key, label: scope.label, all: scope.all, options: payload?.options?.[scope.from] ?? [] }))
    .filter((scope) => scope.options.length > 1 || filters[scope.key])

  return (
    <div className="space-y-4">
      <header className="space-y-4">
        <DashboardHeader
          title={source === 'orion' ? 'Forecast' : 'Billing forecast'}
          subtitle={
            source === 'orion'
              ? 'Where the next month, quarter, half-year, year and three years are heading, if the business keeps its present pace.'
              : 'Where billing, as the Tally books record it, is heading over the next month, quarter, half-year, year and three years.'
          }
          canAsk={false}
        />
        <ViewTabs tabs={tabs} base={source === 'orion' ? '/dashboard/orion' : '/dashboard/tally'} search={params.toString()} label={source === 'orion' ? 'Orion dashboards' : 'Tally dashboards'} />
      </header>
      {error && <ErrorState message={error} onRetry={() => setParams(new URLSearchParams(params), { replace: true })} />}
      {!payload ? (
        error ? null : <DashboardSkeleton kpis={5} />
      ) : !payload.ready ? (
        <div className="panel p-6 text-sm text-[color:var(--color-text-muted)]">{payload.message}</div>
      ) : (
        <ErrorBoundary label="The forecast could not be displayed.">
          <ForecastBoard payload={payload} scopes={shown} filters={filters} onFilter={onFilter} busy={busy} exportName={`${source}-forecast`} />
        </ErrorBoundary>
      )}
    </div>
  )
}

export const OrionForecastPage = () => <ForecastPage source="orion" />
export const TallyForecastPage = () => <ForecastPage source="tally" />
