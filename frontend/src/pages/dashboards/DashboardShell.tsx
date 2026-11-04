import { useEffect, useMemo, useRef, useState } from 'react'
import { Navigate, Outlet, useLocation, useNavigate, useOutletContext } from 'react-router-dom'
import { Briefcase, ChevronDown, Table2, UsersRound } from 'lucide-react'
import { api } from '../../api/client'
import { Alert } from '../../components/ui/Alert'
import { ErrorBoundary } from '../../components/ErrorBoundary'
import { DashboardBrief } from '../../components/dashboard/DashboardBrief'
import { DashboardHeader } from '../../components/dashboard/DashboardHeader'
import { FilterDock, type DockGroup } from '../../components/dashboard/FilterDock'
import { KpiBoard } from '../../components/dashboard/KpiBoard'
import { MeasureExplorer, type ExploreTarget } from '../../components/dashboard/MeasureExplorer'
import { RecordsDrawer } from '../../components/dashboard/RecordsDrawer'
import { DashboardSkeleton, ErrorState, NoMatch } from '../../components/dashboard/States'
import { ViewTabs } from '../../components/dashboard/ViewTabs'
import { WarehouseFreshness } from '../../components/dashboard/WarehouseFreshness'
import { downloadCsv } from '../../components/dashboard/csv'
import { useAuth } from '../../context/AuthContext'
import { RANGE_PRESETS, prettyDay } from '../../dashboards/dateRange'
import { DASHBOARDS, dashboardByView } from '../../dashboards/registry'
import { hasFullYear } from '../../dashboards/compare'
import { useDashboardData, useDashboardFilters, usePeriodControls } from '../../dashboards/useDashboard'
import { openInNewTab } from '../../navigation/openInNewTab'
import type {
  Category,
  DashboardFilterKey,
  DashboardKpi,
  DashboardView,
  RecordSetInfo,
  SeriesPoint,
  TableBlock,
} from '../../types'

/** What each dashboard page receives from the shell. */
export type DashboardContext = {
  data: DashboardView
  /** Toggle a filter; picking the active value clears it. */
  select: (key: DashboardFilterKey) => (value: string) => void
  /** The value currently selected for a dimension, for dimming visuals. */
  active: (key: DashboardFilterKey) => string | undefined
  /** Readable name of the active selection, shown on the chart that owns it. */
  chip: (key: DashboardFilterKey) => string | undefined
  clear: (key: DashboardFilterKey) => () => void
  categories: (id: string) => Category[]
  series: (id: string) => SeriesPoint[]
  table: (id: string) => TableBlock
  /** Open the rows behind a figure. Hands a chart its "Records" button. */
  openRecords: (dataset: string, label?: string) => void
  /** Props for ChartCard's `records` button. */
  records: (dataset: string, label: string) => { dataset: string; label: string; open: (dataset: string, label?: string) => void }
  /** Open a bill (or any record) from a row. */
  go: (path: string) => void
}

const EMPTY_TABLE: TableBlock = { filter_key: null, columns: [], rows: [] }

export function useDashboard(): DashboardContext {
  return useOutletContext<DashboardContext>()
}

function viewFromPath(pathname: string): string {
  const segment = pathname.replace(/^\/dashboard\/orion\/?/, '').split('/')[0]
  return DASHBOARDS.find((tab) => tab.path === segment)?.view ?? 'overview'
}

function ExploreMenu({ sets, onOpen }: { sets: RecordSetInfo[]; onOpen: (dataset: string, label: string) => void }) {
  const [open, setOpen] = useState(false)
  const root = useRef<HTMLDivElement>(null)
  useEffect(() => {
    if (!open) return
    const close = (event: MouseEvent) => {
      if (root.current && !root.current.contains(event.target as Node)) setOpen(false)
    }
    document.addEventListener('mousedown', close)
    return () => document.removeEventListener('mousedown', close)
  }, [open])
  if (!sets.length) return null
  return (
    <div ref={root} className="relative">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        aria-expanded={open}
        aria-haspopup="menu"
        className="interactive flex h-8 items-center gap-1.5 rounded-lg border border-[color:var(--color-border-strong)] bg-surface px-2.5 text-xs font-semibold text-[color:var(--color-text)] shadow-card hover:bg-surface-hover"
      >
        <Table2 className="h-3.5 w-3.5 text-accent" aria-hidden="true" />
        Explore records
        <ChevronDown className="h-3 w-3 text-[color:var(--color-text-faint)]" aria-hidden="true" />
      </button>
      {open && (
        <div role="menu" className="overlay pop-in absolute right-0 z-30 mt-1.5 w-56 overflow-hidden rounded-xl border border-[color:var(--color-border)] py-1 shadow-overlay">
          <p className="eyebrow px-3 pb-1 pt-1.5">Rows behind the figures</p>
          {sets.map((set) => (
            <button
              key={set.id}
              type="button"
              role="menuitem"
              onClick={() => {
                setOpen(false)
                onOpen(set.id, set.label)
              }}
              className="block w-full px-3 py-2 text-left text-sm text-[color:var(--color-text)] hover:bg-muted"
            >
              {set.label}
            </button>
          ))}
        </div>
      )}
    </div>
  )
}

export function DashboardShell() {
  const { user } = useAuth()
  const location = useLocation()
  const navigate = useNavigate()
  const view = viewFromPath(location.pathname)
  const tab = dashboardByView(view)
  const { filters, search, toggle, remove, reset, setRange, setPeriod, setYear, set } = useDashboardFilters()
  const { data, error, busy, retry } = useDashboardData(view, filters)
  const period = usePeriodControls(filters, data, { setPeriod, setYear })
  const [sets, setSets] = useState<RecordSetInfo[]>([])
  const [drawer, setDrawer] = useState<{ dataset: string; label: string } | null>(null)
  const [exploring, setExploring] = useState<ExploreTarget | null>(null)
  const allowed = user?.can_orion_dashboard !== false
  // The Cash tab shows the bank balance, so it is for people with Bank access only (the server refuses everyone else too).
  const tabs = useMemo(() => DASHBOARDS.filter((item) => item.view !== 'cash' || Boolean(user?.can_bank)), [user?.can_bank])

  useEffect(() => {
    if (!allowed) return
    api
      .dashboardRecordSets()
      .then((r) => setSets(r.datasets))
      .catch(() => setSets([]))
  }, [allowed])

  // This tab's own record sets lead the menu.
  const menu = useMemo(() => {
    const rank = (id: string) => {
      const i = tab.records.indexOf(id)
      return i === -1 ? 99 : i
    }
    return sets.filter((set) => !set.hidden).sort((a, b) => rank(a.id) - rank(b.id))
  }, [sets, tab])

  const kpis = useMemo(
    () =>
      tab.kpiKeys
        .map((key) => (data?.kpis ?? []).find((item) => item.key === key))
        .filter((item): item is DashboardKpi => Boolean(item))
        .map(period.apply),
    [data, tab, period.apply],
  )

  const options = data?.meta.filter_options
  const groups = useMemo<DockGroup[]>(
    () => [
      {
        id: 'client',
        label: 'Client',
        icon: UsersRound,
        fields: [
          { key: 'client', label: 'Client', all: 'All clients', options: options?.clients },
          { key: 'client_type', label: 'Client type', all: 'All types', options: options?.client_types },
          { key: 'priority', label: 'Priority', all: 'All priorities', options: options?.priorities },
          { key: 'state', label: 'State', all: 'All states', options: options?.states },
        ],
      },
      {
        id: 'work',
        label: 'Work',
        icon: Briefcase,
        fields: [
          { key: 'case', label: 'Case', all: 'All cases', options: options?.cases },
          { key: 'business_domain', label: 'Business domain', all: 'All domains', options: options?.domains },
          { key: 'capability', label: 'Capability', all: 'All capabilities', options: options?.capabilities },
        ],
      },
    ],
    [options],
  )

  // Before the early return below: a hook must run on every render. A figure that is a position today ignores the period, so its drill-down starts without it.
  const exploreBase = useMemo<Record<string, string>>(() => {
    const entries = Object.entries(period.effective).filter(([key, value]) => value && !(exploring?.snapshot && ['month', 'fy', 'from', 'to'].includes(key)))
    return Object.fromEntries(entries) as Record<string, string>
  }, [period.effective, exploring])

  if (!allowed) return <Navigate to="/dashboard" replace />
  if (view === 'cash' && !user?.can_bank) return <Navigate to="/dashboard/orion" replace />

  const openRecords = (dataset: string, label?: string) =>
    setDrawer({ dataset, label: label ?? sets.find((s) => s.id === dataset)?.label ?? 'Records' })

  const context: DashboardContext | null = data && {
    data,
    select: (key) => (value) => toggle(key, value),
    // "Every year" is not a year to highlight, and the year a dashboard opens on by default is not a pick to clear.
    active: (key) => (key === 'fy' && filters.fy === 'all' ? undefined : filters[key]),
    chip: (key) => (key === 'fy' && !filters.fy ? undefined : data.active_filters.find((entry) => entry.key === key)?.display),
    clear: (key) => () => remove(key),
    categories: (id) => data.categories[id] ?? [],
    series: (id) => data.series[id] ?? [],
    table: (id) => data.tables[id] ?? EMPTY_TABLE,
    openRecords,
    // A chart offers its records only when the signed-in user may open them.
    records: (dataset, label) => ({ dataset, label, open: sets.some((s) => s.id === dataset) ? openRecords : () => undefined }),
    // A bill (or other record) opened from a row opens in a new tab: the dashboard, its filters and its scroll stay where they were.
    go: (path) => openInNewTab(path),
  }

  // Carry what was picked in a drill-down back onto the dashboard.
  const applyPicks = (picks: Record<string, string>) => {
    if ('fy' in picks || 'month' in picks) setRange()
    Object.entries(picks).forEach(([key, value]) => {
      if (key === 'from' || key === 'to') return
      set(key as DashboardFilterKey, value)
    })
  }

  const explore = (item: DashboardKpi) =>
    setExploring({ key: item.key, label: item.label, value: item.value, snapshot: item.scope === 'snapshot' })

  const invalid = data?.meta.invalid_filters ?? []
  const nothingMatches = Boolean(data?.meta.empty)
  const through = data?.meta.data_through ? prettyDay(data.meta.data_through) : ''
  const timeNarrowed = period.narrowed

  const exportKpis = () => {
    if (!data) return
    downloadCsv(
      `orion-${view}-key-figures-${new Date().toISOString().slice(0, 10)}.csv`,
      ['Figure', 'Value', 'Change', 'Compared with', 'Note'],
      kpis.map((item) => [item.label, item.value, item.delta, item.compare ?? '', item.hint]),
    )
  }

  const compareRecent = () => {
    const range = RANGE_PRESETS.find((item) => item.id === '6m')?.range(new Date(), data?.meta.bounds ?? { min: '', max: '' })
    if (range) setPeriod(range.from, range.to)
  }

  const openTab = (target: string) => {
    const found = DASHBOARDS.find((t) => t.view === target)
    navigate({ pathname: found?.path ? `/dashboard/orion/${found.path}` : '/dashboard/orion', search })
  }

  return (
    <div className="space-y-4">
      <header className="space-y-4">
        <DashboardHeader
          title={tab.title}
          subtitle={tab.subtitle}
          status={
            <>
              {through && view !== 'cash' && (
                <span className="rounded-full border border-[color:var(--color-border)] bg-surface px-2.5 py-1 text-xs text-[color:var(--color-text-muted)]">
                  Latest bill <span className="font-medium text-[color:var(--color-text)]">{through}</span>
                </span>
              )}
              {view !== 'cash' && <WarehouseFreshness source="dashboard" compact />}
            </>
          }
          actions={<ExploreMenu sets={menu} onOpen={openRecords} />}
        />
        <ViewTabs tabs={tabs} base="/dashboard/orion" search={search} label="Orion dashboards" />
      </header>

      <FilterDock
        filters={filters}
        bounds={data?.meta.bounds ?? { min: '', max: '' }}
        years={options?.fys}
        groups={groups}
        chips={data?.active_filters ?? []}
        busy={busy && Boolean(data)}
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
      ) : data.meta.message ? (
        <NoMatch title="Nothing to show yet" onReset={reset}>
          {data.meta.message}
        </NoMatch>
      ) : nothingMatches ? (
        <NoMatch
          title="Nothing matches these filters"
          onWiden={timeNarrowed ? period.onWiden : undefined}
          onReset={reset}
          covers={`The warehouse holds data from ${data.meta.bounds.min ? prettyDay(data.meta.bounds.min) : 'the first load'} to ${through || 'today'}.`}
        >
          Try a wider period, or take a client, case or segment filter off.
        </NoMatch>
      ) : (
        <div className={`space-y-5 transition-opacity duration-200 ${busy ? 'opacity-60' : 'opacity-100'}`} aria-busy={busy}>
          <DashboardBrief
            kpis={kpis}
            insights={data.insights ?? []}
            range={data.meta.range}
            comparison={period.changeLabel}
            tabLabel={(target) => DASHBOARDS.find((t) => t.view === target)?.label}
            onFilter={(key, value) => set(key, value)}
            onOpenTab={openTab}
            onExplore={explore}
            onCompare={compareRecent}
          />

          <KpiBoard
            kpis={kpis}
            caption={
              <>
                {data.meta.range && <> · {data.meta.range}</>} ·{' '}
                {period.changeLabel ? `change shown ${period.changeLabel}` : 'choose a period or financial year to see changes'}
              </>
            }
            compare={period.inYear && hasFullYear(kpis) ? { mode: period.mode, onChange: period.setMode } : undefined}
            onExplore={explore}
            onExport={exportKpis}
            snapshotLabel="Position today"
            snapshotNote={
              view === 'cash'
                ? 'Where the bank stands today, read live from the Bank book. It is not set against an earlier period, and the period filters do not change it.'
                : 'Where things stand as at the last warehouse load, such as what is owed or how many cases are running. It is not set against an earlier period, and the period filters do not change it.'
            }
          />

          <ErrorBoundary key={view} label={`The ${tab.label} visuals could not be displayed.`}>
            <Outlet context={context} />
          </ErrorBoundary>
        </div>
      )}

      <MeasureExplorer
        source="orion"
        target={exploring}
        baseFilters={exploreBase}
        baseChips={exploring?.snapshot ? [] : (data?.active_filters ?? [])}
        onApply={applyPicks}
        onClose={() => setExploring(null)}
      />

      <RecordsDrawer
        dataset={drawer?.dataset ?? null}
        label={drawer?.label}
        filters={period.effective}
        chips={data?.active_filters ?? []}
        onClose={() => setDrawer(null)}
      />
    </div>
  )
}
