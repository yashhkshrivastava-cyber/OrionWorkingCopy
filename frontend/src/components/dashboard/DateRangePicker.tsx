import { useEffect, useRef, useState } from 'react'
import { CalendarRange, Check, ChevronDown } from 'lucide-react'
import {
  RANGE_PRESETS,
  exactLabel,
  matchingPreset,
  rangeLabel,
  todayIso,
  type DateBounds,
} from '../../dashboards/dateRange'

/**
 * Period control for every dashboard. Presets cover the usual windows; the two
 * date inputs are for an exact span. Changing the window lives in the URL as
 * `from` / `to` and is shared across tabs.
 *
 * `variant="pill"` is the compact chip in a page header. `variant="field"` is a form
 * control with the same box as a select, for a row of filters, so the row lines up.
 */
export function DateRangePicker({
  from,
  to,
  bounds,
  months,
  onChange,
  variant = 'pill',
  exact = false,
  idleLabel,
}: {
  from?: string
  to?: string
  bounds: DateBounds
  months?: number
  onChange: (from?: string, to?: string) => void
  variant?: 'pill' | 'field'
  /** Names the span in dates rather than by its preset, for a control that sits beside the presets. */
  exact?: boolean
  /** What to say when no dates are chosen, instead of the span the data covers. */
  idleLabel?: string
}) {
  const [open, setOpen] = useState(false)
  const [draftFrom, setDraftFrom] = useState(from ?? '')
  const [draftTo, setDraftTo] = useState(to ?? '')
  const root = useRef<HTMLDivElement>(null)
  const active = matchingPreset(from, to, bounds)
  const min = bounds.min || undefined
  const max = bounds.max || todayIso()
  const label = idleLabel && !from && !to ? idleLabel : exact ? exactLabel(from, to, bounds) : rangeLabel(from, to, bounds)

  useEffect(() => {
    setDraftFrom(from ?? '')
    setDraftTo(to ?? '')
  }, [from, to])

  useEffect(() => {
    if (!open) return
    const onPointer = (event: MouseEvent | TouchEvent) => {
      if (root.current && !root.current.contains(event.target as Node)) setOpen(false)
    }
    const onKey = (event: KeyboardEvent) => {
      if (event.key === 'Escape') setOpen(false)
    }
    document.addEventListener('mousedown', onPointer)
    document.addEventListener('touchstart', onPointer)
    document.addEventListener('keydown', onKey)
    return () => {
      document.removeEventListener('mousedown', onPointer)
      document.removeEventListener('touchstart', onPointer)
      document.removeEventListener('keydown', onKey)
    }
  }, [open])

  const apply = (nextFrom?: string, nextTo?: string) => {
    let start = nextFrom || undefined
    let end = nextTo || undefined
    if (start && end && start > end) [start, end] = [end, start]
    onChange(start, end)
    setDraftFrom(start ?? '')
    setDraftTo(end ?? '')
  }

  return (
    <div ref={root} className="relative">
      {variant === 'field' ? (
        <button
          type="button"
          onClick={() => setOpen((value) => !value)}
          aria-expanded={open}
          aria-haspopup="dialog"
          className="flex min-h-11 w-full cursor-pointer items-center justify-between gap-2 rounded-md border border-[color:var(--color-border-strong)] bg-surface px-3 py-2 text-left text-base text-[color:var(--color-text)] transition-colors hover:border-[color:var(--color-text-faint)] focus:border-accent focus:ring-[3px] focus:ring-[color:var(--orion-ring)] sm:min-h-0 sm:text-sm"
        >
          <span className="flex min-w-0 items-center gap-2">
            <CalendarRange className="h-4 w-4 shrink-0 text-[color:var(--color-text-faint)]" aria-hidden="true" />
            <span className={`truncate ${from || to ? '' : 'text-[color:var(--color-text-faint)]'}`}>{label}</span>
            {typeof months === 'number' && months > 0 && (
              <span className="shrink-0 text-xs text-[color:var(--color-text-faint)]">
                {months} {months === 1 ? 'month' : 'months'}
              </span>
            )}
          </span>
          <ChevronDown className={`h-4 w-4 shrink-0 text-[color:var(--color-text-faint)] transition-transform ${open ? 'rotate-180' : ''}`} aria-hidden="true" />
        </button>
      ) : (
        <button
          type="button"
          onClick={() => setOpen((value) => !value)}
          aria-expanded={open}
          className={`flex w-full items-center justify-center gap-1.5 rounded-full border px-3 py-2 text-xs transition-colors sm:w-auto sm:justify-start sm:py-1 ${
            from || to
              ? 'border-accent/30 bg-accent-dim text-accent hover:border-accent'
              : 'border-[color:var(--color-border)] bg-surface text-[color:var(--color-text-muted)] hover:border-[color:var(--color-border-strong)] hover:text-[color:var(--color-text)]'
          }`}
        >
          <CalendarRange className="h-3.5 w-3.5" />
          <span className="font-medium">{label}</span>
          {typeof months === 'number' && months > 0 && (
            <>
              <span className="text-[color:var(--color-border-strong)]">·</span>
              <span className={from || to ? 'text-accent' : 'text-[color:var(--color-text-faint)]'}>
                {months} {months === 1 ? 'month' : 'months'}
              </span>
            </>
          )}
        </button>
      )}

      {open && (
        <div className={`absolute z-20 mt-2 w-full rounded-xl border border-[color:var(--color-border)] overlay pop-in p-3 sm:w-[22rem] ${variant === 'field' || exact ? 'left-0' : 'left-0 right-0 sm:left-auto sm:right-0'}`} style={{ background: 'var(--orion-surface)' }}>
          <p className="px-1 text-[11px] font-medium uppercase tracking-wide text-[color:var(--color-text-faint)]">Period</p>
          <div className="mt-2 grid grid-cols-2 gap-1.5">
            {RANGE_PRESETS.map((preset) => {
              const selected = active?.id === preset.id
              return (
                <button
                  key={preset.id}
                  type="button"
                  onClick={() => {
                    const range = preset.range(new Date(), bounds)
                    apply(range.from, range.to)
                    setOpen(false)
                  }}
                  className={`flex items-center justify-between rounded-lg px-2.5 py-1.5 text-left text-xs transition-colors ${
                    selected
                      ? 'bg-primary text-on-primary'
                      : 'text-[color:var(--color-text)] hover:bg-muted'
                  }`}
                >
                  {preset.label}
                  {selected && <Check className="h-3 w-3" />}
                </button>
              )
            })}
          </div>

          <div className="mt-3 grid grid-cols-2 gap-2 border-t border-[color:var(--color-border)] pt-3">
            <label className="block">
              <span className="mb-1 block text-[11px] text-[color:var(--color-text-muted)]">From</span>
              <input
                type="date"
                value={draftFrom}
                min={min}
                max={draftTo || max}
                onChange={(event) => {
                  const value = event.target.value
                  setDraftFrom(value)
                  if (value) apply(value, draftTo || undefined)
                }}
                className="w-full rounded-lg border border-[color:var(--color-border)] bg-surface px-2 py-1.5 text-xs text-[color:var(--color-text)]"
              />
            </label>
            <label className="block">
              <span className="mb-1 block text-[11px] text-[color:var(--color-text-muted)]">To</span>
              <input
                type="date"
                value={draftTo}
                min={draftFrom || min}
                max={max}
                onChange={(event) => {
                  const value = event.target.value
                  setDraftTo(value)
                  if (value) apply(draftFrom || undefined, value)
                }}
                className="w-full rounded-lg border border-[color:var(--color-border)] bg-surface px-2 py-1.5 text-xs text-[color:var(--color-text)]"
              />
            </label>
          </div>
        </div>
      )}
    </div>
  )
}
