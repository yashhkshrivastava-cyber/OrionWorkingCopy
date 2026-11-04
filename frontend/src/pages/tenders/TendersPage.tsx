import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { CalendarClock, Copy, ExternalLink, Gavel, MapPin, Pencil, Plus, RefreshCw, Send, Star, Trash2, Undo2, X } from 'lucide-react'
import { tendersApi } from '../../api/client'
import { StatTile } from '../../components/billing/StatTile'
import { inr, inrFull } from '../../components/dashboard/format'
import { Alert, Badge } from '../../components/ui/Alert'
import { Button } from '../../components/ui/Button'
import { EmptyState, Skeleton } from '../../components/ui/EmptyState'
import { Checkbox } from '../../components/ui/Field'
import { PageHeader } from '../../components/ui/PageHeader'
import { Segmented } from '../../components/ui/Segmented'
import { useToast } from '../../components/ui/Toast'
import { useAuth } from '../../context/AuthContext'
import { useLumen } from '../../lumen/useLumen'
import { formatDateTime, timeAgo } from '../../formatTime'
import type { TenderBid, TenderMatchStatus, TenderSearch, TenderSource, TenderStatus } from '../../types'
import { SearchForm } from './SearchForm'
import { BidFilters, NO_FILTERS, applyFilters, type BidFilterState } from './BidFilters'
import { ClosingTile, TermChips, daysLeft } from './lumenTenders'

type View = TenderMatchStatus | 'all'

const VIEWS: { id: View; label: string }[] = [
  { id: 'new', label: 'New' },
  { id: 'shortlisted', label: 'Shortlisted' },
  { id: 'dismissed', label: 'Dismissed' },
  { id: 'all', label: 'All' },
]

const KIND_LABEL = { service: 'Services', product: 'Products / Goods', works: 'Works', all: 'All kinds' } as const
const BATCH = 30 // bids shown at a time
const PORTAL = { gem: 'GeM', mptenders: 'MP Tenders' } as const

function summary(search: TenderSearch): string {
  const parts = [
    search.tender_types.length ? search.tender_types.join(', ') : 'Any type',
    search.cities.length ? search.cities.join(', ') : 'Anywhere',
  ]
  if (search.min_value != null || search.max_value != null) {
    const low = search.min_value != null ? inr(search.min_value) : 'any'
    const high = search.max_value != null ? inr(search.max_value) : 'any'
    parts.push(`${low} to ${high}`)
  }
  return parts.join(' · ')
}

/** "Closes today, 2:30 pm", "Closes tomorrow, ..." or "Closes in 5 days (...)", counted in calendar days on this computer. */
function closesIn(iso: string | null): { text: string; soon: boolean } {
  if (!iso) return { text: 'Closing date not given', soon: false }
  const end = new Date(iso)
  const when = formatDateTime(iso)
  if (end.getTime() <= Date.now()) return { text: `Closed ${when}`, soon: false }
  const midnight = (date: Date) => new Date(date.getFullYear(), date.getMonth(), date.getDate()).getTime()
  const days = Math.round((midnight(end) - midnight(new Date())) / 86400000)
  const time = when.split(', ')[1] ?? when
  if (days === 0) return { text: `Closes today, ${time}`, soon: true }
  if (days === 1) return { text: `Closes tomorrow, ${time}`, soon: true }
  return { text: `Closes in ${days} days (${when})`, soon: days <= 3 }
}

/** Put text on the clipboard. The browser's clipboard needs a secure page (https or this computer); elsewhere, the old way. */
async function copyText(text: string): Promise<boolean> {
  try {
    if (navigator.clipboard && window.isSecureContext) {
      await navigator.clipboard.writeText(text)
      return true
    }
  } catch {
    /* fall through to the old way */
  }
  const area = document.createElement('textarea')
  area.value = text
  area.setAttribute('readonly', '')
  area.style.position = 'fixed'
  area.style.opacity = '0'
  document.body.appendChild(area)
  area.select()
  let copied = false
  try {
    copied = document.execCommand('copy')
  } catch {
    copied = false
  }
  area.remove()
  return copied
}

/** What a seller must put up to apply, as the bid document states it. GeM allows no tender fee, so there never is one. */
/** A fee or deposit: exact rupees under a lakh ("₹3,000"), lakhs and crores above ("₹1.40 L"). */
function fee(value: number): string {
  return value < 100000 ? inrFull(value) : inr(value, 2)
}

function toApply(bid: TenderBid): string[] {
  const parts: string[] = []
  if (bid.source === 'mptenders') {
    if (bid.tender_fee != null)
      parts.push(
        `Tender fee ${fee(bid.tender_fee)}${bid.tender_fee_total != null && bid.tender_fee_total !== bid.tender_fee ? ` (${fee(bid.tender_fee_total)} with charges)` : ''}${bid.tender_fee_exempt ? ', exemption allowed' : ''}`,
      )
    else if (bid.document_status === 'read') parts.push('No tender fee stated')
    if (bid.emd_amount != null) parts.push(`EMD ${fee(bid.emd_amount)}${bid.emd_exempt ? ', exemption allowed' : ''}`)
    else if (bid.document_status === 'read') parts.push('No EMD stated')
    return parts
  }
  if (bid.emd_required === false) parts.push('No EMD')
  else if (bid.emd_amount != null) parts.push(`EMD ${fee(bid.emd_amount)} (MSEs and startups can ask for exemption)`)
  else if (bid.document_status === 'read') parts.push('EMD not stated')
  if (bid.epbg_required === false) parts.push('No performance guarantee')
  else if (bid.epbg_percent != null)
    parts.push(`Performance guarantee ${bid.epbg_percent}%${bid.epbg_months ? ` for ${bid.epbg_months} months` : ''} if won`)
  parts.push('No tender fee (GeM does not allow one)')
  return parts
}

function BidCard({
  bid,
  canWrite,
  justFound,
  onStatus,
}: {
  bid: TenderBid
  canWrite: boolean
  /** Found by the latest check. */
  justFound: boolean
  onStatus: (bid: TenderBid, status: TenderMatchStatus) => void
}) {
  const toast = useToast()
  const lumen = useLumen()
  const closing = closesIn(bid.end_timestamp)
  const place = bid.location_districts?.length ? bid.location_districts.join(', ') : bid.matched_city
  const copyNumber = async () => {
    if (await copyText(bid.bid_number)) toast.show(`Copied ${bid.bid_number}`)
    else toast.show('Could not copy the bid number', { tone: 'error', detail: 'Select it and copy it by hand.' })
  }
  const onMp = bid.source === 'mptenders'
  const portal = PORTAL[bid.source] ?? 'GeM'
  // Neither portal has a link to one tender's application: the number goes on the clipboard, and the portal opens in a new tab.
  const apply = async () => {
    const copied = await copyText(bid.bid_number)
    toast.show(copied ? `${onMp ? 'Tender ID' : 'Bid number'} ${bid.bid_number} copied` : `${bid.bid_number}`, {
      tone: 'info',
      detail: onMp
        ? 'On MP Tenders, sign in with your DSC, find the tender by its Tender ID (the portal asks you to type a captcha) and bid there.'
        : 'On GeM, sign in as the seller, open Bids > Participate in Bids and paste the bid number to open it.',
    })
  }
  if (lumen) {
    const chip = 'rounded-full bg-muted px-2.5 py-1 text-xs font-medium text-[color:var(--color-text-muted)]'
    const asked = [bid.quantity != null ? `Quantity ${bid.quantity}` : '', bid.contract_period ? `Contract ${bid.contract_period}` : '', bid.min_turnover ? `Turnover asked ${bid.min_turnover}` : '', bid.experience_years != null ? `Experience ${bid.experience_years} years` : ''].filter(Boolean)
    return (
      <li className={`panel !p-4 sm:!p-5 ${justFound && bid.status === 'new' ? 'page-enter' : ''}`}>
        <div className="flex flex-wrap gap-x-5 gap-y-4">
          <ClosingTile iso={bid.end_timestamp} />
          <div className="min-w-0 flex-1 basis-72 space-y-2.5">
            <div className="flex flex-wrap items-center gap-2">
              <Badge variant={onMp ? 'amber' : 'violet'}>{portal}</Badge>
              {onMp ? (
                <span className="font-mono text-sm font-semibold" title="MP Tenders' links work only in the visit that made them: find the tender on the portal by this ID">
                  {bid.bid_number}
                </span>
              ) : (
                <a href={bid.document_url} target="_blank" rel="noopener noreferrer" className="inline-flex items-center gap-1 font-mono text-sm font-semibold text-accent underline-offset-2 hover:underline">
                  {bid.bid_number}
                  <ExternalLink className="h-3.5 w-3.5" aria-hidden="true" />
                  <span className="sr-only">(opens the bid document on GeM)</span>
                </a>
              )}
              <button type="button" onClick={copyNumber} title={onMp ? 'Copy the Tender ID' : 'Copy the bid number'} aria-label={`Copy ${onMp ? 'the Tender ID' : 'the bid number'} ${bid.bid_number}`} className="interactive grid h-7 w-7 place-items-center rounded-full text-[color:var(--color-text-faint)] hover:bg-muted">
                <Copy className="h-3.5 w-3.5" aria-hidden="true" />
              </button>
              {justFound && bid.status === 'new' && <Badge variant="cyan">Just found</Badge>}
              {bid.status === 'shortlisted' && <Badge variant="emerald">Shortlisted</Badge>}
              {bid.status === 'dismissed' && <Badge>Dismissed</Badge>}
              {bid.is_high_value && <Badge variant="violet">High value</Badge>}
            </div>
            <h3 className="font-display text-base font-semibold leading-snug">{bid.title || bid.category || 'Category not given'}</h3>
            <p className="t-caption text-[color:var(--color-text-muted)]">
              {[onMp ? bid.tender_category : null, onMp ? bid.category : null, ...(onMp && bid.reference ? [`Ref. ${bid.reference}`] : []), bid.ministry, bid.department].filter(Boolean).join(' · ') || 'Buyer not given'}
            </p>
            <p className="flex flex-wrap gap-x-4 gap-y-1 text-xs text-[color:var(--color-text-muted)]">
              <span className="inline-flex items-center gap-1">
                <MapPin className="h-3.5 w-3.5" aria-hidden="true" />
                {place || 'Place not stated in the bid document'}
                {bid.matched_city && !bid.location_confirmed && <span className="text-warning"> (not confirmed: the bid document could not be read)</span>}
              </span>
              <span className={`inline-flex items-center gap-1 ${closing.soon ? 'font-semibold text-warning' : ''}`}>
                <CalendarClock className="h-3.5 w-3.5" aria-hidden="true" />
                {closing.text}
              </span>
            </p>
            <div className="flex flex-wrap gap-1.5" aria-label="To apply">
              {toApply(bid).map((part) => (
                <span key={part} className={chip}>
                  {part}
                </span>
              ))}
              {asked.map((part) => (
                <span key={part} className={chip}>
                  {part}
                </span>
              ))}
            </div>
          </div>
          <div className="flex shrink-0 flex-col items-start gap-3 sm:items-end">
            <div className="sm:text-right">
              <p className="t-caption text-[color:var(--color-text-faint)]">Estimated value</p>
              <p className="font-display text-2xl font-semibold tabular-nums leading-tight">
                {bid.estimated_value != null ? inr(bid.estimated_value, 2) : bid.document_status === 'read' ? 'Not stated' : 'Not read yet'}
              </p>
            </div>
            <a href={bid.apply_url} target="_blank" rel="noopener noreferrer" onClick={apply} className="btn-primary interactive inline-flex h-10 items-center gap-2 rounded-full px-5 text-sm font-semibold">
              <Send className="h-4 w-4" aria-hidden="true" /> Apply on {portal}
              <span className="sr-only">(copies {onMp ? 'the Tender ID' : 'the bid number'} and opens {portal})</span>
            </a>
            {canWrite && (
              <div className="flex flex-wrap gap-1.5 sm:justify-end">
                {bid.status !== 'shortlisted' && (
                  <Button size="sm" variant="secondary" onClick={() => onStatus(bid, 'shortlisted')}>
                    <Star className="h-3.5 w-3.5" aria-hidden="true" /> Shortlist
                  </Button>
                )}
                {bid.status !== 'dismissed' && (
                  <Button size="sm" variant="ghost" onClick={() => onStatus(bid, 'dismissed')}>
                    <X className="h-3.5 w-3.5" aria-hidden="true" /> Dismiss
                  </Button>
                )}
                {bid.status !== 'new' && (
                  <Button size="sm" variant="ghost" onClick={() => onStatus(bid, 'new')}>
                    <Undo2 className="h-3.5 w-3.5" aria-hidden="true" /> Back to new
                  </Button>
                )}
              </div>
            )}
          </div>
        </div>
      </li>
    )
  }
  return (
    <li className={`panel p-4 ${justFound && bid.status === 'new' ? 'page-enter' : ''}`}>
      <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
        <div className="min-w-0 space-y-1.5">
          <div className="flex flex-wrap items-center gap-2">
            <Badge variant={onMp ? 'amber' : 'violet'}>{portal}</Badge>
            {onMp ? (
              <span className="font-mono text-sm font-semibold text-[color:var(--color-text)]" title="MP Tenders' links work only in the visit that made them: find the tender on the portal by this ID">
                {bid.bid_number}
              </span>
            ) : (
              <a
                href={bid.document_url}
                target="_blank"
                rel="noopener noreferrer"
                className="inline-flex items-center gap-1 font-mono text-sm font-semibold text-accent underline-offset-2 hover:underline"
              >
                {bid.bid_number}
                <ExternalLink className="h-3.5 w-3.5" aria-hidden="true" />
                <span className="sr-only">(opens the bid document on GeM)</span>
              </a>
            )}
            <button
              type="button"
              onClick={copyNumber}
              title={onMp ? 'Copy the Tender ID' : 'Copy the bid number'}
              aria-label={`Copy ${onMp ? 'the Tender ID' : 'the bid number'} ${bid.bid_number}`}
              className="interactive rounded p-1 text-[color:var(--color-text-faint)] hover:bg-muted hover:text-[color:var(--color-text)]"
            >
              <Copy className="h-3.5 w-3.5" aria-hidden="true" />
            </button>
            {justFound && bid.status === 'new' && <Badge variant="cyan">Just found</Badge>}
            {bid.status === 'shortlisted' && <Badge variant="emerald">Shortlisted</Badge>}
            {bid.status === 'dismissed' && <Badge>Dismissed</Badge>}
            {bid.is_high_value && <Badge variant="violet">High value</Badge>}
          </div>
          <p className="text-sm font-medium text-[color:var(--color-text)]">{bid.title || bid.category || 'Category not given'}</p>
          {onMp && (bid.category || bid.tender_category || bid.reference) && (
            <p className="t-caption">{[bid.tender_category, bid.category, bid.reference && `Ref. ${bid.reference}`].filter(Boolean).join(' · ')}</p>
          )}
          <p className="t-caption">{[bid.ministry, bid.department].filter(Boolean).join(' · ') || 'Buyer not given'}</p>
          <div className="flex flex-wrap gap-x-4 gap-y-1 pt-1 text-xs text-[color:var(--color-text-muted)]">
            <span className="inline-flex items-center gap-1">
              <MapPin className="h-3.5 w-3.5" aria-hidden="true" />
              {place || 'Place not stated in the bid document'}
              {bid.matched_city && !bid.location_confirmed && <span className="text-warning"> (not confirmed: the bid document could not be read)</span>}
            </span>
            <span className={`inline-flex items-center gap-1 ${closing.soon ? 'font-medium text-warning' : ''}`}>
              <CalendarClock className="h-3.5 w-3.5" aria-hidden="true" />
              {closing.text}
            </span>
            {bid.quantity != null && <span>Quantity {bid.quantity}</span>}
            {bid.contract_period && <span>Contract {bid.contract_period}</span>}
            {bid.min_turnover && <span>Turnover asked {bid.min_turnover}</span>}
            {bid.experience_years != null && <span>Experience {bid.experience_years} years</span>}
          </div>
          <p className="t-caption">
            <span className="font-medium text-[color:var(--color-text-muted)]">To apply: </span>
            {toApply(bid).join(' · ')}
          </p>
        </div>
        <div className="flex shrink-0 flex-col items-start gap-2 sm:items-end">
          <div className="text-left sm:text-right">
            <p className="t-label text-[color:var(--color-text)] tabular-nums">
              {bid.estimated_value != null ? inr(bid.estimated_value, 2) : bid.document_status === 'read' ? 'Value not stated' : 'Value not read yet'}
            </p>
          </div>
          <a
            href={bid.apply_url}
            target="_blank"
            rel="noopener noreferrer"
            onClick={apply}
            className="interactive btn-primary inline-flex h-8 items-center gap-1.5 rounded-lg px-3 text-xs font-semibold"
          >
            <Send className="h-3.5 w-3.5" aria-hidden="true" /> Apply on {portal}
            <span className="sr-only">(copies {onMp ? 'the Tender ID' : 'the bid number'} and opens {portal})</span>
          </a>
          {canWrite && (
            <div className="flex gap-1.5">
              {bid.status !== 'shortlisted' && (
                <Button size="sm" variant="secondary" onClick={() => onStatus(bid, 'shortlisted')}>
                  <Star className="h-3.5 w-3.5" aria-hidden="true" /> Shortlist
                </Button>
              )}
              {bid.status !== 'dismissed' && (
                <Button size="sm" variant="ghost" onClick={() => onStatus(bid, 'dismissed')}>
                  <X className="h-3.5 w-3.5" aria-hidden="true" /> Dismiss
                </Button>
              )}
              {bid.status !== 'new' && (
                <Button size="sm" variant="ghost" onClick={() => onStatus(bid, 'new')}>
                  <Undo2 className="h-3.5 w-3.5" aria-hidden="true" /> Back to new
                </Button>
              )}
            </div>
          )}
        </div>
      </div>
    </li>
  )
}

function CheckStatus({ status }: { status: TenderStatus | null }) {
  if (!status) return null
  const run = status.last_run
  if (status.running) {
    const live = run?.status === 'running' ? run : null
    return (
      <div className="t-caption flex items-start gap-1.5" aria-live="polite">
        <RefreshCw className="mt-0.5 h-3.5 w-3.5 shrink-0 animate-spin" aria-hidden="true" />
        <p>
          <span className="font-medium text-[color:var(--color-text)]">Checking{live?.progress ? `: ${live.progress}` : ''}.</span>{' '}
          {live && `${live.bids_seen} bids looked at, ${live.documents_read} documents read, ${live.matches_new} new so far. `}
          Each search's bids appear as soon as it is done; a big search (a large city, or all kinds of bid) can take several minutes the
          first time, and much less after.
        </p>
      </div>
    )
  }
  const scope = status.lookback_days ? `Orion looks at bids published in the last ${status.lookback_days} days that are still open. ` : ''
  const schedule = scope + (status.every_hours ? `It checks every ${status.every_hours} hours.` : 'Scheduled checks are off.')
  if (!run) return <p className="t-caption">Not checked yet. {schedule}</p>
  return (
    <p className="t-caption">
      Last checked {timeAgo(run.finished_timestamp || run.started_timestamp)}
      {run.status === 'succeeded' && `: ${run.bids_seen} open bids looked at, ${run.matches_new} new for your searches`}. {schedule}
    </p>
  )
}

export function GemTendersPage() {
  return <TendersPage portal="gem" />
}

export function MpTendersPage() {
  return <TendersPage portal="mptenders" />
}

const PAGE_TEXT: Record<TenderSource, { title: string; subtitle: string }> = {
  gem: {
    title: 'GeM tenders',
    subtitle: "Saved searches for bids on GeM, the Government e-Marketplace. Orion reads each bid's public document for its value, EMD, performance guarantee and where the work is.",
  },
  mptenders: {
    title: 'MP tenders',
    subtitle: "Saved searches for tenders on MP Tenders, Madhya Pradesh's e-procurement portal. Orion reads each tender's details for its value, tender fee, EMD and where the work is.",
  },
}

function TendersPage({ portal }: { portal: TenderSource }) {
  const { user } = useAuth()
  const canWrite = Boolean(user?.can_tenders_write)
  const toast = useToast()
  const lumen = useLumen()
  const [searches, setSearches] = useState<TenderSearch[] | null>(null)
  const [status, setStatus] = useState<TenderStatus | null>(null)
  const [selected, setSelected] = useState<number | null>(null)
  const [view, setView] = useState<View>('new')
  const [showClosed, setShowClosed] = useState(false)
  const [bids, setBids] = useState<TenderBid[] | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [editing, setEditing] = useState<TenderSearch | null>(null)
  const [formOpen, setFormOpen] = useState(false)
  const [starting, setStarting] = useState(false)

  const loadSearches = useCallback(async () => {
    try {
      const [found, now] = await Promise.all([tendersApi.searches(portal), tendersApi.status(portal)])
      setSearches(found)
      setStatus(now)
      setSelected((current) => (current != null && found.some((s) => s.search_id === current) ? current : found[0]?.search_id ?? null))
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not load the searches.')
    }
  }, [portal])

  // quiet: refresh what is shown without the loading outline (while a check adds bids)
  const loadBids = useCallback(async (quiet = false) => {
    if (selected == null) return setBids([])
    if (!quiet) setBids(null)
    try {
      setBids(await tendersApi.bids(selected, view, showClosed))
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not load the bids.')
      setBids([])
    }
  }, [selected, view, showClosed])

  useEffect(() => {
    void loadSearches()
  }, [loadSearches])

  useEffect(() => {
    void loadBids()
  }, [loadBids])

  // While a check runs, look every few seconds: show its progress, refresh the bids when it has found new ones, and when it
  // ends say what it found.
  const running = Boolean(status?.running)
  const matchesSoFar = useRef<number | null>(null)
  useEffect(() => {
    if (!running) return
    matchesSoFar.current = null
    const timer = window.setInterval(async () => {
      try {
        const now = await tendersApi.status(portal)
        setStatus(now)
        if (now.running) {
          const found = now.last_run?.status === 'running' ? now.last_run.matches_new : null
          if (found != null && matchesSoFar.current != null && found !== matchesSoFar.current) {
            void loadSearches()
            void loadBids(true)
          }
          matchesSoFar.current = found
        } else {
          window.clearInterval(timer)
          const run = now.last_run
          if (run?.status === 'failed') toast.show('The check did not finish', { tone: 'error', detail: run.error ?? undefined })
          else if (run) toast.show(`Checked: ${run.matches_new} new bid${run.matches_new === 1 ? '' : 's'} for your searches`)
          void loadSearches()
          void loadBids()
        }
      } catch {
        window.clearInterval(timer)
      }
    }, 4000)
    return () => window.clearInterval(timer)
  }, [running, toast, loadSearches, loadBids, portal])

  const current = useMemo(() => searches?.find((s) => s.search_id === selected) ?? null, [searches, selected])
  // Which search a running check is on, and when the latest check began (bids it found are marked "Just found").
  const checkingId = running && status?.last_run?.status === 'running' ? status.last_run.current_search_id ?? null : null
  const lastRunStart = status?.last_run ? new Date(status.last_run.started_timestamp).getTime() : null
  const [shown, setShown] = useState(BATCH)
  const [filters, setFilters] = useState<BidFilterState>(NO_FILTERS)
  useEffect(() => setShown(BATCH), [selected, view, showClosed, filters])
  const visible = useMemo(() => (bids ? applyFilters(bids, filters) : []), [bids, filters])
  // The figures Lumen opens with: what is new across every search, what is shortlisted, and what in this list closes within three days.
  const newTotal = useMemo(() => (searches ?? []).reduce((sum, search) => sum + (search.new_count ?? 0), 0), [searches])
  const shortlistedTotal = useMemo(() => (searches ?? []).reduce((sum, search) => sum + (search.shortlisted_count ?? 0), 0), [searches])
  const closingSoon = useMemo(
    () => visible.filter((bid) => {
      const left = daysLeft(bid.end_timestamp)
      return left !== null && left >= 0 && left <= 3
    }).length,
    [visible],
  )

  const checkNow = async () => {
    setStarting(true)
    try {
      await tendersApi.check(portal)
      setStatus((now) => (now ? { ...now, running: true } : now))
    } catch (err) {
      toast.show('Could not start a check', { tone: 'error', detail: err instanceof Error ? err.message : undefined })
    } finally {
      setStarting(false)
    }
  }

  const changeStatus = async (bid: TenderBid, next: TenderMatchStatus) => {
    if (!current) return
    try {
      await tendersApi.setStatus(current.search_id, bid.bid_id, next)
      setBids((list) => (list ?? []).flatMap((item) => (item.bid_id !== bid.bid_id ? [item] : view === 'all' ? [{ ...item, status: next }] : [])))
      void loadSearches()
    } catch (err) {
      toast.show('Could not change the bid', { tone: 'error', detail: err instanceof Error ? err.message : undefined })
    }
  }

  const remove = async (search: TenderSearch) => {
    if (!window.confirm(`Delete the search "${search.name}"? Its shortlisted and dismissed bids go with it.`)) return
    try {
      await tendersApi.deleteSearch(search.search_id)
      toast.show('Search deleted')
      void loadSearches()
    } catch (err) {
      toast.show('Could not delete the search', { tone: 'error', detail: err instanceof Error ? err.message : undefined })
    }
  }

  return (
    <div className="space-y-5">
      <PageHeader
        eyebrow="Utilities"
        title={PAGE_TEXT[portal].title}
        subtitle={PAGE_TEXT[portal].subtitle}
        action={
          canWrite ? (
            <div className="flex gap-2">
              <Button variant="secondary" onClick={() => { setEditing(null); setFormOpen(true) }}>
                <Plus className="h-4 w-4" aria-hidden="true" /> New search
              </Button>
              <Button onClick={checkNow} loading={starting || running} disabled={!status?.active_searches}>
                <RefreshCw className="h-4 w-4" aria-hidden="true" /> Check now
              </Button>
            </div>
          ) : undefined
        }
      />
      {lumen && searches && searches.length > 0 && (
        <div className="grid grid-cols-2 gap-3 xl:grid-cols-4">
          <StatTile label="New bids" text={String(newTotal)} hint="Across your searches, not yet looked at" tone={newTotal ? 'text-positive' : ''} />
          <StatTile label="Shortlisted" text={String(shortlistedTotal)} hint="Bids you are going for" />
          <StatTile label="Closing within 3 days" text={String(closingSoon)} hint="In the list below" tone={closingSoon ? 'text-negative' : ''} />
          <StatTile
            label="Last checked"
            text={status?.last_run ? timeAgo(status.last_run.finished_timestamp || status.last_run.started_timestamp) : 'Not yet'}
            hint={running ? 'Checking now' : status?.every_hours ? `Every ${status.every_hours} hours` : 'Scheduled checks are off'}
            tone={status?.failing ? 'text-warning' : ''}
          />
        </div>
      )}
      {(!lumen || running) && <CheckStatus status={status} />}
      {status?.failing && status.last_run?.error && !running && (
        <Alert variant="warning">
          The last check did not finish: {status.last_run.error} Orion tries again at the next check.
        </Alert>
      )}
      {status?.last_run?.note && !running && <Alert variant="info">{status.last_run.note}</Alert>}
      {error && <Alert variant="error" onDismiss={() => setError(null)}>{error}</Alert>}

      {searches === null ? (
        <Skeleton className="h-64" />
      ) : searches.length === 0 ? (
        <EmptyState
          icon={Gavel}
          title="No tender searches yet"
          action={canWrite ? <Button onClick={() => { setEditing(null); setFormOpen(true) }}>Add a search</Button> : undefined}
        >
          Name the tender types, cities and values you want, and Orion finds them on GeM and MP Tenders.
        </EmptyState>
      ) : (
        <div className={lumen ? 'space-y-4' : 'grid gap-5 lg:grid-cols-[minmax(0,20rem)_minmax(0,1fr)]'}>
          {lumen && (
            <nav aria-label="Your searches" className="scroll-quiet -mx-1 flex gap-3 overflow-x-auto px-1 pb-2">
              {searches.map((search) => {
                const on = search.search_id === selected
                return (
                  <button
                    key={search.search_id}
                    type="button"
                    onClick={() => setSelected(search.search_id)}
                    aria-current={on ? 'true' : undefined}
                    className={`panel interactive w-64 shrink-0 !p-4 text-left ${on ? 'ring-2 ring-[color:var(--color-accent)]' : ''} ${search.is_active ? '' : 'opacity-60'}`}
                  >
                    <span className="flex items-start justify-between gap-2">
                      <span className="font-display text-sm font-semibold">{search.name}</span>
                      {(search.new_count ?? 0) > 0 && <span className="rounded-full bg-accent-dim px-2 py-0.5 text-[11px] font-bold text-accent">{search.new_count} new</span>}
                    </span>
                    <span className="t-caption mt-1 line-clamp-2 text-[color:var(--color-text-muted)]" title={summary(search)}>{summary(search)}</span>
                    <span className="t-caption mt-1 block text-[color:var(--color-text-faint)]">
                      {KIND_LABEL[search.bid_kind]}
                      {search.is_active ? '' : ' · paused'}
                      {(search.shortlisted_count ?? 0) > 0 ? ` · ${search.shortlisted_count} shortlisted` : ''}
                    </span>
                    {search.search_id === checkingId && (
                      <span className="mt-1.5 inline-flex items-center gap-1 text-xs font-semibold text-accent">
                        <RefreshCw className="h-3 w-3 animate-spin" aria-hidden="true" /> Being checked now
                      </span>
                    )}
                  </button>
                )
              })}
              {canWrite && (
                <button
                  type="button"
                  onClick={() => { setEditing(null); setFormOpen(true) }}
                  className="interactive grid w-44 shrink-0 place-items-center rounded-[1.5rem] border-2 border-dashed border-[color:var(--color-border-strong)] p-4 text-sm font-semibold text-[color:var(--color-text-muted)] hover:border-[color:var(--color-accent)] hover:text-accent"
                >
                  <span className="inline-flex items-center gap-1.5">
                    <Plus className="h-4 w-4" aria-hidden="true" /> New search
                  </span>
                </button>
              )}
            </nav>
          )}
          {!lumen && (
          <nav aria-label="Your searches" className="space-y-2">
            <p className="eyebrow">Your searches</p>
            {searches.map((search) => {
              const on = search.search_id === selected
              const checking = search.search_id === checkingId
              return (
                <button
                  key={search.search_id}
                  type="button"
                  onClick={() => setSelected(search.search_id)}
                  aria-current={on ? 'true' : undefined}
                  className={`interactive relative block w-full overflow-hidden rounded-xl border p-3 pl-4 text-left ${
                    on
                      ? 'border-[color:var(--color-accent)] bg-accent-dim shadow-card'
                      : 'border-[color:var(--color-border)] bg-surface hover:border-[color:var(--color-border-strong)]'
                  } ${search.is_active ? '' : 'opacity-60'}`}
                >
                  {on && <span aria-hidden="true" className="absolute inset-y-0 left-0 w-1 bg-[color:var(--color-accent)]" />}
                  <span className="flex items-start justify-between gap-2">
                    <span className={`t-label ${on ? 'text-accent' : 'text-[color:var(--color-text)]'}`}>{search.name}</span>
                    {(search.new_count ?? 0) > 0 && <Badge variant="cyan">{search.new_count} new</Badge>}
                  </span>
                  <span className="t-caption mt-1 block">{summary(search)}</span>
                  <span className="t-caption mt-0.5 block">
                    {KIND_LABEL[search.bid_kind]}
                    {search.is_active ? '' : ' · paused'}
                    {(search.shortlisted_count ?? 0) > 0 ? ` · ${search.shortlisted_count} shortlisted` : ''}
                  </span>
                  {checking && (
                    <span className="mt-1.5 inline-flex items-center gap-1 text-xs font-medium text-accent">
                      <RefreshCw className="h-3 w-3 animate-spin" aria-hidden="true" /> Being checked now
                    </span>
                  )}
                </button>
              )
            })}
          </nav>
          )}

          <section aria-label={current ? `Bids for ${current.name}` : 'Bids found'} className="min-w-0 space-y-3">
            {current && (
              <div className="panel space-y-3 p-4">
                <div className="flex flex-col gap-2 sm:flex-row sm:items-start sm:justify-between">
                  <div className="min-w-0">
                    <p className="eyebrow">Showing bids for</p>
                    <h2 className="t-h2 text-[color:var(--color-text)]">{current.name}</h2>
                  </div>
                  {canWrite && (
                    <div className="flex shrink-0 gap-1">
                      <Button size="sm" variant="secondary" onClick={() => { setEditing(current); setFormOpen(true) }}>
                        <Pencil className="h-3.5 w-3.5" aria-hidden="true" /> Change search
                      </Button>
                      <Button size="sm" variant="ghost" onClick={() => remove(current)}>
                        <Trash2 className="h-3.5 w-3.5" aria-hidden="true" /> Delete
                      </Button>
                    </div>
                  )}
                </div>
                <dl className="flex flex-wrap gap-x-5 gap-y-1.5 text-xs">
                  <div className="flex flex-wrap items-center gap-1.5">
                    <dt className="text-[color:var(--color-text-muted)]">Tender types</dt>
                    {lumen ? (
                      <TermChips terms={current.tender_types.length ? current.tender_types : ['Any']} />
                    ) : (
                      (current.tender_types.length ? current.tender_types : ['Any']).map((term) => (
                        <dd key={term} className="rounded-full bg-muted px-2 py-0.5 font-medium">{term}</dd>
                      ))
                    )}
                  </div>
                  <div className="flex flex-wrap items-center gap-1.5">
                    <dt className="text-[color:var(--color-text-muted)]">Cities</dt>
                    {lumen ? (
                      <TermChips terms={current.cities.length ? current.cities : ['Anywhere']} />
                    ) : (
                      (current.cities.length ? current.cities : ['Anywhere']).map((term) => (
                        <dd key={term} className="rounded-full bg-muted px-2 py-0.5 font-medium">{term}</dd>
                      ))
                    )}
                  </div>
                  <div className="flex items-center gap-1.5">
                    <dt className="text-[color:var(--color-text-muted)]">Kind</dt>
                    <dd className="rounded-full bg-muted px-2 py-0.5 font-medium">{KIND_LABEL[current.bid_kind]}</dd>
                  </div>
                  <div className="flex items-center gap-1.5">
                    <dt className="text-[color:var(--color-text-muted)]">Value</dt>
                    <dd className="rounded-full bg-muted px-2 py-0.5 font-medium">
                      {current.min_value == null && current.max_value == null
                        ? 'Any'
                        : `${current.min_value != null ? inr(current.min_value) : 'any'} to ${current.max_value != null ? inr(current.max_value) : 'any'}`}
                      {current.include_unpriced ? ', or not stated' : ''}
                    </dd>
                  </div>
                </dl>
                {checkingId === current.search_id && (
                  <p className="inline-flex items-center gap-1.5 rounded-lg bg-accent-dim px-2.5 py-1.5 text-xs font-medium text-accent" aria-live="polite">
                    <RefreshCw className="h-3.5 w-3.5 animate-spin" aria-hidden="true" />
                    This search is being checked now. Matching bids appear below one by one as they are found.
                  </p>
                )}
              </div>
            )}
            {current && (
              <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
                <Segmented label="Show" value={view} options={VIEWS} onChange={setView} />
                <div className="flex flex-wrap items-center gap-3">
                  <Checkbox label="Show closed bids" checked={showClosed} onChange={setShowClosed} />
                </div>
              </div>
            )}
            {bids === null ? (
              <Skeleton className="h-40" />
            ) : bids.length === 0 ? (
              <EmptyState compact icon={Gavel} title={view === 'new' ? 'Nothing new' : 'No bids here'}>
                {view !== 'new'
                  ? 'Bids you mark appear here.'
                  : current && checkingId === current.search_id
                    ? 'This search is being checked now. Matching bids appear here one by one as they are found.'
                    : running
                      ? 'A check is running; this search gets its turn, and its tenders appear here as they are found.'
                      : !current || !status?.last_run || new Date(current.last_updated_timestamp) > new Date(status.last_run.started_timestamp)
                        ? 'This search has not been checked since it was saved. Press Check now, or wait for the next check.'
                        : 'No open tender fits this search that you have not already shortlisted or dismissed.'}
              </EmptyState>
            ) : (
              <>
                <BidFilters portal={portal} bids={bids} filters={filters} onChange={setFilters} shown={visible.length} />
                {visible.length === 0 && (
                  <EmptyState compact icon={Gavel} title="No bid passes these filters">
                    {bids.length} {bids.length === 1 ? 'bid was' : 'bids were'} found for this search; loosen or clear the filters to see them.
                  </EmptyState>
                )}
                <ul className="space-y-3">
                  {visible.slice(0, shown).map((bid) => (
                    <BidCard
                      key={bid.bid_id}
                      bid={bid}
                      canWrite={canWrite}
                      justFound={Boolean(lastRunStart && new Date(bid.first_matched_timestamp).getTime() >= lastRunStart)}
                      onStatus={changeStatus}
                    />
                  ))}
                </ul>
                {visible.length > shown && (
                  <div className="flex justify-center">
                    <Button variant="secondary" onClick={() => setShown((count) => count + BATCH)}>
                      Show {Math.min(BATCH, visible.length - shown)} more ({visible.length - shown} not shown yet)
                    </Button>
                  </div>
                )}
              </>
            )}
          </section>
        </div>
      )}

      <SearchForm
        portal={portal}
        open={formOpen}
        search={editing}
        onClose={() => setFormOpen(false)}
        onSaved={(saved) => {
          setFormOpen(false)
          toast.show(editing ? 'Search saved' : 'Search added', { detail: 'Press Check now to look straight away.' })
          setSelected(saved.search_id)
          void loadSearches()
          void loadBids()
        }}
      />
    </div>
  )
}
