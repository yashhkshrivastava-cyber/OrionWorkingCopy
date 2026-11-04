import { useEffect, useMemo, useRef, useState } from 'react'
import { Link, Navigate, useNavigate, useParams, useSearchParams } from 'react-router-dom'
import { ChevronLeft, Plus, Settings2, Trash2 } from 'lucide-react'
import { api } from '../../api/client'
import { newIdempotencyKey } from '../../api/idempotency'
import { DEFAULT_RATES, MANUAL_NAMES, calculate, lineAmount, money, type BillRates, type ExtraInput, type LineInput, type ManualInput, type ManualKey } from '../../billing/billCalc'
import { LAYOUT_GROUPS, UNIT_SETUP } from '../../billing/billLayout'
import { LineFields, LineSetupEditor } from '../../components/billing/BillLinesEditor'
import { BillOwnDetails } from '../../components/billing/BillOwnDetails'
import { wordsOfAmount } from '../../billing/moneyText'
import { BillDocument, formatMonth } from '../../components/billing/BillDocument'
import { BillTemplateModal } from '../../components/billing/BillTemplateModal'
import { BillNumber } from '../../components/billing/BillNumber'
import { Alert } from '../../components/ui/Alert'
import { Button } from '../../components/ui/Button'
import { Checkbox, Field, Input, Textarea } from '../../components/ui/Field'
import { MoneyInput } from '../../components/ui/MoneyInput'
import { SearchSelect } from '../../components/ui/SearchSelect'
import { Segmented } from '../../components/ui/Segmented'
import { useAuth } from '../../context/AuthContext'
import { BillDrive, startingChoice, useDriveStatus, type DriveChoice } from '../../components/billing/BillDrive'
import { BillFiling } from '../../components/billing/BillFiling'
import { BillFontPicker } from '../../components/billing/BillFontPicker'
import { BillBar } from '../../components/billing/BillBar'
import { useNarrow } from '../../hooks/useNarrow'
import { LineCard, PaperDesk, StepBar, StepCard } from '../../components/billing/lumenBill'
import { useLumen } from '../../lumen/useLumen'
import { DEFAULT_FONT, fontLabel } from '../../billing/billFonts'
import type { BillCase, BillProfile, BillProfileEdits, BillView, ExtraCharge, HeaderField, LineSetup, ManualFigures, SavedBill } from '../../types'

/** The width from which the bill sits beside the form (the same figure as `min-[1500px]` in the markup). */
const SIDE_BY_SIDE = '(min-width: 1500px)'

const todayIso = () => {
  const now = new Date()
  return `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, '0')}-${String(now.getDate()).padStart(2, '0')}`
}

/** Bills are usually raised the month after the service, so that is the starting choice. */
const lastMonth = () => {
  const now = new Date()
  const prior = new Date(now.getFullYear(), now.getMonth() - 1, 1)
  return `${prior.getFullYear()}-${String(prior.getMonth() + 1).padStart(2, '0')}`
}

/** The month after an ISO date, as YYYY-MM: the month a repeat bill is for. */
const monthAfter = (iso: string) => {
  const [year, month] = iso.slice(0, 7).split('-').map(Number)
  const next = new Date(year, month, 1)
  return `${next.getFullYear()}-${String(next.getMonth() + 1).padStart(2, '0')}`
}

const blankLine = (): LineInput => ({ particulars: '', qty: '', rate: '', days: '', fields: {} })

/** A saved line as the editor holds it: every number as text, the way it is typed. */
type SavedLine = {
  particulars: string
  qty: number | string | null
  rate: number | string | null
  days?: number | string | null
  fields?: Record<string, string>
  skip?: string[]
  manual?: boolean
  amount?: number | string
}
/** `keepManual`: an amount that was entered by hand comes back too (editing the bill); a repeat bill is calculated afresh. */
const lineFrom = (l: SavedLine, keepManual = false): LineInput => ({
  particulars: l.particulars,
  qty: l.qty === null || l.qty === undefined ? '' : String(l.qty),
  rate: l.rate === null || l.rate === undefined ? '' : String(l.rate),
  days: l.days === null || l.days === undefined ? '' : String(l.days),
  fields: l.fields ?? {},
  skip: (l.skip ?? []).filter((key): key is 'epf' | 'esic' | 'service' => key === 'epf' || key === 'esic' || key === 'service'),
  ...(keepManual && l.manual ? { manual: String(l.amount ?? '') } : {}),
})

/** The lines as sent to the server: a blank one is left out, and only the values of the bill's own columns are kept. */
const linesToSend = (lines: LineInput[], setup: LineSetup) =>
  lines
    .map(({ manual, skip, ...l }) => ({
      ...l,
      days: setup.basis === 'unit' ? '' : (l.days ?? ''),
      fields: Object.fromEntries(setup.columns.map((column) => [column.key, l.fields?.[column.key] ?? ''])),
      amount_manual: manual ?? '',
      skip: setup.charge_by_line ? (skip ?? []) : [],
    }))
    .filter(
      (l) =>
        l.particulars.trim() || l.qty.trim() || l.rate.trim() || l.days.trim() || l.amount_manual.trim() || Object.values(l.fields).some((value) => value.trim()),
    )

/** The charges and taxes every bill starts with. Any of them can be removed from a bill, and put back. */
type StandardKey = keyof BillRates
const STANDARD: { key: StandardKey; label: string; tax: boolean }[] = [
  { key: 'epf_pct', label: 'EPFO', tax: false },
  { key: 'esic_pct', label: 'ESIC', tax: false },
  { key: 'service_pct', label: 'Service charges', tax: false },
  { key: 'cgst_pct', label: 'CGST', tax: true },
  { key: 'sgst_pct', label: 'SGST', tax: true },
]
const MAX_EXTRA_CHARGES = 6 // the server's limits
const MAX_HEADER_FIELDS = 6
const MAX_PARTY_FIELDS = 6

/** One row of the charges list: a standard charge (`std` set) or a charge the user named. */
type ChargeRow = { id: number; std: StandardKey | null; label: string; kind: 'pct' | 'amount'; value: string; manual: string }

/** The figure a standard charge's amount is entered as (billing.MANUAL_KEYS). */
const MANUAL_OF: Record<StandardKey, ManualKey> = {
  epf_pct: 'epf_amount',
  esic_pct: 'esic_amount',
  service_pct: 'service_amount',
  cgst_pct: 'cgst_amount',
  sgst_pct: 'sgst_amount',
}

let nextRowId = 1
const standardRow = (key: StandardKey, value: string, manual = ''): ChargeRow => ({
  id: nextRowId++,
  std: key,
  label: STANDARD.find((item) => item.key === key)?.label ?? key,
  kind: 'pct',
  value,
  manual,
})
const customRow = (label = '', kind: 'pct' | 'amount' = 'pct', value = ''): ChargeRow => ({ id: nextRowId++, std: null, label, kind, value, manual: '' })

/** The rows a saved bill shows: a standard charge at 0% is one the bill left off, so it has no row. A new bill has them all. */
function rowsFrom(saved: Record<string, number> | null, extras: ExtraCharge[] | undefined, entered: ManualFigures = {}): ChargeRow[] {
  const rows = STANDARD.filter((item) => !saved || !(item.key in saved) || Number(saved[item.key]) > 0 || MANUAL_OF[item.key] in entered).map((item) =>
    standardRow(item.key, String(saved && item.key in saved ? saved[item.key] : DEFAULT_RATES[item.key]), String(entered[MANUAL_OF[item.key]]?.value ?? '')),
  )
  return [...rows, ...(extras ?? []).map((charge) => customRow(charge.label, charge.kind, String(charge.value)))]
}

function Section({ title, hint, children, id, number }: { title: string; hint?: string; children: React.ReactNode; id?: string; number?: number }) {
  const lumen = useLumen()
  if (lumen && id && number) {
    return (
      <StepCard id={id} number={number} title={title} hint={hint}>
        {children}
      </StepCard>
    )
  }
  return (
    <section className="rounded-xl border border-[color:var(--color-border)] bg-surface p-4">
      <h2 className="t-h3 text-[color:var(--color-text)]">{title}</h2>
      {hint && <p className="mt-0.5 text-xs text-[color:var(--color-text-muted)]">{hint}</p>}
      <div className="mt-3 space-y-3">{children}</div>
    </section>
  )
}

/** Rows of named details (a name and a value) that can be added and removed. Used for the header and for the client. */
function NamedFields({
  fields,
  onChange,
  max,
  addLabel,
  namePlaceholder,
}: {
  fields: HeaderField[]
  onChange: (next: HeaderField[]) => void
  max: number
  addLabel: string
  namePlaceholder: string
}) {
  const set = (index: number, patch: Partial<HeaderField>) =>
    onChange(fields.map((field, i) => (i === index ? { ...field, ...patch } : field)))
  return (
    <>
      <div className="space-y-2">
        {fields.map((field, index) => (
          <div key={index} className="flex items-center gap-2">
            <Input
              className="w-2/5 min-w-0"
              aria-label="Detail name"
              placeholder={namePlaceholder}
              maxLength={30}
              value={field.label}
              onChange={(e) => set(index, { label: e.target.value })}
            />
            <Input
              className="min-w-0 flex-1"
              aria-label={`${field.label || 'Detail'} value`}
              placeholder="Value"
              maxLength={80}
              value={field.value}
              onChange={(e) => set(index, { value: e.target.value })}
            />
            <button
              type="button"
              aria-label={`Remove ${field.label || 'detail'}`}
              onClick={() => onChange(fields.filter((_, i) => i !== index))}
              className="rounded p-1.5 text-[color:var(--color-text-faint)] hover:bg-muted hover:text-negative"
            >
              <Trash2 className="h-4 w-4" />
            </button>
          </div>
        ))}
      </div>
      <Button
        variant="secondary"
        size="sm"
        disabled={fields.length >= max}
        onClick={() => onChange([...fields, { label: '', value: '' }])}
      >
        <Plus className="h-4 w-4" /> {addLabel}
      </Button>
    </>
  )
}

/**
 * Under a standard charge: what the calculation gives, and a box to enter the amount yourself. An amount that differs from the calculation is
 * accepted and saved as entered, with a warning, so a bill can follow a figure agreed with the client.
 */
function ChargeAmount({
  row,
  auto,
  base,
  linesTotal,
  basis,
  onChange,
}: {
  row: ChargeRow
  /** What the calculation gives; null while the lines are not complete enough to work it out (an amount can still be entered). */
  auto: number | null
  base: number | null
  linesTotal: number
  /** What the base is of, after "on ₹ x". */
  basis: string
  onChange: (value: string) => void
}) {
  const typed = row.manual.trim() !== ''
  const differs = typed && auto !== null && Math.abs(Number(row.manual) - auto) >= 0.005
  const name = MANUAL_NAMES[MANUAL_OF[row.std as StandardKey]]
  return (
    <div className="mt-1 space-y-1 pr-9">
      <div className="flex flex-wrap items-center justify-end gap-2 text-xs text-[color:var(--color-text-muted)]">
        <span>
          Calculated: <span className="tabular-nums">{auto === null ? '₹ — (fill in the lines)' : `₹ ${money(auto)}`}</span>
          {base !== null && Math.abs(base - linesTotal) >= 0.005 && <> on ₹ {money(base)}{basis}</>}
        </span>
        <MoneyInput
          className="w-36 text-right"
          words={false}
          aria-label={`${name} amount, entered instead of calculated`}
          placeholder="Enter amount"
          value={row.manual}
          onChange={onChange}
        />
        {typed && (
          <button type="button" className="underline hover:text-[color:var(--color-text)]" onClick={() => onChange('')}>
            Use calculated
          </button>
        )}
      </div>
      {differs && (
        <p className="text-right text-xs text-warning">
          This does not match the calculation (₹ {money(auto as number)}). It will be saved as entered: ₹ {money(Number(row.manual))}.
        </p>
      )}
    </div>
  )
}

const halfFilled = (fields: HeaderField[]) => fields.some((field) => Boolean(field.label.trim()) !== Boolean(field.value.trim()))
const filled = (fields: HeaderField[]) => fields.filter((field) => field.label.trim() || field.value.trim())

/** Raises a new bill, or with a bill id in the address, edits that bill into a new version. */
export function BillEditorPage() {
  const { id } = useParams()
  const editing = Boolean(id)
  const [search] = useSearchParams()
  /** A new bill can start as a copy of an earlier one: ?from=<bill id>&month=YYYY-MM. */
  const copyFrom = id ? null : search.get('from')
  const copyMonth = search.get('month')
  const { user } = useAuth()
  const navigate = useNavigate()
  const canWrite = Boolean(user?.can_billing_write)

  const [cases, setCases] = useState<BillCase[]>([])
  const [profile, setProfile] = useState<BillProfile | null>(null)
  /** Today's template (what a detail can be put back to), and the details this bill prints differently from `profile`. */
  const [template, setTemplate] = useState<BillProfile | null>(null)
  const [own, setOwn] = useState<BillProfileEdits>({})
  const [original, setOriginal] = useState<SavedBill | null>(null)
  const [loadError, setLoadError] = useState('')
  const [showTemplate, setShowTemplate] = useState(false)

  const [billDate, setBillDate] = useState(todayIso)
  const [month, setMonth] = useState(lastMonth)
  const [caseCode, setCaseCode] = useState('')
  const [reason, setReason] = useState('')
  const [partyName, setPartyName] = useState('')
  const [partyGstin, setPartyGstin] = useState('')
  const [partyAddress, setPartyAddress] = useState('')
  const [partyState, setPartyState] = useState('')
  const [refNo, setRefNo] = useState('')
  const [refDate, setRefDate] = useState('')
  const [location, setLocation] = useState('')
  const [description, setDescription] = useState('')
  const [lines, setLines] = useState<LineInput[]>([blankLine(), blankLine()])
  /** How the lines are worked out and laid out (quantity x rate unless the bill says otherwise). */
  const [setup, setSetup] = useState<LineSetup>(UNIT_SETUP)
  const [tenderId, setTenderId] = useState('')
  const [tenderDate, setTenderDate] = useState('')
  const [charges, setCharges] = useState<ChargeRow[]>(() => rowsFrom(null, []))
  const [hidden, setHidden] = useState<string[]>([])
  /** This bill's own typeface and size; empty follows the company's setting (a new bill only: an issued bill's is changed on its page). */
  const [fontFamily, setFontFamily] = useState('')
  const [fontSize, setFontSize] = useState('')
  /** The Document Center folder chosen for a new bill ('' is where Orion files it by itself). */
  const [filingNode, setFilingNode] = useState('')
  /** Also save the new bill to Google Drive: starts as the company's setting says, once the setting is known. */
  const driveStatus = useDriveStatus()
  const [drive, setDrive] = useState<DriveChoice>({ save: false, folder: null })
  const driveStarted = useRef(false)
  useEffect(() => {
    if (!driveStatus || driveStarted.current) return
    driveStarted.current = true
    setDrive(startingChoice(driveStatus))
  }, [driveStatus])
  const [headerFields, setHeaderFields] = useState<HeaderField[]>([])
  const [partyFields, setPartyFields] = useState<HeaderField[]>([])
  const [prefilledFrom, setPrefilledFrom] = useState('')
  /** Whose details are in the party boxes: the case's client, or the client's group. Empty when the bill is being edited and nothing was chosen. */
  const [partyOf, setPartyOf] = useState<'client' | 'group' | ''>('client')
  const [copiedFrom, setCopiedFrom] = useState<SavedBill | null>(null)
  const [nextNumber, setNextNumber] = useState('')
  const [saving, setSaving] = useState(false)
  // One key for this form, kept for every attempt at saving it: if the connection drops and the person tries again, or clicks twice,
  // the server saves one bill. A ref, not state: state is not updated until the next render, so a second click in the same instant
  // would get past a `saving` check (the button's loading flag) and make a second invoice.
  const idemKey = useRef(newIdempotencyKey())
  const savingRef = useRef(false)
  const [error, setError] = useState('')

  /** Start the charges and the hidden parts from a bill's saved settings, or from the defaults when there is none. */
  const loadSettings = (
    source: {
      manual_figures?: ManualFigures
      rates: Record<string, number>
      extra_charges?: ExtraCharge[]
      hidden?: string[]
      header_fields?: HeaderField[]
      line_setup?: LineSetup
      tender_id?: string | null
      tender_start_date?: string | null
    } | null,
    keepManual = false,
  ) => {
    setCharges(rowsFrom(source?.rates ?? null, source?.extra_charges, keepManual ? source?.manual_figures : {}))
    setHidden(source?.hidden ?? [])
    setHeaderFields(source?.header_fields ?? [])
    setSetup(source?.line_setup && source.line_setup.labels ? { ...UNIT_SETUP, ...source.line_setup } : UNIT_SETUP)
    setTenderId(source?.tender_id ?? '')
    setTenderDate(source?.tender_start_date ?? '')
  }

  useEffect(() => {
    api.billingCases().then((r) => setCases(r.cases)).catch((e: Error) => setLoadError(e.message))
    if (id) {
      api.billingProfile().then(setTemplate).catch(() => setTemplate(null)) // only to offer "Use the template's"
      // An edit keeps the letterhead the bill was issued with.
      api
        .bill(id)
        .then((bill) => {
          setOriginal(bill)
          setProfile(bill.profile)
          setBillDate(bill.bill_date)
          setMonth(bill.service_month.slice(0, 7))
          setCaseCode(bill.case_code ?? '')
          setPartyOf('')
          setPartyName(bill.party_name)
          setPartyGstin(bill.party_gstin ?? '')
          setPartyFields(bill.party_fields ?? [])
          setPartyAddress(bill.party_address ?? '')
          setPartyState(bill.party_state ?? '')
          setRefNo(bill.ref_no ?? '')
          setRefDate(bill.ref_date ?? '')
          setLocation(bill.location ?? '')
          setDescription(bill.service_description ?? '')
          setLines(bill.lines.map((l) => lineFrom(l, true)))
          loadSettings(bill, true)
        })
        .catch((e: Error) => setLoadError(e.message))
      return
    }
    // A copy takes everything that repeats from the earlier bill. The letterhead is today's, the
    // bill date is today, and the month moves on. Quantities are for the user to check.
    Promise.all([api.billingProfile(), copyFrom ? api.bill(copyFrom) : Promise.resolve(null)])
      .then(([p, source]) => {
        setProfile(p)
        setTemplate(p)
        if (!source) {
          setDescription((current) => current || p.default_service_description)
          return
        }
        setCopiedFrom(source)
        setOwn(source.profile_overrides ?? {})
        setCaseCode(source.case_code ?? '')
        setMonth(copyMonth ?? monthAfter(source.service_month))
        setPartyOf('')
        setPartyName(source.party_name)
        setPartyGstin(source.party_gstin ?? '')
        setPartyFields(source.party_fields ?? [])
        setPartyAddress(source.party_address ?? '')
        setPartyState(source.party_state ?? '')
        setRefNo(source.ref_no ?? '')
        setRefDate(source.ref_date ?? '')
        setLocation(source.location ?? '')
        setDescription(source.service_description ?? p.default_service_description)
        setLines(source.lines.map((l) => lineFrom(l)))
        loadSettings(source)
      })
      .catch((e: Error) => setLoadError(e.message))
  }, [id, copyFrom, copyMonth])

  useEffect(() => {
    if (!billDate || editing) return
    api
      .billingNextNumber(billDate)
      .then((r) => setNextNumber(r.bill_number))
      .catch(() => setNextNumber(''))
  }, [billDate, editing])

  const options = useMemo(
    () =>
      cases.map((c) => ({
        id: c.case_code,
        label: [c.case_name, c.client_name ?? 'no client'].join(' — '),
      })),
    [cases],
  )
  const billCase = cases.find((c) => c.case_code === caseCode)

  /** Puts the details of the case's client, or of the client's group, in the party boxes. Whatever was typed there is replaced. */
  const fillParty = (picked: BillCase, of: 'client' | 'group') => {
    const group = of === 'group' ? picked.group : null
    const party = group ? group.last_party : picked.last_party
    setPartyName((group ? group.billing_name : picked.billing_name) ?? party?.party_name ?? (group ? group.client_name : picked.client_name) ?? '')
    setPartyAddress((group ? group.billing_address : picked.billing_address) ?? party?.party_address ?? '')
    setPartyState((group ? group.state : picked.state) ?? party?.party_state ?? '')
    setPartyGstin((group ? group.gstin : picked.gstin) ?? party?.party_gstin ?? '')
    setPartyFields(party?.party_fields ?? [])
    setPartyOf(of)
  }

  const pickCase = (code: string | null) => {
    setCaseCode(code ?? '')
    const picked = cases.find((c) => c.case_code === code)
    // An edit only re-tags the bill: what is printed stays as it was until it is changed by hand.
    if (!picked || editing) {
      setPartyOf(editing ? '' : 'client')
      return
    }
    const last = picked.last
    fillParty(picked, 'client')
    setLocation(last?.location ?? picked.case_name)
    setDescription(last?.service_description ?? profile?.default_service_description ?? '')
    if (last) {
      setLines(last.lines.length ? last.lines.map((l) => lineFrom(l)) : [blankLine(), blankLine()])
      loadSettings(last)
      setPrefilledFrom(last.bill_number)
    } else {
      setLines([blankLine(), blankLine()])
      loadSettings(null)
      setPrefilledFrom('')
    }
    setOwn(last?.profile_overrides ?? {}) // the bank details and the like this case's last bill printed differently
    // The tender of the case's opportunity is the source of the tender fields; the last bill's stand in when it has none.
    if (picked.tender_id) setTenderId(picked.tender_id)
    if (picked.tender_start_date) setTenderDate(picked.tender_start_date.slice(0, 10))
  }

  /** The percentages the bill is worked out and saved with: a standard charge with no row is 0%. */
  const rates = useMemo<BillRates>(
    () =>
      Object.fromEntries(
        STANDARD.map((item) => [item.key, charges.find((row) => row.std === item.key)?.value ?? '0']),
      ) as BillRates,
    [charges],
  )
  const extras = useMemo<ExtraInput[]>(
    () => charges.filter((row) => !row.std).map((row) => ({ label: row.label, kind: row.kind, value: row.value })),
    [charges],
  )
  /** The amounts entered instead of calculated, by figure. */
  const manual = useMemo<ManualInput>(
    () => Object.fromEntries(charges.filter((row) => row.std && row.manual.trim()).map((row) => [MANUAL_OF[row.std as StandardKey], row.manual])),
    [charges],
  )
  const calc = useMemo(() => calculate(lines, rates, extras, setup, month, manual), [lines, rates, extras, setup, month, manual])
  const figures = calc.ok ? calc.figures : null

  const setRow = (id: number, patch: Partial<ChargeRow>) =>
    setCharges((current) => current.map((row) => (row.id === id ? { ...row, ...patch } : row)))
  const removedStandard = STANDARD.filter((item) => !charges.some((row) => row.std === item.key))
  const customCount = charges.filter((row) => !row.std).length
  const toggleShown = (key: string, shown: boolean) =>
    setHidden((current) => (shown ? current.filter((k) => k !== key) : [...current.filter((k) => k !== key), key]))

  const companyFont = { family: profile?.font_family ?? DEFAULT_FONT.family, size: profile?.font_size ?? DEFAULT_FONT.size }
  const font = editing
    ? original?.font
    : { family: fontFamily || companyFont.family, size: fontSize ? Number(fontSize) : companyFont.size }

  const preview: BillView | null = profile && {
    number: original?.bill_number ?? null,
    status: 'Draft',
    bill_date: billDate,
    service_month: `${month}-01`,
    party_name: partyName,
    party_gstin: partyGstin.trim().toUpperCase() || null,
    party_fields: partyFields.filter((field) => field.label.trim() && field.value.trim()),
    party_address: partyAddress || null,
    party_state: partyState || null,
    ref_no: refNo || null,
    ref_date: refDate || null,
    tender_id: tenderId.trim() || null,
    tender_start_date: tenderDate || null,
    line_setup: setup,
    manual_figures: figures?.manual_figures,
    location: location || null,
    service_description: description || null,
    lines: figures?.lines ?? [],
    extra_charges: figures?.extra_charges ?? [],
    hidden,
    font,
    header_fields: headerFields.filter((field) => field.label.trim() && field.value.trim()),
    rates: {
      epf_pct: Number(rates.epf_pct) || 0,
      esic_pct: Number(rates.esic_pct) || 0,
      service_pct: Number(rates.service_pct) || 0,
      cgst_pct: Number(rates.cgst_pct) || 0,
      sgst_pct: Number(rates.sgst_pct) || 0,
    },
    lines_total: figures?.lines_total ?? 0,
    epf_amount: figures?.epf_amount ?? 0,
    esic_amount: figures?.esic_amount ?? 0,
    sub_total: figures?.sub_total ?? 0,
    service_amount: figures?.service_amount ?? 0,
    taxable_total: figures?.taxable_total ?? 0,
    cgst_amount: figures?.cgst_amount ?? 0,
    sgst_amount: figures?.sgst_amount ?? 0,
    round_off: figures?.round_off ?? 0,
    grand_total: figures?.grand_total ?? 0,
    profile: { ...profile, ...own },
  }

  const lumen = useLumen()
  /** Wide enough for the bill to sit beside the form at a size that can be read; below that the bar's Preview opens it in a window. */
  const sideBySide = useNarrow(SIDE_BY_SIDE)
  const setLine = (index: number, patch: Partial<LineInput>) =>
    setLines((current) => current.map((line, i) => (i === index ? { ...line, ...patch } : line)))

  const blocker = !canWrite
    ? 'You can view bills but not change them.'
    : !caseCode
      ? 'Choose the case.'
      : billCase && !billCase.client_code
        ? 'That case has no client. Set the client on the case first.'
        : !partyName.trim()
          ? 'The bill needs a party name.'
          : !calc.ok
            ? calc.reason
            : setup.columns.some((column) => !column.label.trim())
              ? 'Name each extra column of the lines, or remove it.'
              : halfFilled(headerFields) || halfFilled(partyFields)
              ? 'Give each extra detail a name and a value, or remove it.'
              : editing && !reason.trim()
                ? 'Say what was changed and why.'
                : ''

  // What the Lumen editor shows of how far the bill has come: the same conditions the blocker above checks, one by one.
  const steps = [
    { id: 'case', label: 'Case', done: Boolean(caseCode) && Boolean(partyName.trim()) },
    { id: 'details', label: 'Details', done: Boolean(billDate) && Boolean(month) },
    { id: 'lines', label: 'Lines', done: calc.ok },
    { id: 'charges', label: 'Charges', done: calc.ok },
    { id: 'extras', label: 'Extras', done: !halfFilled(headerFields) && !halfFilled(partyFields) },
  ]

  const save = async () => {
    if (savingRef.current) return
    savingRef.current = true
    setSaving(true)
    setError('')
    try {
      const body = {
        bill_date: billDate,
        service_month: month,
        case_code: caseCode,
        party_name: partyName,
        party_gstin: partyGstin || null,
        party_fields: filled(partyFields),
        party_address: partyAddress || null,
        party_state: partyState || null,
        ref_no: refNo || null,
        ref_date: refDate || null,
        tender_id: tenderId.trim() || null,
        tender_start_date: tenderDate || null,
        line_setup: setup,
        manual_figures: manual,
        profile_fields: own,
        location: location || null,
        service_description: description || null,
        lines: linesToSend(lines, setup),
        rates,
        extra_charges: extras.filter((extra) => extra.label.trim() || extra.value.trim()),
        hidden,
        header_fields: filled(headerFields),
        ...(id ? {} : { font_family: fontFamily || null, font_size: fontSize ? Number(fontSize) : null, filing_node: filingNode || null, drive_save: driveStatus?.connected ? drive.save : null, drive_folder_id: drive.save ? (drive.folder?.id ?? null) : null }),
      }
      const saved = id ? await api.updateBill(id, { ...body, reason }, idemKey.current) : await api.createBill(body, idemKey.current)
      navigate(`/utility/billing/${saved.id}?saved=${id ? 'edit' : 'new'}`, { replace: true })
    } catch (e) {
      setError((e as Error).message)
    } finally {
      savingRef.current = false
      setSaving(false)
    }
  }

  if (user && !canWrite) return <Navigate to="/utility/billing" replace />

  return (
    <div className="mx-auto max-w-3xl space-y-4 min-[1500px]:max-w-none">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <Link
          to={id ? `/utility/billing/${id}` : '/utility/billing'}
          className="inline-flex items-center gap-1 text-sm font-medium text-[color:var(--color-text-muted)] hover:text-[color:var(--color-text)]"
        >
          <ChevronLeft className="h-4 w-4" /> {original ? `Bill ${original.bill_number}` : 'Bills'}
        </Link>
        {!editing && (
          <Button variant="ghost" size="sm" onClick={() => setShowTemplate(true)}>
            <Settings2 className="h-4 w-4" /> Bill template
          </Button>
        )}
      </div>

      {loadError && <Alert variant="error">{loadError}</Alert>}
      {original && original.status !== 'Issued' && (
        <Alert variant="error">Bill {original.bill_number} is cancelled and cannot be edited.</Alert>
      )}
      {original && original.status === 'Issued' && (
        <Alert variant="info">
          You are editing bill {original.bill_number}. It keeps its number, and saving makes version{' '}
          {original.version_no + 1}. The version it replaces stays viewable on the bill.
        </Alert>
      )}

      {copiedFrom && (
        <Alert variant="info">
          A copy of bill <BillNumber number={copiedFrom.bill_number} code={String(copiedFrom.id)} />, which was for {formatMonth(copiedFrom.service_month)}. It is filled in
          for {formatMonth(`${month}-01`)}. Check the quantities and rates for the new month before issuing it.
        </Alert>
      )}

      {lumen && <StepBar steps={steps} />}

      <div className="min-[1500px]:grid min-[1500px]:grid-cols-[minmax(0,30rem)_minmax(0,1fr)] min-[1500px]:items-start min-[1500px]:gap-5">
        <div className="min-w-0">
        <div className="space-y-4">
          <Section id="case" number={1} title="Case" hint="A bill is raised for a case. The client is the case's client.">
            <Field label="Case" required>
              <SearchSelect
                value={caseCode}
                options={options}
                onChange={pickCase}
                placeholder="Search cases…"
                allowEmpty={false}
              />
            </Field>
            {billCase && (
              <p className="text-xs text-[color:var(--color-text-muted)]">
                Client:{' '}
                <span className="font-medium text-[color:var(--color-text)]">
                  {billCase.client_name ?? 'none set on this case'}
                </span>
              </p>
            )}
            {billCase?.group && (
              <div className="space-y-1.5">
                <Segmented
                  label="Whose details are printed on the bill"
                  value={partyOf}
                  options={[
                    { id: 'client', label: 'The client' },
                    { id: 'group', label: `Client group: ${billCase.group.client_name ?? billCase.group.client_code}` },
                  ]}
                  onChange={(next) => next && fillParty(billCase, next)}
                />
                <p className="text-xs text-[color:var(--color-text-muted)]">
                  {billCase.client_name} belongs to the group {billCase.group.client_name ?? billCase.group.client_code}. The bill
                  is still raised for {billCase.client_name}; choosing the group replaces the party boxes below with the group's
                  billing details from its client record.
                </p>
              </div>
            )}
            {original && !original.case_code && !caseCode && (
              <p className="text-xs text-warning">
                This bill was raised before bills were tagged to cases
                {original.legacy_client_ledger ? `, for ${original.legacy_client_ledger}` : ''}. Choose its case.
              </p>
            )}
            {prefilledFrom && (
              <Alert variant="info">
                Filled in from the last bill for this case ({prefilledFrom}). Check the lines, quantities and rates
                before saving.
              </Alert>
            )}
            {!editing && billCase?.client_code && partyOf !== '' && (() => {
              const source = partyOf === 'group' && billCase.group ? billCase.group : billCase
              return !source.gstin && !source.last_party?.party_gstin
            })() && (
              <p className="text-xs text-warning">
                {partyOf === 'group' ? 'This client group' : 'This client'} has no GSTIN yet. Add it to the client under
                Operational Data and it fills in on every bill.
              </p>
            )}
            <Field label="Party name on the bill" required>
              <Input value={partyName} onChange={(e) => setPartyName(e.target.value)} />
            </Field>
            <div className="grid gap-3 sm:grid-cols-2">
              <Field label="Party GSTIN">
                <Input
                  value={partyGstin}
                  maxLength={15}
                  onChange={(e) => setPartyGstin(e.target.value.toUpperCase())}
                  placeholder="23ABCDE1234F1Z5"
                />
              </Field>
              <Field label="State">
                <Input value={partyState} onChange={(e) => setPartyState(e.target.value)} />
              </Field>
            </div>
            <Field label="Address">
              <Input value={partyAddress} onChange={(e) => setPartyAddress(e.target.value)} />
            </Field>
            <div>
              <p className="mb-1.5 text-xs font-medium text-[color:var(--color-text-muted)]">
                Extra client details, printed under the GSTIN
              </p>
              <div className="space-y-2">
                <NamedFields
                  fields={partyFields}
                  onChange={setPartyFields}
                  max={MAX_PARTY_FIELDS}
                  addLabel="Add a client detail"
                  namePlaceholder="Name, for example State code"
                />
              </div>
            </div>
          </Section>

          <Section id="details" number={2} title="Bill details">
            <div className="grid gap-3 sm:grid-cols-2">
              <Field label="Bill date" required>
                <Input type="date" value={billDate} onChange={(e) => setBillDate(e.target.value)} />
              </Field>
              <Field label="Bill is for the month" required>
                <Input type="month" value={month} onChange={(e) => setMonth(e.target.value)} />
              </Field>
            </div>
            <div className="grid gap-3 sm:grid-cols-2">
              <Field label="Your ref. no.">
                <Input value={refNo} onChange={(e) => setRefNo(e.target.value)} />
              </Field>
              <Field label="Ref. date">
                <Input type="date" value={refDate} onChange={(e) => setRefDate(e.target.value)} />
              </Field>
            </div>
            <div className="grid gap-3 sm:grid-cols-2">
              <Field label="Tender ID">
                <Input value={tenderId} maxLength={80} onChange={(e) => setTenderId(e.target.value)} />
              </Field>
              <Field label="Tender start date">
                <Input type="date" value={tenderDate} onChange={(e) => setTenderDate(e.target.value)} />
              </Field>
            </div>
            {(tenderId.trim() || tenderDate) && (
              <div className="flex flex-wrap gap-x-5 gap-y-1.5">
                <Checkbox label="Print the tender ID on the bill" checked={!hidden.includes('tender_id')} onChange={(shown) => toggleShown('tender_id', shown)} />
                <Checkbox label="Print the tender start date on the bill" checked={!hidden.includes('tender_date')} onChange={(shown) => toggleShown('tender_date', shown)} />
              </div>
            )}
            <Field label="Location">
              <Input value={location} onChange={(e) => setLocation(e.target.value)} />
            </Field>
            <Field label="Service description">
              <Textarea rows={2} value={description} onChange={(e) => setDescription(e.target.value)} />
            </Field>
          </Section>

          <Section
            id="lines"
            number={3}
            title="Lines"
            hint={
              setup.basis === 'unit'
                ? 'Quantity × rate. Amounts are worked out for you.'
                : setup.basis === 'daily'
                  ? 'Rate per day × days. Amounts are worked out for you.'
                  : 'Monthly rate × days. Amounts are worked out for you.'
            }
          >
            <LineSetupEditor
              setup={setup}
              month={month}
              onChange={(next) => {
                setSetup(next)
                // Lines that were left out of a charge are part of it again when the choice is turned off.
                if (!next.charge_by_line) setLines((current) => current.map((l) => (l.skip?.length ? { ...l, skip: [] } : l)))
              }}
            />
            {lumen ? (
              <div className="space-y-3">
                {lines.map((line, index) => (
                  <LineCard
                    key={index}
                    index={index}
                    count={lines.length}
                    line={line}
                    setup={setup}
                    amount={lineAmount(line, setup, month)}
                    onChange={(patch) => setLine(index, patch)}
                    onRemove={() => setLines((c) => (c.length > 1 ? c.filter((_, i) => i !== index) : [blankLine()]))}
                    onMove={(direction) =>
                      setLines((c) => {
                        const to = index + direction
                        if (to < 0 || to >= c.length) return c
                        const next = [...c]
                        ;[next[index], next[to]] = [next[to], next[index]]
                        return next
                      })
                    }
                  />
                ))}
              </div>
            ) : (
            <div className="space-y-2">
              {lines.map((line, index) => (
                <div key={index} className="space-y-1.5 rounded-lg border border-[color:var(--color-border)] p-2">
                  <div className="flex items-center gap-2">
                    <span className="w-5 shrink-0 text-center text-xs font-semibold text-[color:var(--color-text-muted)]">{index + 1}</span>
                    <Input
                      aria-label={`Line ${index + 1} description`}
                      placeholder="Skilled (Supervisor)"
                      value={line.particulars}
                      onChange={(e) => setLine(index, { particulars: e.target.value })}
                    />
                    <button
                      type="button"
                      aria-label={`Remove line ${index + 1}`}
                      onClick={() => setLines((c) => (c.length > 1 ? c.filter((_, i) => i !== index) : [blankLine()]))}
                      className="rounded p-1.5 text-[color:var(--color-text-faint)] hover:bg-muted hover:text-negative"
                    >
                      <Trash2 className="h-4 w-4" />
                    </button>
                  </div>
                  <div className="pl-7">
                    <LineFields index={index} line={line} setup={setup} amount={lineAmount(line, setup, month)} onChange={(patch) => setLine(index, patch)} />
                  </div>
                </div>
              ))}
            </div>
            )}
            <Button variant="secondary" size="sm" onClick={() => setLines((c) => [...c, blankLine()])}>
              <Plus className="h-4 w-4" /> Add line
            </Button>
            <Checkbox
              label="Show a total row under the lines (adds up the quantity, days and amount)"
              checked={setup.totals_row}
              onChange={(totals_row) => setSetup({ ...setup, totals_row })}
            />
          </Section>

          <Section
            id="charges"
            number={4}
            title="Charges and tax"
            hint="Remove a charge this bill does not have, such as EPFO and ESIC on a vehicle rental, or add one of your own. Charges are on the lines total and GST is on everything before it."
          >
            <div className="space-y-2">
              {[
                ...STANDARD.filter((item) => !item.tax).flatMap((item) => charges.filter((row) => row.std === item.key)),
                ...charges.filter((row) => !row.std),
                ...STANDARD.filter((item) => item.tax).flatMap((item) => charges.filter((row) => row.std === item.key)),
              ].map((row) => (
                <div key={row.id}>
                <div className="flex items-center gap-2">
                  {row.std ? (
                    <span className="min-w-0 flex-1 text-sm text-[color:var(--color-text)]">{row.label}</span>
                  ) : (
                    <Input
                      className="min-w-0 flex-1"
                      aria-label="Charge name"
                      placeholder="Name, for example Fuel surcharge"
                      maxLength={60}
                      value={row.label}
                      onChange={(e) => setRow(row.id, { label: e.target.value })}
                    />
                  )}
                  {!row.std && (
                    <select
                      aria-label="Percentage or amount"
                      value={row.kind}
                      onChange={(e) => setRow(row.id, { kind: e.target.value as 'pct' | 'amount' })}
                      className="h-10 rounded-lg border border-[color:var(--color-border)] bg-surface px-2 text-sm text-[color:var(--color-text)]"
                    >
                      <option value="pct">%</option>
                      <option value="amount">₹</option>
                    </select>
                  )}
                  <div className={`flex items-center gap-1.5 ${!row.std && row.kind === 'amount' ? 'w-36' : 'w-24'}`}>
                    {row.kind === 'pct' ? (
                      <Input
                        inputMode="decimal"
                        aria-label={`${row.label || 'Charge'} percentage`}
                        value={row.value}
                        onChange={(e) => setRow(row.id, { value: e.target.value })}
                      />
                    ) : (
                      <MoneyInput
                        aria-label={`${row.label || 'Charge'} amount`}
                        words={false}
                        value={row.value}
                        onChange={(raw) => setRow(row.id, { value: raw })}
                      />
                    )}
                    {row.std && <span className="text-sm text-[color:var(--color-text-muted)]">%</span>}
                  </div>
                  <button
                    type="button"
                    aria-label={`Remove ${row.label || 'charge'}`}
                    onClick={() => setCharges((current) => current.filter((r) => r.id !== row.id))}
                    className="rounded p-1.5 text-[color:var(--color-text-faint)] hover:bg-muted hover:text-negative"
                  >
                    <Trash2 className="h-4 w-4" />
                  </button>
                </div>
                {!row.std && row.kind === 'amount' && wordsOfAmount(row.value) && (
                  <p className="mt-0.5 pr-9 text-right text-xs text-[color:var(--color-text-muted)]">{wordsOfAmount(row.value)}</p>
                )}
                {row.std && (
                  <ChargeAmount
                    row={row}
                    auto={figures ? figures.auto[MANUAL_OF[row.std]] : null}
                    base={
                      !figures ? null : row.std === 'epf_pct' ? figures.bases.epf : row.std === 'esic_pct' ? figures.bases.esic : row.std === 'service_pct' ? figures.bases.service : null
                    }
                    linesTotal={figures?.lines_total ?? 0}
                    basis={row.std === 'service_pct' && setup.service_on === 'lines_epf_esic' ? ' (the lines + EPFO + ESIC)' : ' of the lines'}
                    onChange={(value) => setRow(row.id, { manual: value })}
                  />
                )}
                </div>
              ))}
              {charges.length === 0 && (
                <p className="text-sm text-[color:var(--color-text-muted)]">No charges or tax on this bill.</p>
              )}
            </div>
            {charges.some((row) => row.std === 'service_pct') && (
              <div className="space-y-1">
                <Segmented
                  label="Service charge is taken on"
                  value={setup.service_on ?? 'lines'}
                  options={[
                    { id: 'lines', label: 'The lines' },
                    { id: 'lines_epf_esic', label: 'The lines + EPFO + ESIC' },
                  ]}
                  onChange={(service_on) => setSetup({ ...setup, service_on })}
                />
                <p className="text-xs text-[color:var(--color-text-muted)]">
                  The percentage of the service charge is taken of the lines (those not left out of it){setup.service_on === 'lines_epf_esic' ? ', and of the EPFO and ESIC amounts as well' : ''}.
                </p>
              </div>
            )}
            <div className="flex flex-wrap gap-2">
              {removedStandard.map((item) => (
                <Button
                  key={item.key}
                  variant="secondary"
                  size="sm"
                  onClick={() => setCharges((current) => [...current, standardRow(item.key, DEFAULT_RATES[item.key])])}
                >
                  <Plus className="h-4 w-4" /> {item.label}
                </Button>
              ))}
              <Button
                variant="secondary"
                size="sm"
                disabled={customCount >= MAX_EXTRA_CHARGES}
                onClick={() => setCharges((current) => [...current, customRow()])}
              >
                <Plus className="h-4 w-4" /> Add a charge
              </Button>
            </div>
          </Section>

          <Section
            id="extras"
            number={5}
            title="Extra details at the top"
            hint="Printed with the GSTIN and PAN, for this bill only, for example a vendor code or an MSME number."
          >
            <NamedFields
              fields={headerFields}
              onChange={setHeaderFields}
              max={MAX_HEADER_FIELDS}
              addLabel="Add a detail"
              namePlaceholder="Name, for example Vendor code"
            />
          </Section>

          {!editing && (
            <BillDrive status={driveStatus} value={drive} onChange={setDrive} canChoose={Boolean(user?.can_documents_write)} />
          )}

          {!editing && (
            <BillFiling caseCode={caseCode} billDate={billDate} node={filingNode} canChoose={Boolean(user?.can_documents_write)} onChange={setFilingNode} />
          )}

          {!editing && (
            <details className="rounded-xl border border-[color:var(--color-border)] bg-surface p-4">
              <summary className="cursor-pointer text-sm font-semibold text-[color:var(--color-text)]">
                Text on the bill
                <span className="ml-2 text-xs font-normal text-[color:var(--color-text-muted)]">
                  {fontFamily || fontSize ? fontLabel(font ?? DEFAULT_FONT) : 'As the company sets it'}
                </span>
              </summary>
              <p className="mt-2 text-xs text-[color:var(--color-text-muted)]">
                Choose a larger size or another typeface for this bill. It is used on screen, in print and in the PDF. Leave both on the
                company setting to follow it (changed under Bill template).
              </p>
              <div className="mt-3">
                <BillFontPicker
                  family={fontFamily}
                  size={fontSize}
                  company={companyFont}
                  onChange={(next) => {
                    setFontFamily(next.family)
                    setFontSize(next.size)
                  }}
                />
              </div>
            </details>
          )}

          {profile && <BillOwnDetails base={profile} template={template} own={own} onChange={setOwn} />}

          <details className="rounded-xl border border-[color:var(--color-border)] bg-surface p-4">
            <summary className="cursor-pointer text-sm font-semibold text-[color:var(--color-text)]">
              What shows on the bill
              <span className="ml-2 text-xs font-normal text-[color:var(--color-text-muted)]">
                {hidden.length ? `${hidden.length} left off` : 'Everything shows'}
              </span>
            </summary>
            <p className="mt-2 text-xs text-[color:var(--color-text-muted)]">
              Untick anything this bill should not print, such as the PF and ESI numbers on a vehicle rental. The next
              bill for this case starts the same way.
            </p>
            <div className="mt-3 space-y-3">
              {LAYOUT_GROUPS.map((group) => (
                <div key={group.title}>
                  <p className="text-[11px] font-semibold uppercase tracking-wider text-[color:var(--color-text-faint)]">{group.title}</p>
                  <div className="mt-1.5 grid grid-cols-1 gap-x-4 gap-y-1.5 sm:grid-cols-2">
                    {group.parts.map((part) => (
                      <Checkbox
                        key={part.key}
                        label={part.label}
                        checked={!hidden.includes(part.key)}
                        onChange={(shown) => toggleShown(part.key, shown)}
                      />
                    ))}
                  </div>
                </div>
              ))}
            </div>
            {hidden.length > 0 && (
              <Button variant="ghost" size="sm" className="mt-3" onClick={() => setHidden([])}>
                Show everything
              </Button>
            )}
          </details>
          {editing && (
            <div className="rounded-xl border border-[color:var(--color-border)] bg-surface p-4">
              <Field label="What was changed and why" required>
                <Textarea
                  rows={2}
                  value={reason}
                  maxLength={300}
                  placeholder="Corrected the supervisor rate for July"
                  onChange={(e) => setReason(e.target.value)}
                />
              </Field>
            </div>
          )}
          {error && <Alert variant="error">{error}</Alert>}
        </div>

        <BillBar
          total={figures?.grand_total ?? 0}
          nextNumber={editing ? null : nextNumber}
          saveLabel={editing ? 'Save as new version' : 'Save and issue bill'}
          saving={saving}
          disabled={Boolean(blocker) || (editing && original?.status !== 'Issued')}
          blocker={blocker}
          onSave={save}
          bill={preview}
          previewBeside={sideBySide}
        />
        </div>

        {sideBySide && preview && (
          <aside aria-label="The bill as it will print" className="sticky top-2 max-h-[calc(100dvh-1.5rem)] min-w-0 overflow-y-auto">
            <PaperDesk>
              <BillDocument bill={preview} />
            </PaperDesk>
          </aside>
        )}
      </div>

      <BillTemplateModal
        open={showTemplate}
        canEdit={canWrite}
        onClose={() => setShowTemplate(false)}
        onSaved={(saved) => {
          setProfile(saved)
          setTemplate(saved)
        }}
      />
    </div>
  )
}
