import { useEffect, useRef, useState, type ReactNode } from 'react'
import { Camera, ChevronDown, Filter, RotateCcw, X, type LucideIcon } from 'lucide-react'
import { DateRangePicker } from './DateRangePicker'
import { SearchSelect } from '../ui/SearchSelect'
import { Segmented } from '../ui/Segmented'
import { RANGE_PRESETS, matchingPreset, type DateBounds } from '../../dashboards/dateRange'
import { hasPeriod } from '../../dashboards/useDashboard'
import type { DashboardFilterKey, DashboardFilters, FilterChip } from '../../types'

export type DockOption = { id: string; label: string }

/** One dropdown inside a group: the filter it sets, what to call "no filter", and its choices. */
export type DockField = { key: DashboardFilterKey; label: string; all: string; options?: DockOption[] }

/** Filters that belong together (everything about the client, everything about the work) behind one button. */
export type DockGroup = { id: string; label: string; icon: LucideIcon; fields: DockField[] }

/** The few windows people reach for every day. The full list, and exact dates, are in the picker beside them. */
const QUICK: { id: string; label: string; title: string }[] = [
  { id: '3m', label: '3M', title: 'Last 3 months' },
  { id: '6m', label: '6M', title: 'Last 6 months' },
  { id: '12m', label: '12M', title: 'Last 12 months' },
  { id: 'this_fy', label: 'This FY', title: 'This financial year' },
  { id: 'all', label: 'All', title: 'All time' },
]

function useDismiss(open: boolean, close: () => void) {
  const root = useRef<HTMLDivElement>(null)
  useEffect(() => {
    if (!open) return
    const onPointer = (event: MouseEvent) => {
      if (root.current && !root.current.contains(event.target as Node)) close()
    }
    const onKey = (event: KeyboardEvent) => {
      if (event.key === 'Escape') close()
    }
    document.addEventListener('mousedown', onPointer)
    document.addEventListener('keydown', onKey)
    return () => {
      document.removeEventListener('mousedown', onPointer)
      document.removeEventListener('keydown', onKey)
    }
  }, [open, close])
  return root
}

function GroupButton({
  group,
  filters,
  onSet,
}: {
  group: DockGroup
  filters: DashboardFilters
  onSet: (key: DashboardFilterKey, value?: string | null) => void
}) {
  const [open, setOpen] = useState(false)
  const [flip, setFlip] = useState(false)
  const root = useDismiss(open, () => setOpen(false))
  const fields = group.fields.filter((field) => (field.options?.length ?? 0) > 0 || filters[field.key])
  if (!fields.length) return null

  const active = fields.filter((field) => filters[field.key])
  const first = active[0]
  const firstLabel = first ? (first.options?.find((option) => option.id === filters[first.key])?.label ?? filters[first.key]) : ''
  const Icon = group.icon

  return (
    <div ref={root} className="relative">
      <button
        type="button"
        onClick={() => {
          // Open towards the side with room, so the panel is never cut off by the edge of the window.
          const box = root.current?.getBoundingClientRect()
          if (box) setFlip(box.left + 400 > window.innerWidth - 16)
          setOpen((value) => !value)
        }}
        aria-expanded={open}
        aria-haspopup="dialog"
        className={`interactive inline-flex h-9 max-w-full items-center gap-2 rounded-lg border px-3 text-sm font-medium ${
          active.length
            ? 'border-transparent bg-accent-dim text-accent'
            : 'border-[color:var(--color-border)] bg-surface text-[color:var(--color-text)] hover:border-[color:var(--color-border-strong)]'
        }`}
      >
        <Icon className="h-4 w-4 shrink-0" aria-hidden="true" />
        <span>{group.label}</span>
        {active.length > 0 && (
          <span className="flex min-w-0 items-center gap-1.5">
            <span className="hidden max-w-[9rem] truncate font-semibold sm:inline">{firstLabel}</span>
            {active.length > 1 && (
              <span className="rounded-full bg-accent px-1.5 text-[10px] font-bold leading-4 text-on-primary">+{active.length - 1}</span>
            )}
          </span>
        )}
        <ChevronDown className={`h-3.5 w-3.5 shrink-0 opacity-60 transition-transform ${open ? 'rotate-180' : ''}`} aria-hidden="true" />
      </button>

      {open && (
        <div
          role="dialog"
          aria-label={`${group.label} filters`}
          className={`overlay pop-in absolute top-full z-30 mt-2 w-[min(88vw,25rem)] ${flip ? 'right-0' : 'left-0'} rounded-xl border border-[color:var(--color-border)] p-4 shadow-overlay`}
          // Opaque: over the brief's text a see-through panel is hard to read.
          style={{ background: 'var(--orion-surface)' }}
        >
          <div className="mb-3 flex items-center justify-between">
            <p className="eyebrow">{group.label}</p>
            {active.length > 0 && (
              <button
                type="button"
                onClick={() => active.forEach((field) => onSet(field.key, null))}
                className="text-xs font-medium text-accent hover:underline"
              >
                Clear {group.label.toLowerCase()}
              </button>
            )}
          </div>
          <div className="grid gap-3 sm:grid-cols-2">
            {fields.map((field) => (
              <label key={field.key} className="block min-w-0">
                <span className="mb-1 block text-[11px] font-medium text-[color:var(--color-text-muted)]">{field.label}</span>
                <SearchSelect
                  value={filters[field.key] ?? ''}
                  options={field.options ?? []}
                  onChange={(value) => onSet(field.key, value)}
                  placeholder={field.all}
                  emptyLabel={field.all}
                />
              </label>
            ))}
          </div>
        </div>
      )}
    </div>
  )
}

/**
 * One bar for everything that narrows a dashboard. The period is the choice people make most, so its common windows
 * are always on screen; the rest are grouped by what they are about (the client, the work), each behind one button
 * that says what is selected. Chart clicks show up underneath as chips that can be taken off one by one.
 */
export function FilterDock({
  filters,
  bounds,
  years,
  groups,
  chips,
  busy,
  timeApplies = true,
  timeNote,
  answeredYear,
  onPeriod,
  onYear,
  onSet,
  onRemoveChip,
  onReset,
}: {
  filters: DashboardFilters
  bounds: DateBounds
  years?: DockOption[]
  groups: DockGroup[]
  chips: FilterChip[]
  busy: boolean
  /** False on a page of closing balances, where the period means nothing; `timeNote` says so instead. */
  timeApplies?: boolean
  timeNote?: ReactNode
  /** The financial year that "no period chosen" turned into, to name it in the year box. */
  answeredYear?: string
  onPeriod: (from?: string, to?: string) => void
  onYear: (fy?: string | null) => void
  onSet: (key: DashboardFilterKey, value?: string | null) => void
  onRemoveChip: (key: DashboardFilterKey) => void
  onReset: () => void
}) {
  const preset = filters.fy ? undefined : matchingPreset(filters.from, filters.to, bounds)
  // With no period chosen the dashboard shows the financial year we are in; "All" is chosen by name.
  const everyYear = filters.fy === 'all'
  const byDefault = !hasPeriod(filters)
  const quickValue = everyYear ? 'all' : byDefault ? 'this_fy' : preset && QUICK.some((item) => item.id === preset.id) ? preset.id : ''
  const yearValue = everyYear ? 'all' : (filters.fy ?? (byDefault ? (answeredYear ?? '') : ''))
  const yearOptions = [{ id: 'all', label: 'All years' }, ...(years ?? [])]
  const quick = QUICK.map((item) => ({ id: item.id, label: item.label }))
  const shownChips = chips.filter((chip) => chip.key !== 'from' && chip.key !== 'to' && chip.key !== 'fy')
  const anyActive = Object.keys(filters).length > 0

  return (
    <div className="panel relative lg:sticky lg:top-0 lg:z-20">
      <div className="flex flex-wrap items-center gap-x-3 gap-y-2 p-2.5">
        {timeApplies ? (
          <div className="flex flex-wrap items-center gap-2">
            <Segmented
              label="Period"
              value={quickValue}
              options={quick}
              onChange={(id) => {
                if (id === 'all') return onYear('all')
                if (id === 'this_fy') return onYear(null)
                const found = RANGE_PRESETS.find((item) => item.id === id)
                if (!found) return
                const range = found.range(new Date(), bounds)
                onPeriod(range.from, range.to)
              }}
            />
            <div className="w-[13.5rem] max-w-full">
              <DateRangePicker
                variant="field"
                exact
                idleLabel={(filters.fy && !everyYear) || byDefault ? 'Pick exact dates' : undefined}
                from={filters.from}
                to={filters.to}
                bounds={bounds}
                onChange={onPeriod}
              />
            </div>
            {(years?.length ?? 0) > 0 && (
              <div className="w-36">
                <SearchSelect
                  value={yearValue}
                  options={yearOptions}
                  onChange={(value) => onYear(value || null)}
                  placeholder="Financial year"
                  allowEmpty={false}
                />
              </div>
            )}
          </div>
        ) : (
          <p className="flex min-w-0 items-center gap-2 px-1 text-sm text-[color:var(--color-text-muted)]">
            <Camera className="h-4 w-4 shrink-0 text-accent" aria-hidden="true" />
            <span>{timeNote}</span>
          </p>
        )}

        {groups.length > 0 && <span className="hidden h-6 w-px bg-[color:var(--color-border)] sm:block" aria-hidden="true" />}

        {groups.map((group) => (
          <GroupButton key={group.id} group={group} filters={filters} onSet={onSet} />
        ))}

        {anyActive && (
          <button
            type="button"
            onClick={onReset}
            className="interactive ml-auto inline-flex h-9 items-center gap-1.5 rounded-lg px-2.5 text-xs font-medium text-[color:var(--color-text-muted)] hover:bg-muted hover:text-[color:var(--color-text)]"
          >
            <RotateCcw className="h-3.5 w-3.5" aria-hidden="true" />
            Reset
          </button>
        )}
      </div>

      {shownChips.length > 0 && (
        <div className="flex flex-wrap items-center gap-1.5 border-t border-[color:var(--color-border)] px-2.5 py-2">
          <span className="flex items-center gap-1.5 pr-1 text-[11px] font-medium text-[color:var(--color-text-faint)]">
            <Filter className="h-3 w-3" aria-hidden="true" />
            Focused on
          </span>
          {shownChips.map((chip) => (
            <button
              key={chip.key}
              type="button"
              onClick={() => onRemoveChip(chip.key)}
              title={`Remove ${chip.label}: ${chip.display}`}
              className="interactive group flex items-center gap-1.5 rounded-full bg-accent-dim py-1 pl-2.5 pr-1.5 text-xs text-accent hover:opacity-80"
            >
              <span className="opacity-70">{chip.label}</span>
              <span className="max-w-[180px] truncate font-semibold">{chip.display}</span>
              <X className="h-3 w-3" aria-hidden="true" />
            </button>
          ))}
        </div>
      )}

      {busy && (
        <span className="pointer-events-none absolute inset-x-3 bottom-0 h-0.5 overflow-hidden rounded-full" role="status" aria-label="Recalculating">
          <span className="dock-progress block h-full w-1/3 rounded-full bg-accent" />
        </span>
      )}
    </div>
  )
}
