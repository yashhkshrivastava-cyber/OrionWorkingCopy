import { useMemo, useState } from 'react'
import { SlidersHorizontal, X } from 'lucide-react'
import { Button } from '../../components/ui/Button'
import { Checkbox, Field, Input, Select } from '../../components/ui/Field'
import { MoneyInput } from '../../components/ui/MoneyInput'
import { useLumen } from '../../lumen/useLumen'
import type { TenderBid, TenderSource } from '../../types'

const LAKH = 100000

/** What narrows the bids a search has found. Everything is on this page: the list is already loaded. */
export interface BidFilterState {
  text: string
  place: string
  closingDays: string
  minLakh: string
  maxLakh: string
  withValueOnly: boolean
  category: string
  noFeeOnly: boolean
  feeMax: string
  emdMax: string
  emd: '' | 'required' | 'none'
  guarantee: '' | 'required' | 'none'
  sort: 'closing' | 'value_desc' | 'value_asc' | 'found'
}

export const NO_FILTERS: BidFilterState = {
  text: '',
  place: '',
  closingDays: '',
  minLakh: '',
  maxLakh: '',
  withValueOnly: false,
  category: '',
  noFeeOnly: false,
  feeMax: '',
  emdMax: '',
  emd: '',
  guarantee: '',
  sort: 'closing',
}

function places(bid: TenderBid): string[] {
  const found = [...(bid.location_districts ?? [])]
  if (bid.matched_city && !found.some((place) => place.toLowerCase() === bid.matched_city?.toLowerCase())) found.push(bid.matched_city)
  return found
}

function number(text: string): number | null {
  const value = Number(text.trim())
  return text.trim() && Number.isFinite(value) ? value : null
}

/** How many filters narrow the list (the sort is not one). */
export function activeFilters(filters: BidFilterState): number {
  return (Object.keys(NO_FILTERS) as (keyof BidFilterState)[]).filter((key) => key !== 'sort' && filters[key] !== NO_FILTERS[key]).length
}

/** The bids that pass the filters, in the chosen order. */
export function applyFilters(bids: TenderBid[], filters: BidFilterState): TenderBid[] {
  const words = filters.text.toLowerCase().split(/\s+/).filter(Boolean)
  const days = number(filters.closingDays)
  const deadline = days != null ? Date.now() + days * 86400000 : null
  const min = number(filters.minLakh)
  const max = number(filters.maxLakh)
  const feeMax = number(filters.feeMax)
  const emdMax = number(filters.emdMax)
  const kept = bids.filter((bid) => {
    if (words.length) {
      const haystack = [bid.bid_number, bid.title, bid.category, bid.work_description, bid.ministry, bid.department, bid.reference, ...places(bid)]
        .filter(Boolean)
        .join(' ')
        .toLowerCase()
      if (!words.every((word) => haystack.includes(word))) return false
    }
    if (filters.place && !places(bid).some((place) => place === filters.place)) return false
    if (deadline != null && (!bid.end_timestamp || new Date(bid.end_timestamp).getTime() > deadline)) return false
    if (filters.withValueOnly && bid.estimated_value == null) return false
    if (min != null && (bid.estimated_value == null || bid.estimated_value < min * LAKH)) return false
    if (max != null && (bid.estimated_value == null || bid.estimated_value > max * LAKH)) return false
    if (filters.category && (bid.tender_category ?? '') !== filters.category) return false
    if (filters.noFeeOnly && (bid.tender_fee ?? 0) > 0) return false
    if (feeMax != null && (bid.tender_fee ?? 0) > feeMax) return false
    if (emdMax != null && (bid.emd_amount ?? 0) > emdMax) return false
    if (filters.emd === 'required' && !(bid.emd_required === true || (bid.emd_amount ?? 0) > 0)) return false
    if (filters.emd === 'none' && (bid.emd_required === true || (bid.emd_amount ?? 0) > 0)) return false
    if (filters.guarantee === 'required' && bid.epbg_required !== true) return false
    if (filters.guarantee === 'none' && bid.epbg_required !== false) return false
    return true
  })
  const value = (bid: TenderBid) => bid.estimated_value ?? -1
  const closing = (bid: TenderBid) => (bid.end_timestamp ? new Date(bid.end_timestamp).getTime() : Number.MAX_SAFE_INTEGER)
  const found = (bid: TenderBid) => new Date(bid.first_matched_timestamp).getTime()
  const order = {
    closing: (a: TenderBid, b: TenderBid) => closing(a) - closing(b),
    value_desc: (a: TenderBid, b: TenderBid) => value(b) - value(a),
    value_asc: (a: TenderBid, b: TenderBid) => (value(a) < 0 ? 1 : value(b) < 0 ? -1 : value(a) - value(b)),
    found: (a: TenderBid, b: TenderBid) => found(b) - found(a),
  }[filters.sort]
  return [...kept].sort(order)
}

/** The filter bar above a search's bids. */
export function BidFilters(props: FilterBarProps) {
  const lumen = useLumen()
  const [open, setOpen] = useState(false)
  if (!lumen) return <FullFilters {...props} />
  return <LumenFilters {...props} open={open} onToggle={() => setOpen((v) => !v)} />
}

interface FilterBarProps {
  portal: TenderSource
  bids: TenderBid[]
  filters: BidFilterState
  onChange: (next: BidFilterState) => void
  /** How many pass the filters. */
  shown: number
}

/** Lumen: the few things asked most (words, how soon it closes, the order) in one line, and every other filter one tap away. */
function LumenFilters({ portal, bids, filters, onChange, shown, open, onToggle }: FilterBarProps & { open: boolean; onToggle: () => void }) {
  const count = activeFilters(filters)
  const closing: [string, string][] = [
    ['', 'Any time'],
    ['3', '3 days'],
    ['7', 'A week'],
    ['30', 'A month'],
  ]
  return (
    <div className="space-y-3" role="search" aria-label="Filter the bids found">
      <div className="flex flex-wrap items-center gap-2">
        <input
          aria-label="Words"
          value={filters.text}
          placeholder="Search title, number, department, place"
          onChange={(event) => onChange({ ...filters, text: event.target.value })}
          className="h-11 min-w-[14rem] flex-1 rounded-full px-4 text-sm sm:max-w-sm"
        />
        <div role="group" aria-label="Closing within" className="flex rounded-full border border-[color:var(--color-border)] bg-muted p-1">
          {closing.map(([value, label]) => (
            <button key={label} type="button" aria-pressed={filters.closingDays === value} onClick={() => onChange({ ...filters, closingDays: value })} className={`interactive rounded-full px-3.5 py-1.5 text-sm font-semibold ${filters.closingDays === value ? 'bg-surface text-[color:var(--color-text)] shadow-card' : 'text-[color:var(--color-text-muted)]'}`}>
              {label}
            </button>
          ))}
        </div>
        <select aria-label="Sort by" value={filters.sort} onChange={(event) => onChange({ ...filters, sort: event.target.value as BidFilterState['sort'] })} className="h-10 rounded-full px-3 text-sm">
          <option value="closing">Closing soonest</option>
          <option value="value_desc">Value, highest first</option>
          <option value="value_asc">Value, lowest first</option>
          <option value="found">Found most recently</option>
        </select>
        <button type="button" onClick={onToggle} aria-expanded={open} className={`interactive inline-flex h-10 items-center gap-1.5 rounded-full border px-4 text-sm font-semibold ${open || count > 0 ? 'border-[color:var(--color-accent)] text-accent' : 'border-[color:var(--color-border)] text-[color:var(--color-text-muted)] hover:bg-muted'}`}>
          <SlidersHorizontal className="h-4 w-4" aria-hidden="true" /> More filters{count ? ` · ${count} on` : ''}
        </button>
        {count > 0 && (
          <button type="button" onClick={() => onChange({ ...NO_FILTERS, sort: filters.sort })} className="interactive text-sm font-semibold text-[color:var(--color-text-muted)] underline-offset-2 hover:underline">
            Clear
          </button>
        )}
        <span className="t-caption ml-auto text-[color:var(--color-text-muted)]">
          Showing {shown} of {bids.length}
        </span>
      </div>
      {open && <FullFilters portal={portal} bids={bids} filters={filters} onChange={onChange} shown={shown} />}
    </div>
  )
}

function FullFilters({
  portal,
  bids,
  filters,
  onChange,
  shown,
}: {
  portal: TenderSource
  bids: TenderBid[]
  filters: BidFilterState
  onChange: (next: BidFilterState) => void
  /** How many pass the filters. */
  shown: number
}) {
  const set = <K extends keyof BidFilterState>(key: K, value: BidFilterState[K]) => onChange({ ...filters, [key]: value })
  const placeOptions = useMemo(() => [...new Set(bids.flatMap(places))].sort((a, b) => a.localeCompare(b)), [bids])
  const categories = useMemo(() => [...new Set(bids.map((bid) => bid.tender_category).filter((c): c is string => Boolean(c)))].sort(), [bids])
  const count = activeFilters(filters)

  return (
    <div className="panel space-y-3 p-3" role="search" aria-label="Filter the bids found">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <p className="t-label inline-flex items-center gap-1.5 text-[color:var(--color-text)]">
          <SlidersHorizontal className="h-4 w-4" aria-hidden="true" /> Filters
          <span className="t-caption font-normal">
            {count ? `${count} on · ` : ''}showing {shown} of {bids.length}
          </span>
        </p>
        {count > 0 && (
          <Button size="sm" variant="ghost" onClick={() => onChange({ ...NO_FILTERS, sort: filters.sort })}>
            <X className="h-3.5 w-3.5" aria-hidden="true" /> Clear filters
          </Button>
        )}
      </div>
      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        <Field label="Words">
          <Input aria-label="Words" value={filters.text} placeholder="Title, number, department, place" onChange={(event) => set('text', event.target.value)} />
        </Field>
        <Field label="Place">
          <Select aria-label="Place" value={filters.place} onChange={(event) => set('place', event.target.value)}>
            <option value="">Anywhere</option>
            {placeOptions.map((place) => (
              <option key={place} value={place}>
                {place}
              </option>
            ))}
          </Select>
        </Field>
        <Field label="Closing">
          <Select aria-label="Closing" value={filters.closingDays} onChange={(event) => set('closingDays', event.target.value)}>
            <option value="">Any time</option>
            <option value="3">Within 3 days</option>
            <option value="7">Within a week</option>
            <option value="15">Within 15 days</option>
            <option value="30">Within a month</option>
          </Select>
        </Field>
        <Field label="Sort by">
          <Select aria-label="Sort by" value={filters.sort} onChange={(event) => set('sort', event.target.value as BidFilterState['sort'])}>
            <option value="closing">Closing soonest</option>
            <option value="value_desc">Value, highest first</option>
            <option value="value_asc">Value, lowest first</option>
            <option value="found">Found most recently</option>
          </Select>
        </Field>
        <Field label="Value from (₹ lakh)">
          <MoneyInput aria-label="Value from (₹ lakh)" value={filters.minLakh} decimals={4} scale={100000} placeholder="Any" onChange={(raw) => set('minLakh', raw)} />
        </Field>
        <Field label="Value up to (₹ lakh)">
          <MoneyInput aria-label="Value up to (₹ lakh)" value={filters.maxLakh} decimals={4} scale={100000} placeholder="Any" onChange={(raw) => set('maxLakh', raw)} />
        </Field>
        <Field label="EMD up to (₹)">
          <MoneyInput aria-label="EMD up to (₹)" value={filters.emdMax} placeholder="Any" onChange={(raw) => set('emdMax', raw)} />
        </Field>
        {portal === 'mptenders' ? (
          <>
            <Field label="Tender category">
              <Select aria-label="Tender category" value={filters.category} onChange={(event) => set('category', event.target.value)}>
                <option value="">Any</option>
                {categories.map((category) => (
                  <option key={category} value={category}>
                    {category}
                  </option>
                ))}
              </Select>
            </Field>
            <Field label="Tender fee up to (₹)">
              <MoneyInput aria-label="Tender fee up to (₹)" value={filters.feeMax} placeholder="Any" onChange={(raw) => set('feeMax', raw)} />
            </Field>
          </>
        ) : (
          <>
            <Field label="EMD">
              <Select aria-label="EMD" value={filters.emd} onChange={(event) => set('emd', event.target.value as BidFilterState['emd'])}>
                <option value="">Either</option>
                <option value="none">Not required</option>
                <option value="required">Required</option>
              </Select>
            </Field>
            <Field label="Performance guarantee">
              <Select aria-label="Performance guarantee" value={filters.guarantee} onChange={(event) => set('guarantee', event.target.value as BidFilterState['guarantee'])}>
                <option value="">Either</option>
                <option value="none">Not required</option>
                <option value="required">Required</option>
              </Select>
            </Field>
          </>
        )}
      </div>
      <div className="flex flex-wrap gap-x-6 gap-y-2">
        <Checkbox label="Only those that state a value" checked={filters.withValueOnly} onChange={(on) => set('withValueOnly', on)} />
        {portal === 'mptenders' && <Checkbox label="Only those with no tender fee" checked={filters.noFeeOnly} onChange={(on) => set('noFeeOnly', on)} />}
      </div>
    </div>
  )
}
