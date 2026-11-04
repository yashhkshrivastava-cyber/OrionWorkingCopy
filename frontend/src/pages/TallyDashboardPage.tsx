import { useMemo, useState } from 'react'
import { Outlet, useLocation, useNavigate, useOutletContext, Navigate } from 'react-router-dom'
import { Building2, FileText, Landmark } from 'lucide-react'
import { Link } from 'react-router-dom'
import { Alert } from '../components/ui/Alert'
import { ErrorBoundary } from '../components/ErrorBoundary'
import { DashboardBrief } from '../components/dashboard/DashboardBrief'
import { DashboardHeader } from '../components/dashboard/DashboardHeader'
import { FilterDock, type DockGroup } from '../components/dashboard/FilterDock'
import { KpiBoard } from '../components/dashboard/KpiBoard'
import { MeasureExplorer, type ExploreTarget } from '../components/dashboard/MeasureExplorer'
import { ViewTabs } from '../components/dashboard/ViewTabs'
import { DashboardSkeleton, EmptyState, ErrorState, NoMatch } from '../components/dashboard/States'
import { downloadCsv } from '../components/dashboard/csv'
import { RANGE_PRESETS, prettyDay } from '../dashboards/dateRange'
import { TALLY_DASHBOARDS, tallyDashboardByView } from '../dashboards/registry'
import { hasFullYear } from '../dashboards/compare'
import { useDashboardFilters, usePeriodControls, useTallyDashboardData } from '../dashboards/useDashboard'
import { useAuth } from '../context/AuthContext'
import type {
  Category,
  DashboardFilterKey,
  DashboardKpi,
  DashboardView,
  SeriesPoint,
  TableBlock,
} from '../types'

export type TallyDashboardContext = {
  data: DashboardView
  select: (key: DashboardFilterKey) => (value: string) => void
  active: (key: DashboardFilterKey) => string | undefined
  chip: (key: DashboardFilterKey) => string | undefined
  clear: (key: DashboardFilterKey) => () => void
  categories: (id: string) => Category[]
  series: (id: string) => SeriesPoint[]
  table: (id: string) => TableBlock
}

const EMPTY_TABLE: TableBlock = { filter_key: null, columns: [], rows: [] }

export function useTallyDashboard(): TallyDashboardContext {
  return useOutletContext<TallyDashboardContext>()
}

function viewFromPath(pathname: string): string {
  const segment = pathname.replace(/^\/dashboard\/tally\/?/, '').split('/')[0]
  return TALLY_DASHBOARDS.find((tab) => tab.path === segment)?.view ?? 'overview'
}

export function TallyDashboardPage() {
  const { user } = useAuth()
  const location = useLocation()
  const navigate = useNavigate()
  const view = viewFromPath(location.pathname)
  const tab = tallyDashboardByView(view)
  const canTally = user?.can_tally_dashboard === true
  const { filters, search, toggle, remove, reset, setRange, setPeriod, setYear, set } = useDashboardFilters()
  const { data, error, busy, retry } = useTallyDashboardData(filters)
  const period = usePeriodControls(filters, data, { setPeriod, setYear })
  const [exploring, setExploring] = useState<ExploreTarget | null>(null)

  const kpis = useMemo(
    () =>
      tab.kpiKeys
        .map((key) => (data?.kpis ?? []).find((kpi) => kpi.key === key))
        .filter((kpi): kpi is NonNullable<typeof kpi> => Boolean(kpi))
        .map(period.apply),
    [data, tab, period.apply],
  )
  const insights = useMemo(
    () => (data?.insights ?? []).filter((item) => (tab.areas as string[]).includes(item.area)),
    [data, tab],
  )

  const options = data?.meta.filter_options
  // Books balances are closing positions: only the company narrows them. Billed figures can be cut by who and what.
  const groups = useMemo<DockGroup[]>(() => {
    const companies = options?.companies ?? []
    const books: DockGroup = {
      id: 'books',
      label: 'Company',
      icon: Landmark,
      fields: [{ key: 'company', label: 'Company', all: 'All companies', options: companies.length > 1 ? companies : undefined }],
    }
    if (tab.snapshot) return [books]
    return [
      books,
      {
        id: 'client',
        label: 'Client',
        icon: Building2,
        fields: [{ key: 'client', label: 'Client', all: 'All clients', options: options?.clients }],
      },
      {
        id: 'documents',
        label: 'Documents',
        icon: FileText,
        fields: [
          { key: 'voucher_type', label: 'Document type', all: 'All types', options: options?.voucher_types },
          { key: 'income_line', label: 'Income line', all: 'All income', options: options?.income_lines },
          { key: 'cost_centre', label: 'Cost centre', all: 'All centres', options: options?.cost_centres },
        ],
      },
    ]
  }, [options, tab.snapshot])

  if (!canTally) return <Navigate to="/dashboard" replace />

  const context: TallyDashboardContext | null = data && {
    data,
    select: (key) => (value) => toggle(key, value),
    // "Every year" is not a year to highlight, and the year a dashboard opens on by default is not a pick to clear.
    active: (key) => (key === 'fy' && filters.fy === 'all' ? undefined : filters[key]),
    chip: (key) => (key === 'fy' && !filters.fy ? undefined : data.active_filters.find((entry) => entry.key === key)?.display),
    clear: (key) => () => remove(key),
    categories: (id) => data.categories[id] ?? [],
    series: (id) => data.series[id] ?? [],
    table: (id) => data.tables[id] ?? EMPTY_TABLE,
  }

  const invalid = data?.meta.invalid_filters ?? []
  const nothingMatches = Boolean(data?.meta.empty) && !tab.snapshot
  const through = data?.meta.data_through ? prettyDay(data.meta.data_through) : ''
  const timeNarrowed = period.narrowed

  const exportKpis = () => {
    if (!data) return
    downloadCsv(
      `tally-${view}-key-figures-${new Date().toISOString().slice(0, 10)}.csv`,
      ['Figure', 'Value', 'Change', 'Compared with', 'Note'],
      kpis.map((kpi) => [kpi.label, kpi.value, kpi.delta, kpi.compare ?? '', kpi.hint]),
    )
  }

  // Books balances are closing positions, so their drill-down keeps only the company.
  const exploreBase = (): Record<string, string> =>
    Object.fromEntries(
      Object.entries(period.effective).filter(([key, value]) => value && (!exploring?.snapshot || key === 'company')),
    ) as Record<string, string>

  const applyPicks = (picks: Record<string, string>) => {
    if ('fy' in picks || 'month' in picks) setRange()
    Object.entries(picks).forEach(([key, value]) => {
      if (key === 'from' || key === 'to' || key === 'ledger' || key === 'group') return
      set(key as DashboardFilterKey, value)
    })
  }

  const explore = (kpi: DashboardKpi) =>
    setExploring({ key: kpi.key, label: kpi.label, value: kpi.value, snapshot: kpi.scope === 'snapshot' })

  const compareRecent = () => {
    const range = RANGE_PRESETS.find((item) => item.id === '6m')?.range(new Date(), data?.meta.bounds ?? { min: '', max: '' })
    if (range) setPeriod(range.from, range.to)
  }

  const openTab = (path: string) => navigate({ pathname: `/dashboard/tally/${path}`, search })

  return (
    <div className="space-y-4">
      <header className="space-y-4">
        <DashboardHeader
          title={tab.title}
          subtitle={tab.subtitle}
          status={
            through ? (
              <span className="rounded-full border border-[color:var(--color-border)] bg-surface px-2.5 py-1 text-xs text-[color:var(--color-text-muted)]">
                Latest billed document <span className="font-medium text-[color:var(--color-text)]">{through}</span>
              </span>
            ) : undefined
          }
        />
        <ViewTabs tabs={TALLY_DASHBOARDS} base="/dashboard/tally" search={search} label="Tally dashboards" />
      </header>

      <FilterDock
        filters={filters}
        bounds={data?.meta.bounds ?? { min: '', max: '' }}
        years={options?.fys}
        groups={groups}
        chips={data?.active_filters ?? []}
        busy={busy && Boolean(data)}
        timeApplies={!tab.snapshot}
        timeNote={
          <>
            <span className="font-medium text-[color:var(--color-text)]">Balances at the last warehouse load.</span> Period, financial year
            and billing filters do not change these figures.
          </>
        }
        answeredYear={period.answeredYear}
        onPeriod={period.onPeriod}
        onYear={setYear}
        onSet={set}
        onRemoveChip={remove}
        onReset={reset}
      />

      {invalid.length > 0 && (
        <Alert variant="info">
          {invalid.length === 1 ? 'One filter was' : `${invalid.length} filters were`} adjusted or ignored:{' '}
          {invalid.map((item) => `${item.key} (${item.reason})`).join(' ')}
        </Alert>
      )}

      {error && <ErrorState message={error} onRetry={retry} />}

      {!data ? (
        error ? null : <DashboardSkeleton kpis={tab.kpiKeys.length} />
      ) : nothingMatches && !data.meta.bounds.min ? (
        <EmptyState
          title="Nothing has been loaded from Tally yet"
          action={
            <Link to="/data/tally" className="interactive rounded-lg bg-primary px-3 py-1.5 text-sm font-semibold text-on-primary hover:opacity-90">
              Open Tally data
            </Link>
          }
        >
          The dashboards read a copy of the Tally books that Orion keeps. Once a load has run they fill in by themselves, and no filter will change what is shown until then.
        </EmptyState>
      ) : nothingMatches ? (
        <NoMatch
          title="No billed documents match these filters"
          onWiden={timeNarrowed ? period.onWiden : undefined}
          onReset={reset}
          covers={`Billed data runs from ${data.meta.bounds.min ? prettyDay(data.meta.bounds.min) : 'the first load'} to ${through || 'today'}.`}
        >
          Try a wider period or remove a client, document type or income filter.
        </NoMatch>
      ) : (
        <div className={`space-y-5 transition-opacity duration-200 ${busy ? 'opacity-60' : 'opacity-100'}`} aria-busy={busy}>
          <DashboardBrief
            kpis={kpis}
            insights={insights}
            range={tab.snapshot ? undefined : data.meta.range}
            comparison={tab.snapshot ? undefined : period.changeLabel}
            tabLabel={(target) => TALLY_DASHBOARDS.find((t) => t.path === target)?.label}
            onFilter={(key, value) => set(key, value)}
            onOpenTab={openTab}
            onExplore={explore}
            onCompare={compareRecent}
          />

          <KpiBoard
            kpis={kpis}
            caption={
              <>
                {data.meta.range && !tab.snapshot && <> · {data.meta.range}</>}
                {!tab.snapshot && (
                  <>
                    {' · '}
                    {period.changeLabel ? `change shown ${period.changeLabel}` : 'choose a period or financial year to see changes'}
                  </>
                )}
              </>
            }
            compare={!tab.snapshot && period.inYear && hasFullYear(kpis) ? { mode: period.mode, onChange: period.setMode } : undefined}
            onExplore={explore}
            onExport={exportKpis}
          />

          <ErrorBoundary key={view} label={`The ${tab.label} visuals could not be displayed.`}>
            <Outlet context={context} />
          </ErrorBoundary>
        </div>
      )}
      <MeasureExplorer
        source="tally"
        target={exploring}
        baseFilters={exploreBase()}
        baseChips={exploring?.snapshot ? [] : (data?.active_filters ?? [])}
        onApply={applyPicks}
        onClose={() => setExploring(null)}
      />
    </div>
  )
}
