import type { DashboardKpi, KpiChange } from '../types'

/** What a financial year in progress is set against: the same stretch of the year before, or all of it. */
export type CompareMode = 'same' | 'full'

const KEY = 'orion.dashboard.compare'

/** The person's last choice, kept in this browser (and quietly forgotten where storage is not allowed). */
export function savedCompareMode(): CompareMode {
  try {
    return window.localStorage.getItem(KEY) === 'full' ? 'full' : 'same'
  } catch {
    return 'same'
  }
}

export function saveCompareMode(mode: CompareMode) {
  try {
    window.localStorage.setItem(KEY, mode)
  } catch {
    /* the choice only lasts until the page is closed */
  }
}

/** Whether any figure on the page can be set against both: only then is there a choice to offer. */
export function hasFullYear(kpis: DashboardKpi[]): boolean {
  return kpis.some((kpi) => kpi.scope !== 'snapshot' && Boolean(kpi.full || kpi.detail?.full_label))
}

/**
 * A figure with the chosen comparison leading and the other beside it. The server sends both for a financial year in
 * progress: the change against the same period of the year before (`delta`, with its dates in `detail.previous_*`) and
 * against the whole of it (`full`, with its dates in `detail.full_*`).
 *
 * The chosen one always leads, with its own label and its own dates, even when it cannot be worked out for this figure
 * (the year before had none of it, so there is no percentage): the card then says there is no comparison and the pop-over
 * shows what it was set against. It never quietly shows the other comparison under the chosen one's name.
 */
export function withCompare(kpi: DashboardKpi, mode: CompareMode): DashboardKpi {
  const detail = kpi.detail
  if (kpi.scope === 'snapshot' || !(kpi.full || detail?.full_label)) return kpi
  const same: KpiChange | null = kpi.delta
    ? {
        delta: kpi.delta,
        delta_type: kpi.delta_type,
        delta_pct: kpi.delta_pct,
        compare: kpi.compare ?? '',
        value: detail?.previous_value,
        range: detail?.previous_range,
      }
    : null
  const full: KpiChange | null =
    kpi.full ??
    (detail?.full_label
      ? { delta: '', delta_type: 'neutral', delta_pct: null, compare: detail.full_label, value: detail.full_value, range: detail.full_range }
      : null)

  if (mode === 'same') return { ...kpi, also: full && full.delta ? full : null }

  return {
    ...kpi,
    delta: full?.delta ?? '',
    delta_type: full?.delta_type ?? 'neutral',
    delta_pct: full?.delta_pct ?? null,
    compare: full?.delta ? full.compare : '',
    detail: {
      ...detail,
      compare: full?.compare,
      previous_value: full?.value,
      previous_range: full?.range,
    },
    also: same,
  }
}
