import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import { api } from '../api/client'
import { useDataRefresh } from '../context/DataRefreshContext'
import { saveCompareMode, savedCompareMode, withCompare, type CompareMode } from './compare'
import { RANGE_PRESETS } from './dateRange'
import {
  DASHBOARD_DIMENSION_KEYS,
  DASHBOARD_FILTER_KEYS,
  type DashboardFilterKey,
  type DashboardFilters,
  type DashboardKpi,
  type DashboardView,
} from '../types'

/** The keys that choose a stretch of time. A dashboard with none of them set shows the financial year we are in. */
export const PERIOD_KEYS = ['month', 'fy', 'from', 'to'] as const

export function hasPeriod(filters: DashboardFilters): boolean {
  return PERIOD_KEYS.some((key) => Boolean(filters[key]))
}

/**
 * What is asked of the server. With no period chosen, "the current financial year": the server turns that into the
 * year (and says which in its answer). "All years" is asked for by name, so it can still be chosen.
 */
export function requestFilters(filters: DashboardFilters): DashboardFilters {
  return hasPeriod(filters) ? filters : { ...filters, fy: 'current' }
}

/**
 * The selection as everything that reads the page's figures should see it (the rows behind a figure, the drill-down,
 * the Copilot): the year the default turned into, and no financial-year filter at all for "all years".
 */
export function effectiveFilters(filters: DashboardFilters, answered?: DashboardFilters): DashboardFilters {
  if (filters.fy === 'all') {
    const { fy: _all, ...rest } = filters
    return rest
  }
  if (hasPeriod(filters)) return filters
  return answered?.fy ? { ...filters, fy: answered.fy } : filters
}

/**
 * Filters live in the query string, so a selection survives switching between
 * dashboards, a page refresh, and being pasted to a colleague.
 */
export function useDashboardFilters() {
  const [params, setParams] = useSearchParams()

  const filters = useMemo(() => {
    const active: DashboardFilters = {}
    for (const key of DASHBOARD_FILTER_KEYS) {
      const value = params.get(key)
      if (value) active[key] = value
    }
    return active
  }, [params])

  // The router's own updater does not queue: two changes made in the same click each start from the address as it was
  // drawn, so the second undoes the first (picking a period and then clearing the financial year lost the period).
  // Each change here starts from the latest one instead.
  const latest = useRef(params)
  latest.current = params

  const update = useCallback(
    (mutate: (next: URLSearchParams) => void) => {
      const next = new URLSearchParams(latest.current)
      mutate(next)
      latest.current = next
      setParams(next, { replace: true })
    },
    [setParams],
  )

  /** Clicking the value that is already selected clears it. */
  const toggle = useCallback(
    (key: DashboardFilterKey, value: string) =>
      update((next) => {
        if (next.get(key) === value) next.delete(key)
        else next.set(key, value)
      }),
    [update],
  )

  const remove = useCallback(
    (key: DashboardFilterKey) => update((next) => next.delete(key)),
    [update],
  )

  const clear = useCallback(
    () => update((next) => DASHBOARD_DIMENSION_KEYS.forEach((key) => next.delete(key))),
    [update],
  )

  /** Every filter, period included. The "Reset all" control. */
  const reset = useCallback(
    () => update((next) => DASHBOARD_FILTER_KEYS.forEach((key) => next.delete(key))),
    [update],
  )

  /** Changing the window drops a clicked month, which would otherwise sit outside it. */
  const setRange = useCallback(
    (from?: string, to?: string) =>
      update((next) => {
        next.delete('month')
        if (from) next.set('from', from)
        else next.delete('from')
        if (to) next.set('to', to)
        else next.delete('to')
      }),
    [update],
  )

  const set = useCallback(
    (key: DashboardFilterKey, value?: string | null) =>
      update((next) => {
        if (key === 'from' || key === 'to') return
        if (!value) next.delete(key)
        else next.set(key, value)
      }),
    [update],
  )

  /** A period and a financial year are one choice: picking either one replaces the other (and a clicked month). */
  const setPeriod = useCallback(
    (from?: string, to?: string) =>
      update((next) => {
        next.delete('month')
        next.delete('fy')
        if (from) next.set('from', from)
        else next.delete('from')
        if (to) next.set('to', to)
        else next.delete('to')
      }),
    [update],
  )

  const setYear = useCallback(
    (fy?: string | null) =>
      update((next) => {
        next.delete('month')
        next.delete('from')
        next.delete('to')
        if (fy) next.set('fy', fy)
        else next.delete('fy')
      }),
    [update],
  )

  return { filters, search: params.toString(), toggle, remove, clear, reset, setRange, setPeriod, setYear, set }
}

/** Loads one view, ignoring responses that arrive after a newer request. */
export function useDashboardData(view: string, filters: DashboardFilters) {
  const { generation } = useDataRefresh()
  const [data, setData] = useState<DashboardView | null>(null)
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(true)
  const [attempt, setAttempt] = useState(0)
  const requestId = useRef(0)
  const asked = requestFilters(filters)
  const key = JSON.stringify(asked)

  useEffect(() => {
    const id = ++requestId.current
    setBusy(true)
    api
      .dashboard(view, asked)
      .then((result) => {
        if (id !== requestId.current) return
        setData(result)
        setError('')
      })
      .catch((e: Error) => {
        if (id === requestId.current) setError(e.message)
      })
      .finally(() => {
        if (id === requestId.current) setBusy(false)
      })
    // filters is compared by value through `key`
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [view, key, generation, attempt])

  const retry = useCallback(() => setAttempt((n) => n + 1), [])
  return { data, error, busy, retry }
}

/** Loads billed Tally warehouse KPIs for the Tally dashboard. */
export function useTallyDashboardData(filters: DashboardFilters) {
  const { generation } = useDataRefresh()
  const [data, setData] = useState<DashboardView | null>(null)
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(true)
  const [attempt, setAttempt] = useState(0)
  const requestId = useRef(0)
  const asked = requestFilters(filters)
  const key = JSON.stringify(asked)

  useEffect(() => {
    const id = ++requestId.current
    setBusy(true)
    api
      .tallyDashboard(asked)
      .then((result) => {
        if (id !== requestId.current) return
        setData(result)
        setError('')
      })
      .catch((e: Error) => {
        if (id === requestId.current) setError(e.message)
      })
      .finally(() => {
        if (id === requestId.current) setBusy(false)
      })
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key, generation, attempt])

  const retry = useCallback(() => setAttempt((n) => n + 1), [])
  return { data, error, busy, retry }
}

/**
 * Everything about the period that the Orion and Tally dashboards do the same way: what the figures cover once the
 * default (this financial year) is resolved, what the period control does with "all time" and "this financial year",
 * and which comparison leads when a financial year in progress is set against the year before.
 */
export function usePeriodControls(
  filters: DashboardFilters,
  data: DashboardView | null | undefined,
  actions: { setPeriod: (from?: string, to?: string) => void; setYear: (fy?: string | null) => void },
) {
  const { setPeriod, setYear } = actions
  const [mode, setModeState] = useState<CompareMode>(savedCompareMode)
  const setMode = useCallback((next: CompareMode) => {
    setModeState(next)
    saveCompareMode(next)
  }, [])

  const comparison = data?.meta.comparison
  const inYear = comparison?.kind === 'fy'
  const effective = useMemo(() => effectiveFilters(filters, data?.filters), [filters, data?.filters])

  /** The period control reports a span, or none. None is "all time" and this financial year is "no choice made". */
  const onPeriod = useCallback(
    (from?: string, to?: string) => {
      if (!from && !to) {
        setYear('all')
        return
      }
      const thisYear = RANGE_PRESETS.find((item) => item.id === 'this_fy')?.range(new Date(), { min: '', max: '' })
      if (thisYear && from === thisYear.from && to === thisYear.to) {
        setYear(null)
        return
      }
      setPeriod(from, to)
    },
    [setPeriod, setYear],
  )

  const apply = useCallback((kpi: DashboardKpi) => (inYear ? withCompare(kpi, mode) : kpi), [inYear, mode])

  /** What the leading change is measured against, in words. */
  const changeLabel =
    inYear && mode === 'full' && comparison?.full ? comparison.full : comparison?.previous || (inYear ? (comparison?.full ?? '') : '')

  return {
    effective,
    /** True when something other than "every year" limits the period. */
    narrowed: hasPeriod(effective),
    onPeriod,
    onWiden: () => setYear('all'),
    mode,
    setMode,
    inYear,
    apply,
    changeLabel,
    /** The year the default turned into, for the control that names it. */
    answeredYear: hasPeriod(filters) ? undefined : data?.filters.fy,
  }
}
