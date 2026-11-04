import type { AppearancePrefs } from './theme/types'

export type ThemePreference = 'light' | 'dark'

/** Every access flag a user can be given, in the order Admin shows them. Keep in step with ACCESS_FLAGS in auth.py. */
export const ACCESS_FLAG_KEYS = [
  'ods_access',
  'ods_write',
  'dw_access',
  'dw_write',
  'tally_access',
  'tally_write',
  'tally_dw_access',
  'tally_dw_write',
  'orion_dashboard_access',
  'tally_dashboard_access',
  'billing_access',
  'billing_write',
  'etl_access',
  'etl_write',
  'letterhead_access',
  'letterhead_write',
  'documents_access',
  'documents_write',
  'bank_access',
  'bank_write',
  'tenders_access',
  'tenders_write',
  'attendance_access',
  'attendance_write',
  'ai_access',
] as const
export type AccessFlag = (typeof ACCESS_FLAG_KEYS)[number]
export type AccessFlags = Record<AccessFlag, boolean>

export interface User {
  id: number
  username: string
  display_name: string
  role: string
  /** When the account was made; the welcome tour opens by itself for an account less than 30 days old. */
  created_timestamp?: string
  ods_access: boolean
  ods_write: boolean
  dw_access: boolean
  dw_write: boolean
  tally_access: boolean
  tally_write: boolean
  tally_dw_access: boolean
  tally_dw_write: boolean
  orion_dashboard_access: boolean
  tally_dashboard_access: boolean
  billing_access: boolean
  billing_write: boolean
  etl_access: boolean
  etl_write: boolean
  letterhead_access: boolean
  letterhead_write: boolean
  documents_access: boolean
  documents_write: boolean
  bank_access: boolean
  bank_write: boolean
  tenders_access: boolean
  tenders_write: boolean
  attendance_access: boolean
  attendance_write: boolean
  ai_access: boolean
  pages: string[]
  can_ods: boolean
  can_ods_write: boolean
  can_dw: boolean
  can_dw_write: boolean
  can_tally: boolean
  can_tally_write: boolean
  can_tally_dw: boolean
  can_tally_dw_write: boolean
  can_billing: boolean
  can_billing_write: boolean
  can_etl: boolean
  can_etl_write: boolean
  can_letterhead: boolean
  can_letterhead_write: boolean
  can_documents: boolean
  can_documents_write: boolean
  can_bank: boolean
  can_bank_write: boolean
  can_tenders: boolean
  can_tenders_write: boolean
  can_attendance: boolean
  can_attendance_write: boolean
  can_ai: boolean
  can_orion_dashboard: boolean
  can_tally_dashboard: boolean
  preferred_theme: ThemePreference | null
  /** The saved appearance settings (see src/theme), or null when the person has never changed them. */
  appearance?: AppearancePrefs | null
  has_avatar: boolean
  avatar_version: number
  avatar_url: string | null
  email?: string | null
  phone?: string | null
  pending_signups?: number
}

export interface FormField {
  label: string
  type: string
  options?: string[]
  depends_on?: string
  source_table?: string
  source_display_column?: string
  source_pk_column?: string
  required?: boolean
  optional?: boolean
  compute_from?: string[]
  compute_op?: 'sum' | 'difference' | 'month_year'
  auto_parts?: string[]
  breakdown?: boolean
  readonly?: boolean
  /** Shown under a read-only field to say where its value comes from. */
  hint?: string
  custom_option?: string
  /** What a person sees for each stored option (the stored value is unchanged). */
  option_labels?: Record<string, string>
  /** An amount of money in rupees: shown with commas as it is typed, with the amount in words under it. */
  money?: boolean
}

/** A file kept against an employee (Aadhaar scan, PAN scan, bank passbook, ...). The file itself is fetched separately. */
export interface EmployeeDocument {
  id: number
  doc_type: string
  title: string | null
  file_name: string
  content_type: string
  size_bytes: number
  uploaded_timestamp: string
  uploaded_by_name: string | null
}

export interface EmployeeDocumentList {
  documents: EmployeeDocument[]
  types: string[]
  /** The file types that can be uploaded, for example ".pdf, .jpg". */
  accepted: string
  max_mb: number
}

export interface EntityMeta {
  name: string
  primary_key: string
  display_column: string
  form_fields: Record<string, FormField>
  /** Asked only when a record is added (an expense's Paid On, Paid From): they record its payment in the same save. Empty for a person who may not change the bank. */
  create_fields?: Record<string, FormField>
  /** Adding one that looks like another is warned about first (an expense). */
  checks_duplicates?: boolean
  merge_key?: string[]
}

/** Dimensions the dashboard can be sliced by. Every chart click sets one of these. */
export const DASHBOARD_DIMENSION_KEYS = [
  'month',
  'business_domain',
  'capability',
  'client',
  'case',
  'state',
  'client_type',
  'priority',
  'case_status',
  'status',
  'expense_type',
  'is_regular',
  'stage',
  'designation',
  'employee_type',
  'salary_paid',
  'car_model',
  'company',
  'voucher_type',
  'fy',
  'cost_centre',
  'income_line',
  'bucket',
  'pay_status',
  'opp_type',
  'driver',
] as const

/** Inclusive calendar bounds. Own control in the header, not a chart click. */
export const DASHBOARD_RANGE_KEYS = ['from', 'to'] as const

export const DASHBOARD_FILTER_KEYS = [
  ...DASHBOARD_DIMENSION_KEYS,
  ...DASHBOARD_RANGE_KEYS,
] as const

export type DashboardFilterKey = (typeof DASHBOARD_FILTER_KEYS)[number]

export type DashboardFilters = Partial<Record<DashboardFilterKey, string>>

export interface FilterChip {
  key: DashboardFilterKey
  label: string
  value: string
  display: string
}

export interface DashboardKpi {
  key: string
  label: string
  value: string
  delta: string
  delta_type: 'positive' | 'negative' | 'neutral'
  hint: string
  tone: string
  /** Numeric change against the comparison window; the string above is its display form. */
  delta_pct?: number | null
  /** What the change is measured against, e.g. "vs Jun 26". */
  compare?: string
  yoy_pct?: number | null
  yoy_label?: string
  /** False where a rise is bad news (credit notes), so the colour follows the meaning. */
  higher_is_better?: boolean
  spark?: number[]
  /** Month label for each sparkline point, and whether the values are money or counts. */
  spark_labels?: string[]
  spark_kind?: 'money' | 'number'
  /** "snapshot" figures are books balances and ignore the period filters. */
  scope?: 'period' | 'snapshot'
  /** True when the tile can be clicked to drill into the figure. */
  explore?: boolean
  /** Plain-language help: what the figure means and exactly how it is worked out. */
  about?: { means: string; calc: string; scope: string }
  /** What the change is measured against: both values and their date ranges. */
  detail?: KpiDetail | null
  /** The change against the whole of the year before, for a financial year in progress (null where it has no meaning). */
  full?: KpiChange | null
  /** The other comparison, kept beside the one that is leading. Set by `withCompare`, never by the server. */
  also?: KpiChange | null
}

/** One comparison of a figure: how it moved, which way is good, and what it is set against. */
export interface KpiChange {
  delta: string
  delta_type: 'positive' | 'negative' | 'neutral'
  delta_pct?: number | null
  /** "vs full FY 2025-26" */
  compare: string
  /** The figure it is set against, and the dates it covers. */
  value?: string
  range?: string
}

export interface KpiDetail {
  current_range?: string
  current_value?: string
  compare?: string
  previous_value?: string
  previous_range?: string
  yoy_label?: string
  yoy_value?: string
  yoy_range?: string
  full_label?: string
  full_value?: string
  full_range?: string
  /** Why there is no comparison, when there is none. */
  note?: string
}

export type InsightTone = 'positive' | 'negative' | 'warning' | 'neutral'

/** A finding the backend computed from the figures on the page. */
export interface Insight {
  id: string
  /** The dashboard tab that shows it: a Tally area (trend, clients, notes, income) or an Orion tab. */
  area: string
  tone: InsightTone
  title: string
  detail: string
  action?: { key: DashboardFilterKey; value: string }
  /** Tally dashboard tab to open instead of filtering the current one. */
  tab?: string
}

/** Shared shape for every categorical visual so one chart component fits all. */
export interface Category {
  code: string
  label: string
  value: number
}

/** A month on the x axis plus whatever metrics the view asked for. */
export interface SeriesPoint {
  code: string
  label: string
  [metric: string]: string | number
}

/** `bill` is a bill number: it shows the bill's card on hover and opens the bill in a new tab (components/billing/BillNumber.tsx). */
export type CellFormat = 'text' | 'money' | 'number' | 'percent' | 'bill'

export interface TableColumn {
  key: string
  label: string
  format: CellFormat
  align: 'left' | 'right'
}

export interface TableBlock {
  /** When set, clicking a row filters the page by that dimension. */
  filter_key: DashboardFilterKey | null
  columns: TableColumn[]
  rows: Record<string, string | number>[]
  /** Column totals over every row the filters select, when that is known. */
  totals?: Record<string, number> | null
  /** True when the server cut the list, so row-based sums would be partial. */
  truncated?: boolean
}

export interface DashboardView {
  view: string
  filters: DashboardFilters
  active_filters: FilterChip[]
  kpis: DashboardKpi[]
  series: Record<string, SeriesPoint[]>
  categories: Record<string, Category[]>
  tables: Record<string, TableBlock>
  insights?: Insight[]
  meta: {
    months: number
    range: string
    from?: string | null
    to?: string | null
    bounds: { min: string; max: string }
    snapshot?: string
    invalid_filters?: { key: string; value: string; reason: string }[]
    data_through?: string
    comparison?: {
      previous: string
      yoy: string
      /** The whole of the year before, when a financial year in progress is selected. */
      full?: string
      /** What the selection is: a month, a financial year, a range, or everything. */
      kind?: 'month' | 'fy' | 'range' | 'all'
    }
    empty?: boolean
    filter_options?: {
      clients?: { id: string; label: string }[]
      companies?: { id: string; label: string }[]
      fys?: { id: string; label: string }[]
      voucher_types?: { id: string; label: string }[]
      cost_centres?: { id: string; label: string }[]
      income_lines?: { id: string; label: string }[]
      domains?: { id: string; label: string }[]
      capabilities?: { id: string; label: string }[]
      cases?: { id: string; label: string }[]
      states?: { id: string; label: string }[]
      client_types?: { id: string; label: string }[]
      priorities?: { id: string; label: string }[]
    }
    message?: string
  }
}

export interface SignupRequest {
  id: number
  username: string
  display_name: string
  email: string
  phone?: string | null
  status: 'pending' | 'approved' | 'rejected'
  requested_timestamp: string
  reviewed_timestamp?: string | null
  reviewed_by?: number | null
  created_user_id?: number | null
  rejection_reason?: string | null
}

/** One place a person is signed in (a browser or device). `id` is for ending it; the cookie itself is never sent to a screen. */
export type UserSession = {
  id: number
  created: string
  last_seen: string
  expires: string
  ip: string | null
  device: string
  current: boolean
}

/** What the admin System page shows (GET /api/health/details). */
export type SystemHealth = {
  status: 'ok' | 'attention'
  attention: string[]
  environment: string
  checked: string
  database: {
    ok: boolean
    ms: number | null
    error: string | null
    /** The connection pool: how many are open, busy and idle, and how often a caller had to wait or gave up. Null before first use. */
    pool: { max: number; open: number; in_use: number; idle: number; waits: number; wait_seconds: number; timeouts: number; opened: number; discarded: number } | null
  }
  loads: {
    pipeline: string
    last_success: string | null
    last_failure: string | null
    last_error: string | null
    running: boolean
    failing: boolean
  }[]
  autoload: { minutes: number; next_check: string | null }
  /** The database schema record (app/migrate.py): steps recorded, how many applied, when the last was, and what is wrong. */
  schema: { steps: number; applied: number; last_applied: string | null; problems: string[] }
  backup: {
    state: string
    problems: string[]
    running: boolean
    last_success: { finished_timestamp?: string | null; size_bytes?: number | null } | null
    next_run: string | null
    stale: boolean
    interval_hours: number
  } | null
  requests: {
    since: string
    uptime_seconds: number
    total: number
    errors_5xx: number
    slow: number
    slow_threshold_ms: number
    recent_slow: { time: string; method: string; path: string; status: number; ms: number; request_id: string }[]
  }
  problems: { time: string; level: string; logger: string; request_id: string; message: string }[]
  log: { level: string; file: string | null }
}

export interface AppUser {
  id: number
  username: string
  display_name: string
  role: string
  is_active: boolean
  ods_access: boolean
  ods_write: boolean
  dw_access: boolean
  dw_write: boolean
  tally_access: boolean
  tally_write: boolean
  tally_dw_access: boolean
  tally_dw_write: boolean
  orion_dashboard_access: boolean
  tally_dashboard_access: boolean
  billing_access: boolean
  billing_write: boolean
  etl_access: boolean
  etl_write: boolean
  letterhead_access: boolean
  letterhead_write: boolean
  documents_access: boolean
  documents_write: boolean
  bank_access: boolean
  bank_write: boolean
  tenders_access: boolean
  tenders_write: boolean
  attendance_access: boolean
  attendance_write: boolean
  ai_access: boolean
  created_timestamp: string
  has_avatar: boolean
  avatar_version: number
  avatar_url?: string | null
  email?: string | null
  phone?: string | null
}

/** What deleting a folder together with everything in it would take away, and whether that may be done. */
export interface FolderContents {
  folder_id: number
  name: string
  subfolders: number
  subfolder_names: string[]
  documents: number
  document_titles: string[]
  versions: number
  size_bytes: number
  /** Documents already in the trash: they stay there. */
  trashed: number
  /** Papers Orion filed itself (bills, employee and EMD papers): they are never deleted here. */
  filed: number
  can_drop: boolean
  reason: string | null
}

export interface ChatPeer {
  id: number
  display_name: string
  username: string
  role?: string
  has_avatar?: boolean
  avatar_version?: number
  avatar_url?: string | null
  online?: boolean
}

export type ChatMediaKind = 'image' | 'video' | 'file' | 'audio'

/** What a finished call left in its conversation (the sound and picture are never kept). */
export interface ChatCall {
  id: number
  kind: 'voice' | 'video'
  outcome: 'ended' | 'missed' | 'declined' | 'cancelled' | 'answered' | 'failed' | 'ringing'
  caller_id: number
  /** How long it lasted, when it was answered. */
  seconds?: number | null
}

/** A call that is ringing, as the server sends it to the person rung and to the person ringing. */
export interface CallRing {
  id: number
  chat_id: number
  kind: 'voice' | 'video'
  caller: ChatPeer
  callee_id: number
}

export interface ChatReaction {
  emoji: string
  user_ids: number[]
}

/** The message a reply quotes, as the server sends it (already cut short, and blank when that message was deleted). */
export interface ChatReplyRef {
  id: number
  sender_id: number | null
  body: string
  media_kind?: ChatMediaKind | null
  media_name?: string | null
  deleted: boolean
}

export interface ChatMessage {
  id: number
  chat_id: number
  sender_id: number
  body: string
  created_timestamp: string
  edited_timestamp?: string | null
  deleted?: boolean
  forwarded?: boolean
  client_id?: string | null
  reply_to?: ChatReplyRef | null
  media_kind?: ChatMediaKind | null
  media_name?: string | null
  media_url?: string | null
  media_size?: number | null
  /** A voice note: how long it is and a small picture of its loudness (0 to 100). */
  media_duration_ms?: number | null
  media_waveform?: number[]
  /** Set when this line is a call that happened in the conversation. */
  call?: ChatCall | null
  /** A line nobody wrote ("Priya added Rahul"): it is shown between the messages and cannot be changed. */
  system?: boolean
  /** Who wrote it, so a group can name someone who has since left. */
  sender_name?: string | null
  reactions?: ChatReaction[]
  /** Only on a message this browser is still sending, or could not send. Never comes from the server. */
  pending?: { state: 'sending' | 'failed'; progress?: number; error?: string; file?: File | null }
}

export interface ChatSettings {
  pinned: boolean
  muted: boolean
  archived: boolean
}

/** A person in a group: who they are and whether they run it. `last_read_id` is how far they have read. */
export interface ChatMember extends ChatPeer {
  group_role: 'admin' | 'member'
  last_read_id: number
}

export interface ChatThread {
  id: number
  /** A conversation with one person, or a group of people with a name. */
  kind: 'direct' | 'group'
  title?: string | null
  peer: ChatPeer | null
  /** The people in a group (everyone, this person included). Empty for a conversation with one person. */
  members: ChatMember[]
  /** This person's part in a group. */
  my_role?: 'admin' | 'member' | null
  created_by?: number | null
  last_message: ChatMessage | null
  unread: number
  settings: ChatSettings
  my_last_read_id: number
  peer_last_read_id: number
}

export interface ChatPage {
  messages: ChatMessage[]
  has_more: boolean
  reaches_latest?: boolean
}

export interface ChatSearchHit {
  id: number
  chat_id: number
  sender_id: number
  snippet: string
  created_timestamp: string
}

export interface ChatSharedItem {
  message_id: number
  sender_id: number
  created_timestamp: string
  kind: ChatMediaKind
  name: string
  size: number | null
  url: string
}

export type ChatAssistAction = 'rewrite' | 'reply' | 'summarize' | 'translate'

export interface ChatAssistResult {
  status: 'ok' | 'needs_consent' | 'unavailable'
  message?: string
  text?: string
  options?: string[]
  where?: 'local' | 'cloud'
  provider?: string
}

export interface ChatThreadDetail extends ChatThread, ChatPage {
  pins: ChatMessage[]
}

// ---- Billing (Utility > Billing) -----------------------------------------------------

export interface BillProfile {
  company_name: string
  address: string
  phone: string
  gstin: string
  pan: string
  pf_no: string
  esi_no: string
  reg_no: string
  bank_name: string
  bank_ifsc: string
  bank_account: string
  signatory: string
  signatory_title: string
  terms: string[]
  default_service_description: string
  /** The company's own typeface and size for its bills (bill_fonts.py). Not part of the copy a bill keeps of the profile. */
  font_family?: string
  font_size?: number
}

/** The details of the template one bill prints differently (PROFILE_BILL_KEYS in billing.py). */
export type BillProfileEdits = Partial<
  Pick<
    BillProfile,
    | 'company_name'
    | 'address'
    | 'phone'
    | 'gstin'
    | 'pan'
    | 'pf_no'
    | 'esi_no'
    | 'reg_no'
    | 'bank_name'
    | 'bank_ifsc'
    | 'bank_account'
    | 'signatory'
    | 'signatory_title'
    | 'terms'
  >
>

/** The typeface (a key of billFonts.ts) and base size in points a bill is drawn in. */
export interface BillFont {
  family: string
  size: number
  /** The bill has a choice of its own; false means it follows the company's setting. */
  own?: boolean
}

/** What GET /billing/fonts offers: the typefaces this computer can draw in the PDF, and the sizes. */
export interface BillFontOptions {
  sizes: number[]
  default_family: string
  default_size: number
  families: { key: string; label: string; css: string }[]
}

/** A case a bill can be raised for. The client and its billing details come from the case. */
export interface BillCase {
  case_code: string
  case_name: string
  case_status: string | null
  client_code: string | null
  client_name: string | null
  billing_name: string | null
  gstin: string | null
  billing_address: string | null
  state: string | null
  /** The tender of the case's opportunity: what a new bill's tender fields start from. */
  tender_id?: string | null
  tender_start_date?: string | null
  /** The case's last issued bill: its lines and rates start the next one. */
  last: {
    location: string | null
    service_description: string | null
    lines: { particulars: string; qty: number | string | null; rate: number | string | null; days?: number | string | null; fields?: Record<string, string>; skip?: string[] }[]
    line_setup?: LineSetup
    /** What that bill printed differently from the template: a repeat bill starts with it. */
    profile_overrides?: BillProfileEdits
    tender_id?: string | null
    tender_start_date?: string | null
    rates: Record<string, number>
    extra_charges?: ExtraCharge[]
    hidden?: string[]
    header_fields?: HeaderField[]
    bill_number: string
    bill_date: string
  } | null
  /** The party details on the client's last issued bill, used where the client record has none. */
  last_party: BillParty | null
  /** The client's group (another client), when it has one: its own billing details, for a bill addressed to the group. */
  group: {
    client_code: string
    client_name: string | null
    billing_name: string | null
    gstin: string | null
    billing_address: string | null
    state: string | null
    last_party: BillParty | null
  } | null
}

/** The party printed on an issued bill. */
export interface BillParty {
  party_name: string
  party_gstin: string | null
  party_address: string | null
  party_state: string | null
  party_fields?: HeaderField[]
}

export interface BillListRow {
  id: string
  bill_number: string
  fy_start_year: number
  bill_seq: number
  bill_date: string
  service_month: string
  case_code: string | null
  case_name: string | null
  client_code: string | null
  client_name: string | null
  /** The Tally ledger a bill was raised against before bills were tagged to cases. */
  legacy_client_ledger: string | null
  gst_paid: boolean
  /** The GST paid so far: more than 0 and gst_paid false means part paid. */
  gst_paid_amount: number
  /** What the bill charged for EPFO and ESIC, and what has been paid over of each. */
  epf_amount: number
  esic_amount: number
  epf_paid_amount: number
  esic_paid_amount: number
  version_no: number
  /** Money received against the bill so far. */
  received_total: number
  /** What approved credit notes have taken off the bill. */
  credited_amount: number
  party_name: string
  party_gstin: string | null
  location: string | null
  ref_no: string | null
  taxable_total: number
  cgst_amount: number
  sgst_amount: number
  round_off: number
  grand_total: number
  status: 'Issued' | 'Cancelled'
  created_timestamp: string
}

/** A named detail printed with the GSTIN and PAN at the top of one bill, such as a vendor code. */
export interface HeaderField {
  label: string
  value: string
}

/** The rows of the totals a bill can name. */
export type SummaryLabelKey = 'lines_total' | 'sub_total' | 'taxable_total' | 'epf' | 'esic' | 'service'

/**
 * How one bill's lines are laid out and worked out (billing.clean_line_setup). `unit` is quantity x rate; `daily` is rate x days and
 * `monthly` is a monthly rate for `days` of the month's days, each times the quantity when `qty_multiplies`. `columns` are the bill's
 * own columns: each line keeps its value for one under `fields[key]`. `labels` are the column names the bill chose.
 */
export interface LineSetup {
  basis: 'unit' | 'daily' | 'monthly'
  qty_multiplies: boolean
  /** Days a monthly rate is divided by; null is the number of days in the bill's month. */
  month_days: number | null
  /** A row under the lines adding up the quantity, the days and the amount. */
  totals_row: boolean
  /** Each line says which of EPFO, ESIC and service charges it is part of (the editor shows the choice). */
  charge_by_line: boolean
  /** What the service charge is taken of: the lines, or the lines with the EPFO and ESIC. Absent on a bill saved before: the lines. */
  service_on?: 'lines' | 'lines_epf_esic'
  /** The names the bill gave its columns and the rows of its totals; empty keeps the usual name. */
  labels: Partial<Record<'particulars' | 'qty' | 'rate' | 'days' | 'amount' | SummaryLabelKey, string>>
  columns: { key: string; label: string }[]
}

/** A charge the user named on one bill: a percentage of the lines total, or a fixed amount. */
export interface ExtraCharge {
  label: string
  kind: 'pct' | 'amount'
  value: number
  amount: number
}

/** One line of a bill. `days` is there on a day-based bill and `fields` on one with its own columns. */
export interface BillLine {
  particulars: string
  qty: number | string | null
  rate: number | null
  days?: number | string | null
  fields?: Record<string, string>
  /** Charges (epf, esic, service) the line is left out of. */
  skip?: string[]
  /** The amount was entered by hand; `auto_amount` is what the quantity, rate and days came to. */
  manual?: boolean
  auto_amount?: number | null
  amount: number
}

/** A figure entered instead of the calculated one: the value on the bill, and what the calculation gave. */
export type ManualFigures = Partial<Record<'epf_amount' | 'esic_amount' | 'service_amount' | 'cgst_amount' | 'sgst_amount', { value: number; auto: number }>>

/** What the printable bill needs. A saved bill and a draft in the editor both fit this. */
export interface BillView {
  number: string | null
  status: 'Issued' | 'Cancelled' | 'Draft'
  bill_date: string
  service_month: string
  party_name: string
  party_gstin: string | null
  party_address: string | null
  party_state: string | null
  ref_no: string | null
  ref_date: string | null
  location: string | null
  service_description: string | null
  lines: BillLine[]
  rates: { epf_pct: number; esic_pct: number; service_pct: number; cgst_pct: number; sgst_pct: number }
  /** The tender the bill is raised under; printed with the invoice details unless hidden (tender_id, tender_date). */
  tender_id?: string | null
  tender_start_date?: string | null
  /** Absent on a bill saved before the lines could be laid out differently: quantity x rate, standard columns. */
  line_setup?: LineSetup
  /** EPFO, ESIC, service, CGST or SGST amounts that were entered instead of calculated. Absent or empty: all calculated. */
  manual_figures?: ManualFigures
  /** The template details this bill prints differently from the template (its printed copy is `profile`). */
  profile_overrides?: BillProfileEdits
  /** Absent on a bill saved before extra charges and hiding existed; it prints as it always did. */
  extra_charges?: ExtraCharge[]
  /** Parts of the printed bill this bill leaves off (billLayout.ts). */
  hidden?: string[]
  header_fields?: HeaderField[]
  /** Named details of the client, printed under its GSTIN. */
  party_fields?: HeaderField[]
  /** The typeface and size it is drawn in (its own, else the company's). Absent: Arial, 9 pt. */
  font?: BillFont
  lines_total: number
  epf_amount: number
  esic_amount: number
  sub_total: number
  service_amount: number
  taxable_total: number
  cgst_amount: number
  sgst_amount: number
  round_off: number
  grand_total: number
  profile: BillProfile
}

export interface SavedBill extends Omit<BillView, 'number' | 'status' | 'lines'> {
  id: string
  bill_number: string
  fy_start_year: number
  status: 'Issued' | 'Cancelled'
  case_code: string | null
  case_name: string | null
  client_code: string | null
  client_name: string | null
  legacy_client_ledger: string | null
  lines: BillView['lines']
  /** This bill's own choice; null follows the company's setting. */
  font_family: string | null
  font_size: number | null
  cancelled_reason: string | null
  gst_paid: boolean
  /** The GST paid to the government so far (payments that have not been reversed added up). */
  gst_paid_amount: number
  gst_paid_timestamp: string | null
  /** Where the GST stands, with its payments. Absent on an earlier version of the bill fetched from history. */
  gst?: BillGst
  /** Where EPFO and ESIC stand, with their payments. Absent on an earlier version of the bill fetched from history. */
  statutory?: BillStatutory
  epf_paid_amount?: number
  esic_paid_amount?: number
  version_no: number
  version_reason: string | null
  version_by_name: string | null
  version_timestamp: string
  /** Received and outstanding money. Absent on an earlier version fetched from history. */
  revenue?: BillRevenue
  /** False when this is an earlier version of the bill, fetched from its history. */
  is_current: boolean
  current_version_no: number
}

/** One component of the GST on a bill: what it comes to, what has been paid, what is left. */
export interface GstPart {
  due: number
  paid: number
  remaining: number
}

/**
 * A payment of GST to the government, as recorded: its CGST and SGST together (what was recorded in one go), the day, a reference, who
 * and when. Reversing one keeps it (reversed: true, with who, when and why): nothing is ever deleted.
 */
export interface GstPayment {
  batch_id: string
  paid_date: string | null
  reference: string | null
  recorded_by_name: string | null
  recorded_timestamp: string
  cgst: number
  sgst: number
  total: number
  reversed: boolean
  reversed_by_name: string | null
  reversed_timestamp: string | null
  reversal_reason: string | null
}

/** GST on a bill is paid in instalments: CGST and SGST on different days, a part now and the rest later. */
export interface BillGst {
  status: 'Not paid' | 'Part paid' | 'Paid' | 'No GST'
  cgst: GstPart
  sgst: GstPart
  total: GstPart
  /** Newest first. */
  payments: GstPayment[]
}

/** One of EPFO and ESIC on a bill: what it charged, what has been paid over, what is left. */
export interface StatutoryPart extends GstPart {
  status: 'Not paid' | 'Part paid' | 'Paid' | 'None'
}

/**
 * A payment of EPFO and/or ESIC to the authority, as recorded: the two together (what was recorded in one go), the day, a reference, who and when. Reversing one
 * keeps it (reversed: true, with who, when and why): nothing is ever deleted.
 */
export interface StatutoryPayment {
  batch_id: string
  paid_date: string | null
  reference: string | null
  recorded_by_name: string | null
  recorded_timestamp: string
  epfo: number
  esic: number
  total: number
  reversed: boolean
  reversed_by_name: string | null
  reversed_timestamp: string | null
  reversal_reason: string | null
}

export interface BillStatutory {
  status: 'Not paid' | 'Part paid' | 'Paid' | 'No EPFO or ESIC'
  epfo: StatutoryPart
  esic: StatutoryPart
  total: GstPart
  /** Newest first. */
  payments: StatutoryPayment[]
}

/** What the hover card on a bill number shows (GET /billing/card). */
export interface BillCard {
  id: string
  bill_number: string
  status: 'Issued' | 'Cancelled'
  payment_status: 'Paid' | 'Part paid' | 'Unpaid' | 'Settled' | 'Cancelled'
  bill_date: string | null
  service_month: string | null
  /** Days since the bill date, only while money is still owed on an issued bill. */
  age_days: number | null
  ref_no: string | null
  ref_date: string | null
  location: string | null
  service_description: string | null
  client_code: string | null
  client_name: string | null
  case_code: string | null
  case_name: string | null
  party_name: string | null
  party_gstin: string | null
  party_state: string | null
  line_count: number
  lines: { particulars: string | null; qty: number | string | null; rate: number | null; days?: number | string | null; amount: number | null }[]
  figures: {
    lines_total: number
    epf_amount: number
    esic_amount: number
    service_amount: number
    extra_charges: { label: string; amount: number }[]
    taxable_total: number
    cgst_amount: number
    sgst_amount: number
    round_off: number
    grand_total: number
  }
  payments: { received: number; credited: number; remaining: number; count: number; recent: { received_date: string | null; amount: number }[] }
  gst_paid: boolean
  gst: { status: BillGst['status'] | null; total: GstPart | null; cgst: GstPart | null; sgst: GstPart | null; last_paid_date: string | null }
  statutory: { status: BillStatutory['status'] | null; total: GstPart | null; epfo: StatutoryPart | null; esic: StatutoryPart | null }
  version_no: number
  version_reason: string | null
  version_by_name: string | null
  version_timestamp: string | null
  created_by_name: string | null
  created_timestamp: string | null
  cancelled_reason: string | null
  cancelled_timestamp: string | null
}

/** One revenue entry (case transaction) a bill owns. */
export interface BillRevenueEntry {
  id: string
  /** Committed is money received, Prospective is still to come. */
  status: 'Committed' | 'Prospective' | 'Cancelled'
  bill_date: string
  received_date: string | null
  taxable: number
  gst: number
  /** What this payment took off the bill: the cash plus what the client held back. */
  amount: number
  /** What reached the account (the amount less what was held back). */
  cash: number
  deductions: BillDeduction[]
}

/** The kinds of thing a client may hold back from a payment. */
export type DeductionKind = 'TDS' | 'Penalty' | 'Rounding' | 'Other'

/** Something a client held back from a payment. */
export interface BillDeduction {
  id: number
  kind: DeductionKind
  amount: number
  section: string | null
  rate: number | null
  reason: string | null
  matched_26as: boolean
}

/** A deduction as typed when a payment is recorded. */
export interface DeductionInput {
  kind: DeductionKind
  amount: string
  section?: string
  rate?: string
  reason?: string
}

export interface BillRevenue {
  /** What credit notes have taken off the bill (approved, not reversed): owed by no one. */
  credited: number
  /** What has settled the bill: the cash that came in plus what clients held back. */
  received: number
  /** Of `received`, what clients held back (TDS and the like). */
  deducted: number
  remaining: number
  entries: BillRevenueEntry[]
}

// ---- Credit notes and write-offs (Utility > Credit notes, and on a bill) ----------------------------

export type CreditNoteKind = 'Credit note' | 'Bad debt write-off'
export type CreditNoteStatus = 'Pending' | 'Approved' | 'Rejected' | 'Withdrawn' | 'Reversed'

export interface CreditNote {
  id: number
  bill_code: string
  bill_number: string
  client_code: string | null
  client_name: string | null
  party_name: string | null
  kind: CreditNoteKind
  status: CreditNoteStatus
  note_date: string
  /** The amount credited, GST included. The parts are worked out when the note is approved. */
  total: number
  taxable: number
  cgst: number
  sgst: number
  reason: string
  cn_number: string | null
  created_by: number | null
  created_by_name: string | null
  created_timestamp: string | null
  decided_by_name: string | null
  decided_timestamp: string | null
  decision_note: string | null
  reversed_by_name: string | null
  reversed_timestamp: string | null
  reversal_reason: string | null
  /** What this person may do with it, worked out by the server. */
  can_approve: boolean
  approve_blocked: string | null
  can_withdraw: boolean
  can_reverse: boolean
}

export interface CreditNoteList {
  rows: CreditNote[]
  pending: number
  years: { fy_start_year: number; label: string }[]
  totals: { approved: number; gst: number; count: number }
}

export interface CreditNotePreview {
  total: number
  taxable: number
  cgst: number
  sgst: number
  still_owed: number
  open: number
}

// ---- GST position by month (Utility > GST) ------------------------------------------------------

export interface GstMonth {
  month: string
  label: string
  /** CGST + SGST on the bills issued in the month. */
  output: number
  /** The GST on the credit notes dated in the month, which comes off it. */
  notes: number
  /** Input tax credit: GST on the costs that carry the supplier's GSTIN and invoice number. */
  credit: number
  net: number
  running_net: number
  paid: number
  future: boolean
}

export interface GstPosition {
  fy_start_year: number
  fy_label: string
  months: GstMonth[]
  totals: { output: number; notes: number; credit: number; net: number; paid: number }
  without_gstin: { count: number; gst: number }
  suppliers: { gstin: string; expenses: number; credit: number }[]
  years: { fy_start_year: number; label: string }[]
}

// ---- TDS held back by clients (Utility > TDS) ---------------------------------------------------

export interface TdsSection {
  code: string
  label: string
  rate: number
}

export interface TdsSuggestion {
  section: string
  rate: number
  /** `last` when it is what this client was last deducted under, `default` when there is no history. */
  source: 'last' | 'default'
  sections: TdsSection[]
}

export interface TdsRow {
  deduction_id: number
  bill_code: string
  bill_number: string
  client_code: string | null
  client_name: string | null
  received_date: string
  fy_start_year: number
  fy_label: string
  quarter: string | null
  section: string
  rate: number | null
  amount: number
  matched: boolean
  certificate_ref: string | null
  matched_by_name: string | null
}

export interface TdsLedger {
  rows: TdsRow[]
  years: { fy_start_year: number; label: string }[]
  totals: { total: number; matched: number; unmatched: number; count: number }
  by_client: { client_code: string | null; client_name: string | null; total: number; unmatched: number; count: number }[]
  by_quarter: { quarter: string; total: number }[]
  truncated: boolean
}

export interface BillVersionRow {
  version_no: number
  saved_timestamp: string
  saved_by: string | null
  reason: string | null
  grand_total: number
  is_current: boolean
}

// ---- Outstanding bills, reminders and sending (Utility > Outstanding) -------------------

export interface ReceivableBill {
  id: string
  bill_number: string
  bill_date: string
  service_month: string
  case_code: string
  case_name: string | null
  location: string | null
  grand_total: number
  received: number
  balance: number
  /** Days since the bill date. */
  days: number
  /** Index into the report's bucket_labels. */
  bucket: number
  last_reminder: string | null
  reminders: number
}

export interface ReceivableClient {
  client_code: string
  client_name: string
  billing_name: string | null
  total: number
  /** What is owed in each age bucket, in the order of bucket_labels. */
  buckets: number[]
  bills: ReceivableBill[]
  oldest_days: number
  last_reminder: string | null
}

export interface ReceivablesReport {
  as_of: string
  bucket_labels: string[]
  clients: ReceivableClient[]
  totals: { total: number; buckets: number[]; clients: number; bills: number }
  /** Issued bills with no case. They have no payment record, so they are not counted as owed. */
  untagged_bills: number
}

export interface ShareHistoryRow {
  kind: 'invoice' | 'reminder'
  channel: 'email' | 'whatsapp'
  recipient: string
  sent_timestamp: string
  sent_by: string | null
}

/** What the send dialog starts with: the wording, and the address or number last used for this client. */
export interface ShareDefaults {
  subject: string
  message: string
  email_enabled: boolean
  email: string | null
  phone: string | null
  history: ShareHistoryRow[]
}

/** A case billed before that has no bill yet for the month being billed. */
export interface DueCase {
  /** The case's latest issued bill: what a repeat bill is copied from. */
  id: string
  bill_number: string
  bill_date: string
  service_month: string
  party_name: string
  grand_total: number
  location: string | null
  case_code: string
  case_name: string
  client_code: string | null
  client_name: string | null
  months_behind: number
}

// ---- Record history and warehouse freshness --------------------------------------------

export interface HistoryChange {
  field: string
  label: string
  from: string | number | boolean | null
  to: string | number | boolean | null
  /** On a lookup field, the name behind the code ("Anita Rao (EMP-0003)"). The code stays in from / to. */
  from_label?: string
  to_label?: string
}

export interface HistoryEntry {
  kind: 'created' | 'changed' | 'deleted'
  when: string | null
  /** Display name of the user. Null when the record was saved before changes were tracked. */
  by: string | null
  changes: HistoryChange[]
}

export interface RecordHistory {
  /** Newest first. */
  entries: HistoryEntry[]
  /** When the warehouse was last fully loaded: history is complete up to the start of that load. */
  loaded: string | null
  /** The record was saved after the last load began, so its newest change is not listed yet. */
  pending: boolean
}

export interface WarehouseLoadRun {
  trigger: 'manual' | 'scheduled'
  status: 'running' | 'succeeded' | 'failed'
  started: string | null
  finished: string | null
  error: string | null
  by: string | null
  scope?: string
}

export interface WarehouseStatus {
  /** The warehouse is as current as its stalest table. Null if a table has never been loaded. */
  last_success: WarehouseLoadRun | null
  latest: WarehouseLoadRun | null
  /** How often the automatic loader checks. 0 means it is off. */
  autoload_minutes: number
}

// ---- ETL pipelines and their run history ------------------------------------------------

export type EtlPipelineKey = 'orion_dw' | 'tally_ods' | 'tally_dw'
export type EtlRunStatus = 'running' | 'succeeded' | 'failed'
export type EtlStepStatus = 'pending' | 'running' | 'succeeded' | 'failed' | 'skipped'

/** One run of one pipeline. The four counts mean the same for every pipeline: a warehouse "updates" a row by
 *  adding a new version and "deletes" one by marking it expired. */
export interface EtlRun {
  id: number
  pipeline: EtlPipelineKey
  /** "all", or the one table that was loaded. */
  scope: string
  trigger: 'manual' | 'scheduled'
  status: EtlRunStatus
  started_timestamp: string
  finished_timestamp: string | null
  /** Elapsed so far while the run is still going. */
  duration_ms: number | null
  steps_total: number
  steps_succeeded: number
  steps_failed: number
  steps_skipped: number
  rows_read: number
  rows_inserted: number
  rows_updated: number
  rows_deleted: number
  rows_unchanged: number
  /** Where it read from: Tally host and company, or the schema. */
  source: Record<string, unknown> | null
  target: string | null
  source_fingerprint: string | null
  runner_host: string | null
  app_env: string | null
  error: string | null
  started_by: number | null
  started_by_name: string | null
}

export interface EtlStep {
  seq: number
  name: string
  kind: string | null
  target_table: string | null
  status: EtlStepStatus
  started_timestamp: string | null
  finished_timestamp: string | null
  duration_ms: number | null
  rows_read: number
  rows_inserted: number
  rows_updated: number
  rows_deleted: number
  rows_unchanged: number
  target_rows_before: number | null
  target_rows_after: number | null
  /** What the loader reported, as it reported it, plus current_rows for a warehouse table. */
  stats: Record<string, number> | null
  error: string | null
}

export interface EtlRunDetail extends EtlRun {
  steps: EtlStep[]
}

export interface EtlRecentRun {
  id: number
  status: EtlRunStatus
  scope: string
  trigger: 'manual' | 'scheduled'
  duration_ms: number | null
  started_timestamp: string
  rows_inserted: number
  rows_updated: number
  rows_deleted: number
}

export interface EtlPipeline {
  key: EtlPipelineKey
  label: string
  group: string
  description: string
  source: string
  target: string
  schedule: string
  steps: { name: string; kind: string }[]
  can_run: boolean
  /** Pipelines this one reads from, which must not be running. */
  waits_for: string[]
  running: boolean
  last_run: EtlRun | null
  last_full_success: EtlRun | null
  /** What the last full success left in the target: tables loaded and rows held (every version, for a warehouse). */
  footprint: { tables: number; rows: number } | null
  /** The latest runs, oldest first, for the bars. */
  recent_runs: EtlRecentRun[]
  /** When the automatic loader will next look, if this pipeline has one. */
  next_run: string | null
  runs_30d: number
  success_rate_30d: number | null
  avg_duration_ms_30d: number | null
}

export interface BackupRun {
  id: number
  trigger: 'manual' | 'scheduled'
  status: 'running' | 'succeeded' | 'failed'
  started_timestamp: string
  finished_timestamp: string | null
  duration_ms: number | null
  size_bytes: number | null
  prefixes: string[] | null
  error: string | null
}

export interface BackupStatus {
  /** off: switched off here; blocked: switched on but this machine may not back up; ready: running on its schedule. */
  state: 'off' | 'blocked' | 'ready'
  problems: string[]
  role: 'dev' | 'prod' | null
  bucket: string | null
  interval_hours: number
  running: boolean
  last_success: { id: number; finished_timestamp: string | null; size_bytes: number | null } | null
  last_checked: string | null
  next_run: string | null
  stale: boolean
  recent: BackupRun[]
}

/** One column of a record set opened from a chart. */
export interface RecordColumn {
  key: string
  label: string
  format: CellFormat
  align: 'left' | 'right'
}

/** A page of the rows behind a dashboard figure. */
export interface RecordPage {
  dataset: string
  label: string
  columns: RecordColumn[]
  rows: Record<string, string | number | null>[]
  total: number
  totals: Record<string, number>
  page: number
  size: number
  sort: { key: string; dir: 'asc' | 'desc' }
  /** Route to open a row, with {id} standing for the row's `_id`. */
  link: string | null
  /** False for sets that show today's position and ignore the period. */
  period_applies: boolean
  truncated: boolean
  /** False for a set worked out in Python (a ledger snapshot), which the column filters cannot reach. */
  filterable?: boolean
}

export interface RecordSetInfo {
  id: string
  label: string
  /** A narrowed set that a chart opens; the Explore menu does not list it. */
  hidden?: boolean
}

/** One bar in a drill-down: a year, a month, or a value of a dimension. */
export interface ExploreBar {
  code: string
  label: string
  value: number
  /** Share of the whole, for figures that add up. */
  share?: number
}

export interface ExploreBreakdown {
  key: string
  label: string
  items: ExploreBar[]
  /** How many more values there are than the bars shown. */
  more: number
}

/** A key figure taken apart: by year and month, by every dimension that applies, and the rows behind it. */
export interface ExploreView {
  measure: string
  label: string
  format: 'money' | 'number' | 'percent'
  additive: boolean
  snapshot: boolean
  note: string
  total: number
  years: ExploreBar[]
  months: ExploreBar[]
  breakdowns: ExploreBreakdown[]
  records: { dataset: string; label: string }[]
  /** What makes a row count towards this figure, in words, for example "Only the opportunities that were won." */
  population_note?: string
  chips: FilterChip[]
}

/** One of the two image strips of the company letterhead. */
export interface LetterheadStrip {
  /** False while the strip shipped with the application is in use. */
  custom: boolean
  width: number
  height: number
  type: string
  size_bytes: number
  url: string
}

export type LetterheadSettingKey =
  | 'header_top_mm'
  | 'footer_bottom_mm'
  | 'side_mm'
  | 'body_left_mm'
  | 'body_right_mm'
  | 'body_gap_top_mm'
  | 'body_gap_bottom_mm'

export type LetterheadSettings = Record<LetterheadSettingKey, number>

/** The letterhead as the server describes it. Every length is in millimetres; `layout` is worked out by the server. */
export interface LetterheadDesign {
  version: number
  settings: LetterheadSettings
  limits: Record<LetterheadSettingKey, { default: number; min: number; max: number }>
  layout: {
    strip_width_mm: number
    header_height_mm: number
    footer_height_mm: number
    /** What text must stay clear of at the top and bottom of a page. */
    top_space_mm: number
    bottom_space_mm: number
  }
  page: { width_mm: number; height_mm: number }
  header: LetterheadStrip
  footer: LetterheadStrip
  updated_timestamp: string | null
  updated_by_name: string | null
}

export type LetterFont = 'sans' | 'serif'

/** What is sent to save a letter. */
export interface LetterInput {
  title: string
  ref_no: string | null
  letter_date: string
  body_html: string
  font: LetterFont
  font_size: number
  show_header: boolean
  show_footer: boolean
}

export interface LetterSummary {
  letter_id: number
  title: string
  ref_no: string | null
  letter_date: string
  font: LetterFont
  font_size: number
  show_header: boolean
  show_footer: boolean
  created_timestamp: string
  last_updated_timestamp: string
  created_by_name: string | null
  last_updated_by_name: string | null
  /** The first words of the letter. */
  preview: string
}

export interface Letter extends Omit<LetterSummary, 'preview'> {
  /** Already reduced by the server to the tags the editor makes. */
  body_html: string
}

// --- Document Center -------------------------------------------------------------------------------------------------

export type DocScope = 'company' | 'case' | 'client'
export type DocStatus = 'Draft' | 'Active' | 'Superseded' | 'Archived'
export type DocExpiryState = 'none' | 'valid' | 'expiring' | 'expired'

export interface DocumentSummary {
  id: number
  code: string
  scope: DocScope
  case_code: string | null
  case_name: string | null
  client_code: string | null
  client_name: string | null
  folder_id: number | null
  folder_name: string | null
  title: string
  category: string
  description: string | null
  tags: string[]
  status: DocStatus
  confidentiality: 'Standard' | 'Confidential'
  document_date: string | null
  expiry_date: string | null
  reminder_days: number
  expiry_state: DocExpiryState
  current_version: number
  is_deleted: boolean
  created_timestamp: string
  last_updated_timestamp: string
  file_name: string
  content_type: string
  size_bytes: number
  inline: boolean
  created_by_name: string | null
  updated_by_name: string | null
  /** Where an automatically filed document came from (a bill, an employee's file, an EMD); null for one a person uploaded. */
  source: { type: string; label: string; path: string | null } | null
}

export interface DocumentVersion {
  version_no: number
  file_name: string
  content_type: string
  size_bytes: number
  sha256: string
  change_note: string | null
  uploaded_timestamp: string
  uploaded_by_name: string | null
}

export interface DocumentActivity {
  action: string
  detail: string | null
  at: string
  by_name: string | null
}

export interface DocumentDetail extends DocumentSummary {
  versions: DocumentVersion[]
  activity: DocumentActivity[]
  folder_path: { id: number; name: string }[]
  /** The other places it is filed in as well as its home. */
  placements: { scope: DocScope; case_code: string | null; case_name: string | null; client_code: string | null; client_name: string | null; folder_id: number | null; folder_path: { id: number; name: string }[] }[]
}

export interface DocumentPage {
  items: DocumentSummary[]
  total: number
  limit: number
  offset: number
}

export interface DocumentOptions {
  scopes: DocScope[]
  categories: Record<DocScope, string[]>
  statuses: DocStatus[]
  confidentiality: string[]
  checklist: string[]
  standard_folders: Record<DocScope, string[]>
  accepted: string
  max_mb: number
  max_tags: number
}

export interface DocumentSpaceCounts {
  documents: number
  attention: number
}

export interface DocumentSpaces {
  company: DocumentSpaceCounts
  cases: (DocumentSpaceCounts & { case_code: string; case_name: string; case_status: string | null; client_name: string | null })[]
  clients: (DocumentSpaceCounts & { client_code: string; client_name: string })[]
  trash: number
  /** Every live document once, however many places it is filed in. */
  total: number
}

export interface DocumentOverview {
  total: number
  expired: number
  expiring: number
  drafts: number
  stored_bytes: number
  tags: { tag: string; n: number }[]
  expired_documents: DocumentSummary[]
  expiring_documents: DocumentSummary[]
  recent: DocumentSummary[]
}

export interface DocumentFolder {
  id: number
  parent_id: number | null
  name: string
  documents: number
  /** Made and kept by Orion's automatic filing: it cannot be renamed. */
  system: boolean
}

// ---- The Document Center as a file explorer (documents_explorer.py) ---------------------------------------------------

/** A place in the explorer: `root`, `company`, `clients`, `cases`, `client:CL-1`, `case:CS-1`, `folder:12`, `all` or `trash`. */
export type ExplorerNodeId = string

export type ExplorerKind = 'root' | 'company' | 'clients' | 'cases' | 'client' | 'case' | 'folder' | 'all' | 'trash'

/** What is inside a place that is not a document: a folder, or a client, a case or a group of them to open. */
export interface ExplorerEntry {
  node: ExplorerNodeId
  name: string
  kind: 'folder' | 'client' | 'case' | 'company' | 'group' | 'drive' | 'driveFolder'
  /** Everything inside it, including what is in the folders below. */
  documents: number
  attention?: number
  system?: boolean
  /** Folders directly inside it (a folder) so the tree knows whether it opens. */
  children?: number
  sub?: string | null
}

export interface ExplorerPage {
  node: { id: ExplorerNodeId; kind: ExplorerKind; label: string; system: boolean }
  trail: { id: ExplorerNodeId; label: string }[]
  /** Where a new folder or upload goes; null where nothing can be made (the top levels). */
  space: { scope: DocScope | null; case_code: string | null; client_code: string | null; folder_id: number | null } | null
  can_create_folder: boolean
  folders: ExplorerEntry[]
  /** The place's own documents (or, when searching, everything inside it); null where it has none of its own. */
  documents: DocumentPage | null
  searching: boolean
}

// ---- The SQL editor (sql_lab.py) -----------------------------------------------------------------------------------------

export interface SqlStatus {
  /** What this server allows: nothing, reading only, or changes too (a person still turns "Allow changes" on). */
  mode: 'off' | 'readonly' | 'full'
  can_change: boolean
  database: string
  role: string
  version: string
  default_limit: number
  max_limit: number
  default_timeout: number
  max_timeout: number
  reports_schema: string
  max_statements: number
}

export interface SqlColumn {
  name: string
  type: string
  nullable: boolean
  default: string | null
  pk: boolean
  /** The column it points to, as "schema.table(column)". */
  fk: string | null
}

export interface SqlObject {
  name: string
  kind: string
  rows: number | null
  size: number
  comment: string | null
  /** Holds secrets or private messages: listed, never readable here. */
  private: boolean
  columns: SqlColumn[]
}

export interface SqlCatalog {
  schemas: { name: string; objects: SqlObject[] }[]
  functions: { schema: string; name: string; args: string; returns: string }[]
}

export interface SqlObjectDetail {
  schema: string
  name: string
  kind: string
  owner: string
  comment: string | null
  estimated_rows: number | null
  total_bytes: number
  table_bytes: number
  columns: { name: string; type: string; nullable: boolean; default: string | null; comment: string | null; identity: boolean }[]
  constraints: { name: string; kind: string; definition: string }[]
  referenced_by: { name: string; table: string; definition: string }[]
  indexes: { name: string; definition: string }[]
  triggers: { name: string; definition: string }[]
  stats: Record<string, string | number | null>
  view_sql: string | null
  ddl: string
}

export interface SqlResultSet {
  index: number
  kind: 'rows' | 'command'
  statement: string
  columns?: { name: string; type: string }[]
  rows?: (string | number | boolean | null)[][]
  truncated?: boolean
  row_count: number
  command: string
  duration_ms: number
}

export interface SqlError {
  message: string
  hint: string | null
  detail: string | null
  code: string | null
  position: { line: number; column: number } | null
  statement?: number
}

export interface SqlRun {
  ok: boolean
  blocked?: boolean
  /** Things to confirm before the run goes ahead (an UPDATE with no WHERE, a DROP). */
  needs_confirmation?: string[]
  error?: SqlError | null
  results: SqlResultSet[]
  duration_ms?: number
  rolled_back?: boolean
  changed?: boolean
  run_id: string | null
  mode?: 'read' | 'write'
}

export interface SqlSavedQuery {
  id: number
  title: string
  folder: string | null
  description: string | null
  sql: string
  shared: boolean
  mine: boolean
  owner: string | null
  updated: string
}

export interface SqlHistoryRow {
  id: number
  username: string | null
  sql: string
  mode: 'read' | 'write'
  status: 'ok' | 'error' | 'blocked' | 'cancelled'
  statements: number
  rows_returned: number
  rows_affected: number
  rolled_back: boolean
  duration_ms: number | null
  error: string | null
  at: string
}

// ---- Google Drive in the Document Center (gdrive.py) -----------------------------------------------------------------------

export interface DriveStatus {
  /** How this server reaches a Drive: Google's, a stand-in kept on this computer (development), or none. */
  mode: 'google' | 'fake' | 'off'
  connected: boolean
  account: string | null
  connected_at: string | null
  /** It was connected before this server was set up differently (the fake Drive, then Google's credentials): connect again. */
  reconnect: boolean
  can_connect: boolean
  bills: { mode: 'off' | 'ask' | 'on'; folder_id: string | null; folder_label: string | null }
}

export interface DriveItem {
  id: string
  name: string
  mime: string
  size: number | null
  modified: string | null
  url: string | null
  is_folder: boolean
  /** A real file, or a Google document that can be exported; false for a shortcut, form or map. */
  copyable: boolean
}

export interface DriveListing {
  folder: string
  trail: { id: string; name: string }[]
  searching: boolean
  next: string | null
  folders: DriveItem[]
  files: DriveItem[]
  account: string | null
  mode: 'google' | 'fake' | 'off'
}

export interface DriveCopyResult {
  done: number
  failed: { name: string; message: string }[]
  to: string
  moved: boolean
}

/** A document or bill that is also in Drive. */
export interface DriveLink {
  id: number
  kind: 'bill' | 'document'
  ref: string
  file_id: string | null
  folder_id: string | null
  folder_label: string | null
  name: string | null
  direction: 'to_drive' | 'from_drive'
  /** synced, failed (see `error`, "Try again" retries), or stopped (no longer kept up to date). */
  state: 'synced' | 'failed' | 'stopped'
  error: string | null
  updated: string | null
  url: string | null
  folder_url: string | null
}

export interface MoveResult {
  moved: number
  folders: number
  to: string
}

/** Where a paper Orion filed by itself (a bill, an employee's or an EMD's paper) is kept. */
export interface SourceLocations {
  document_id: number
  deleted: boolean
  /** A person chose where it is kept; false means it is where Orion files it by itself. */
  chosen: boolean
  locations: { home: boolean; node: ExplorerNodeId; label: string }[]
}

export interface DocumentFolders {
  folders: DocumentFolder[]
  loose: number
}

export interface DocumentTargets {
  cases: { case_code: string; case_name: string; case_status: string | null; client_name: string | null }[]
  clients: { client_code: string; client_name: string }[]
}

export interface DocumentFilters {
  q?: string
  scope?: DocScope
  case_code?: string
  client_code?: string
  /** A folder's id, or 'none' for documents not in any folder. */
  folder_id?: string
  category?: string
  status?: string
  expiry?: string
  tag?: string
  trash?: boolean
  sort?: string
  direction?: 'asc' | 'desc'
  limit?: number
  offset?: number
}

/** The details sent when filing a document or changing one. */
export interface DocumentInput {
  scope: DocScope
  case_code?: string | null
  client_code?: string | null
  folder_id?: number | null
  title?: string
  category: string
  description?: string
  tags?: string
  status?: string
  confidentiality?: string
  document_date?: string
  expiry_date?: string
  reminder_days?: string
}

// ------------------------------------------------------------------------------------------------- AI Copilot

export type AiSettings = { enabled: boolean; keep_history: boolean; show_insights: boolean; allow_cloud: boolean }

/** Where an answer was made: by the application itself, by the model on this computer, or by a cloud model. */
export type AiPath = 'app' | 'local' | 'cloud'

export type AiCloudPolicy = 'local_only' | 'no_app_data' | 'local_first' | 'cloud_eligible'

export type AiRouting = {
  local: {
    provider: string
    /** ok, unreachable, no_model, model_missing or error */
    state: string
    model: string
    /** For administrators: what is wrong, and which models are installed. */
    detail: string
    installed: string[]
  }
  cloud: {
    switched_on: boolean
    ready: boolean
    provider: string
    policy: AiCloudPolicy
    you_allow: boolean
    /** Cloud AI could be used for your questions: switched on, permitted by the policy, allowed by you, with budget. */
    usable_by_you: boolean
    /** Administrators only. */
    model?: string
    key_present?: boolean
    budget_usd?: number
    spent_usd?: number
    user_daily?: number
  }
  policies: { id: AiCloudPolicy; label: string }[]
}

export type AiStatus = {
  /** The Copilot can answer now: switched on on the server and for this person. The application answers common questions itself, so no model is needed. */
  available: boolean
  switched_on: boolean
  settings: AiSettings
  usage_today: { requests: number; limit: number }
  routing: AiRouting
  admin?: {
    usage: { day: string; people: number; requests: number; tool_calls: number; tokens_in: number; tokens_out: number }[]
    routes: { path: string; answers: number; cost_usd: number; avg_ms: number; escalated: number; not_ok: number }[]
  }
}

export type AiHealth = {
  local: { state: string; model: string; latency_ms: number | null; detail: string; installed: string[] }
  cloud?: { state: string; model: string; detail: string }
}

/** How an answer was made, as shown on it. */
export type AiRoute = {
  path: AiPath
  label: string
  provider: string
  model: string
  category: string
  category_label: string
  reason: string
  cloud_blocked: string | null
  escalated: boolean
}

export type AiRouteExplanation = {
  classification: { category: string; label: string; confidence: number; reasons: string[] }
  plan: { intent: string; tools: string[] } | null
  route: AiPath
  why: string
  local?: { state: string; model: string }
  cloud_if_local_fails?: { allowed: boolean; blocked_by: string | null; checks: { check: string; ok: boolean; note: string }[] }
  cloud_if_local_is_down?: { allowed: boolean; blocked_by: string | null }
}

export type AiCategory = 'general' | 'analytics' | 'reports' | 'records' | 'tasks'

export type AiConversation = {
  id: number
  title: string
  category: AiCategory
  created_timestamp: string
  updated_timestamp: string
  preview?: string | null
}

/** Something the server made for the screen from real data. The model can place one in an answer but cannot change it. */
export type AiBlock =
  | { id: string; kind: 'metrics'; title?: string; link?: string | null; items: { label: string; value: string; delta?: string | null; tone?: 'positive' | 'negative' | 'neutral' }[] }
  | {
      id: string
      kind: 'table'
      title?: string
      link?: string | null
      columns: { key: string; label: string; format?: 'inr' | 'pct' | 'number' | 'bill' | null; align?: 'left' | 'right' }[]
      rows: Record<string, unknown>[]
    }
  | {
      id: string
      kind: 'chart'
      title?: string
      link?: string | null
      type: 'bar' | 'line' | 'area'
      unit?: 'inr' | 'pct' | 'count'
      x: string[]
      series: { name: string; values: (number | null)[] }[]
    }
  | { id: string; kind: 'file'; name: string; size: number; url: string; format: string; description?: string }
  | { id: string; kind: 'task'; task_kind: 'reminder' | 'task'; title: string; due?: string | null; link?: string | null }

export type AiUiAction =
  | { type: 'navigate'; path: string; label: string }
  | { type: 'appearance'; mode?: 'light' | 'dark' | 'system'; theme?: string }

export type AiPendingAction = {
  id: string
  tool: string
  risk: 'low' | 'medium' | 'high'
  status: 'pending' | 'confirming' | 'done' | 'cancelled' | 'failed' | 'expired'
  result?: string
  preview: {
    title: string
    rows?: { label: string; value: string }[]
    danger?: boolean
    warning?: string
    confirm_label?: string
  }
}

export type AiSource = { label: string; detail?: string; path?: string | null }

export type AiNoticeKind = 'limit' | 'unverified' | 'local_unavailable' | 'cloud_blocked'

/** One piece of an assistant message, in the order it was produced. */
export type AiPart =
  | { type: 'text'; text: string }
  | { type: 'block'; block: AiBlock }
  | { type: 'tool'; id: string; label: string; status: 'running' | 'done' | 'error' | 'denied'; summary?: string }
  | { type: 'ui'; action: AiUiAction }
  | { type: 'confirm'; action: AiPendingAction }
  | { type: 'notice'; kind: AiNoticeKind; text?: string; figures?: string[]; can_use_cloud?: boolean; local_state?: string; reason?: string }
  | { type: 'sources'; sources: AiSource[] }
  | ({ type: 'route' } & AiRoute)
  | { type: 'stopped' }
  | { type: 'action_result'; ok: boolean; title: string; text: string; action_id: string }

export type AiMessage = {
  id: number
  role: 'user' | 'assistant'
  text: string
  parts: AiPart[]
  created_timestamp?: string
}

/** What the server streams while it answers. */
export type AiEvent =
  | { type: 'conversation'; id: number; title: string; category: AiCategory; created: boolean }
  | { type: 'start' }
  | { type: 'plan'; category: string; category_label: string }
  | ({ type: 'route' } & AiRoute)
  | { type: 'reset'; reason: string }
  | { type: 'text'; delta: string }
  | { type: 'block'; block: AiBlock }
  | { type: 'tool'; id: string; label: string; status: 'running' | 'done' | 'error' | 'denied'; summary?: string }
  | { type: 'ui'; action: AiUiAction }
  | { type: 'confirm'; action: AiPendingAction }
  | { type: 'notice'; kind: AiNoticeKind; text?: string; figures?: string[]; can_use_cloud?: boolean; local_state?: string; reason?: string }
  | { type: 'sources'; sources: AiSource[] }
  | { type: 'done'; message_id: number | null; conversation_id: number | null; usage: { in: number; out: number }; ms: number; path?: AiPath }
  | { type: 'error'; code: string; message: string; retryable?: boolean; retry_after?: number }

/** Where the person is, sent with each question so "this dashboard" and "these filters" mean something. */
export type AiPageContext = {
  path?: string
  title?: string
  area?: string
  view?: string
  filters?: Record<string, string>
  entity?: string
  entity_id?: string
  selected?: string[]
}

export type AiInsight = {
  id: string
  severity: 'critical' | 'warning' | 'info'
  headline: string
  body: string
  area: string
  prompt: string
  link?: string | null
}

export type AiTask = {
  id: number
  kind: 'reminder' | 'task'
  title: string
  note: string | null
  due_at: string | null
  status: 'open' | 'done' | 'dismissed'
  link: string | null
}

export type AiAuditRow = {
  id: number
  at: string
  user_id: number
  username: string | null
  conversation_id: number | null
  tool: string
  kind: string
  status: string
  entity: string | null
  summary: string | null
  confirmation_required: boolean
  confirmed_by_user: boolean | null
  duration_ms: number | null
}

// ---------------------------------------------------------------------------------------------------------------- Bank

export type BankDirection = 'in' | 'out'

export type BankMeta = {
  entry_categories: Record<BankDirection, { key: string; label: string }[]>
  category_labels: Record<string, string>
  source_labels: Record<string, string>
  income_categories: string[]
}

export type BankAccountKind = 'bank' | 'cash'

/** An account a payment can go into or come out of: name and kind only (the payment forms). */
export type MoneyAccount = { account_id: number; account_name: string; account_kind: BankAccountKind }

export type BankAccount = {
  configured: boolean
  account_id?: number
  account_kind?: BankAccountKind
  account_name?: string
  bank_name?: string | null
  account_last4?: string | null
  opening_balance?: number
  opening_date?: string
  /** The balance this account should not fall below (optional): Orion only warns. */
  low_balance_floor?: number | null
  balance?: number
  entry_count?: number
}

export type BankAccountInput = {
  account_id?: number
  account_kind?: BankAccountKind
  account_name: string
  bank_name: string
  account_last4: string
  opening_balance: string
  opening_date: string
  /** Empty clears it; left out keeps it. */
  low_balance_floor?: string
  confirm?: boolean
}

/** Something about the balance worth a look: an account below its minimum, or the balance expected to fall below it within two weeks. */
export type BankAlert = {
  key: string
  level: 'critical' | 'warning'
  title: string
  detail: string
  account_id: number | null
  balance: number
  floor: number
  date: string | null
}

export type BankAccountPreview = {
  current_balance: number | null
  new_balance: number
  opening_balance?: number
  opening_date?: string
}

export type BankAccounts = { configured: boolean; accounts: (BankAccount & { balance: number })[]; total: number }

export type BankSummary = {
  configured: boolean
  as_of?: string
  balance?: number
  accounts?: { account_id: number; account_name: string; account_kind: BankAccountKind; balance: number }[]
  account?: { account_id?: number | null; account_kind?: string; account_name: string; bank_name: string | null; account_last4: string | null; opening_balance: number; opening_date: string }
  month?: { from: string; money_in: number; money_out: number; net: number }
  financial_year?: {
    from: string
    money_in: number
    money_out: number
    net: number
    client_receipts: number
    interest: number
    other_income: number
    bank_charges: number
    interest_and_other_income: number
  }
  movements?: number
  reconciliation?: {
    book_unmatched: number
    book_unmatched_net: number
    lines_unmatched: number
    lines_matched: number
    lines_ignored: number
    statement_from: string | null
    statement_to: string | null
    changed_after_matching?: number
  }
  last_import?: { import_id: number; filename: string; uploaded_timestamp: string; period_from: string | null; period_to: string | null; closing_statement_balance: number | null } | null
}

export type BankMonth = {
  month: string
  money_in: number
  money_out: number
  net: number
  closing_balance: number
  client_receipts: number
  other_income: number
  interest: number
}

export type BankSeries = {
  configured: boolean
  months: BankMonth[]
  categories: { category: string; direction: BankDirection; total: number; n: number; label: string }[]
}

export type BankExpected = {
  source: string
  source_ref: string
  due_date: string
  direction: BankDirection
  amount: number
  category: string
  category_label: string
  counterparty: string | null
  description: string | null
  reference: string | null
}

export type BankForecast = {
  configured: boolean
  as_of?: string
  balance?: number
  include_overdue?: boolean
  overdue?: { money_in: number; money_out: number; count: number; items: BankExpected[] }
  windows?: { days: number; money_in: number; money_out: number; projected_balance: number }[]
  weeks?: { week_start: string; week_end: string; money_in: number; money_out: number; balance: number }[]
  lowest?: { balance: number; week_start: string }
  upcoming?: BankExpected[]
  note?: string
}

export type BankLedgerRow = {
  source: string
  source_ref: string
  source_label: string
  move_date: string
  direction: BankDirection
  amount: number
  category: string
  category_label: string
  detail: string | null
  counterparty: string | null
  description: string | null
  reference: string | null
  bill_code: string | null
  balance: number
  reconciled: boolean
  account_id?: number
  account_name?: string
  account_kind?: BankAccountKind
}

export type BankLedger = {
  configured: boolean
  rows: BankLedgerRow[]
  total: number
  page?: number
  page_size?: number
  totals?: { in: number; out: number }
}

export type BankLedgerQuery = {
  date_from?: string
  date_to?: string
  direction?: BankDirection | ''
  category?: string
  source?: string
  q?: string
  reconciled?: 'yes' | 'no' | ''
  account_id?: number
  page?: number
  limit?: number
}

export type BankEntryInput = {
  account_id?: number
  entry_date: string
  direction: BankDirection
  amount: string
  category: string
  counterparty?: string
  description?: string
  reference?: string
}

export type BankEntry = {
  entry_id: number
  entry_date: string
  direction: BankDirection
  amount: number
  category: string
  category_label: string
  counterparty: string | null
  description: string | null
  reference: string | null
  statement_line_id: number | null
  voided_timestamp?: string | null
  void_reason?: string | null
}

export type BankStatementPreview = {
  filename: string
  header_row: number
  headers: string[]
  mapping: Record<string, number>
  columns: Record<string, string>
  sample: string[][]
  line_count: number
  period_from: string | null
  period_to: string | null
  money_in: number
  money_out: number
  opening_balance: number | null
  closing_balance: number | null
  newest_first: boolean
  balance_checked: number
  balance_breaks: number
  balanced: boolean | null
  skipped_rows: number
  issues: { row: number | null; message: string; severity: 'warning' | 'error' }[]
  first_lines: { row: number; date: string; description: string; direction: BankDirection; amount: number }[]
  known_lines: number
  new_lines: number
  already_imported: boolean
  before_opening_date: number
  opening_date: string
  book_balance_before_period: number | null
  sha256: string
  can_import: boolean
}

export type BankImportResult = { import_id: number; line_count: number; new_count: number; duplicate_count: number; auto_matched: number }

export type BankImportRow = {
  import_id: number
  account_id?: number
  filename: string
  uploaded_timestamp: string
  uploaded_by: string | null
  period_from: string | null
  period_to: string | null
  line_count: number
  new_count: number
  duplicate_count: number
  opening_statement_balance: number | null
  closing_statement_balance: number | null
  matched: number
}

export type BankMovement = {
  source: string
  source_ref: string
  move_date: string
  direction: BankDirection
  amount: number
  category: string
  detail: string | null
  counterparty: string | null
  description: string | null
  reference: string | null
  bill_code: string | null
}

export type BankLineMatch = {
  source: string
  source_ref: string
  amount: number
  method: 'auto' | 'manual' | 'created'
  counterparty: string | null
  description: string | null
  reference: string | null
  bill_code: string | null
  move_date: string | null
  category: string | null
}

export type BankLine = {
  line_id: number
  import_id: number
  account_id?: number
  line_date: string
  description: string | null
  reference: string | null
  direction: BankDirection
  amount: number
  balance_after: number | null
  status: 'Unmatched' | 'Matched' | 'Ignored'
  ignore_reason: string | null
  matches: BankLineMatch[]
  guess: { category: string; why: string; category_label: string } | null
}

export type BankLines = { rows: BankLine[]; total: number; page: number; page_size: number }

export type BankSuggestions = {
  line: { line_id: number; line_date: string; description: string | null; reference: string | null; direction: BankDirection; amount: number; status: string }
  candidates: { movement: BankMovement; score: number; days: number; reasons: string[] }[]
  combinations: BankMovement[][]
  guess: { category: string; why: string; category_label: string } | null
  categories: { key: string; label: string }[]
}

export type BankReconciliation = {
  configured: boolean
  state: 'no_statement' | 'reconciled' | 'explained' | 'unexplained'
  cash?: boolean
  account_id?: number
  changed_after_matching?: number
  has_lines?: boolean
  as_of?: string
  statement_balance?: number
  book_balance?: number
  difference?: number
  unexplained?: number
  book_only?: { count: number; money_in: number; money_out: number; net: number }
  statement_only?: { count: number; money_in: number; money_out: number; net: number }
}

/** A statement line matched to something that has since been reversed, cancelled or edited in the book. */
export type BankException = {
  line_id: number
  account_id: number
  line_date: string
  description: string | null
  direction: BankDirection
  line_amount: number
  reason: string
  broken: { source: string; source_ref: string; matched_amount: number; now_amount: number | null; gone: boolean; bill_code: string | null; why: string }[]
}

/** What is owed on an expense: what it came to, what has been paid, and how late the rest is. */
export type PayableRow = {
  expense_code: string
  case_code: string | null
  case_name: string | null
  expense_type: string | null
  description: string | null
  transaction_date: string | null
  due_date: string | null
  /** The day it is to be paid by: the due date, or the transaction date when none was given. */
  pay_by: string
  status: string
  total: number
  paid: number
  left: number
  payment_status: 'Unpaid' | 'Part paid' | 'Paid' | null
  days_late: number | null
  bucket: PayableBucket | null
}

export type PayableBucket = 'not_due' | '0-30' | '31-60' | '61-90' | '90+'

export type PayablesList = {
  items: PayableRow[]
  total: number
  page: number
  limit: number
  summary: { owed: number; overdue: number; open_count: number; due_in_7_days: number }
  ageing: { bucket: PayableBucket; label: string; count: number; amount: number }[]
  /** The cases that have something owed (whichever case is chosen), for the case filter. */
  cases: { case_code: string | null; case_name: string | null; count: number; amount: number }[]
}

export type ExpensePayment = {
  payment_id: number
  amount: number
  paid_date: string
  reference: string | null
  account_id: number | null
  account_name: string | null
  recorded_timestamp: string
  reversed: boolean
  reversed_timestamp: string | null
  reversal_reason: string | null
}

export type PayableDetail = PayableRow & { payments: ExpensePayment[] }

/** One month of salary: what was to be paid, what pay runs have paid, and what is still to pay. */
export type PayrollMonth = {
  month_year: string
  lines: number
  total: number
  paid_lines: number
  paid_total: number
  unpaid_lines: number
  unpaid_total: number
  runs: number
}

export type PayrollUnpaidLine = {
  code: string
  employee_code: string | null
  employee_name: string | null
  days_worked: number | null
  amount: number
  transaction_date: string | null
  /** The case the salary was worked at (an attendance register sets it), else the employee's own case. */
  case_code: string | null
  case_name: string | null
}

export type PayrollUnpaid = {
  month_year: string
  lines: PayrollUnpaidLine[]
  count: number
  total: number
  /** Each case with unpaid salary this month, so the month can be paid one case at a time. */
  cases: { case_code: string | null; case_name: string | null; lines: number; total: number }[]
}

/** One transfer that paid a month's salary lines, from one account, on one day. */
export type PayrollRun = {
  run_id: number
  month_year: string
  paid_date: string
  reference: string | null
  account_id: number | null
  account_name: string | null
  recorded_timestamp: string
  reversed: boolean
  reversed_timestamp: string | null
  reversal_reason: string | null
  lines: number
  total: number
}

export type PayrollRunInput = {
  month_year: string
  line_codes: string[]
  seen_count: number
  seen_total: string
  paid_date: string
  account_id?: number
  reference?: string
  confirm: boolean
}

export type ExpensePaymentInput = { amount: string; paid_date: string; account_id?: number; reference?: string; seen_paid: number; confirm: boolean }

export type BankActivityRow = {
  audit_id: number
  occurred: string
  user_id: number | null
  username: string | null
  action: string
  detail: Record<string, unknown>
}

export type BankAiSuggestions = {
  suggestions: Record<string, { category: string; category_label: string; counterparty: string | null }>
  asked: number
}

// ------------------------------------------------------------------------------------------------------------- Forecast

export type ForecastRow = { month: string; expected: number; p10: number; p90: number; p025: number; p975: number }

export type ForecastHorizon = {
  months: number
  label: string
  through: string
  expected: number
  p10: number
  p90: number
  p025: number
  p975: number
  previous: number | null
  change_pct: number | null
  previous_note: string | null
}

export type ForecastYear = { fy: string; actual_months: number; forecast_months: number; actual: number; complete: boolean; expected: number; p10: number; p90: number }

export type ForecastConfidence = 'high' | 'medium' | 'low' | 'very_low'

export type ForecastMetric = {
  key: string
  label: string
  means: string
  unit: 'inr' | 'count'
  available: boolean
  notes: string[]
  data_through?: string
  first_forecast?: string
  history: { month: string; value: number; fitted: boolean }[]
  forecast: ForecastRow[]
  horizons: ForecastHorizon[]
  years: ForecastYear[]
  model?: { components: { key: string; name: string; weight: number }[]; seasonal: boolean; history_months: number; from: string; derived?: boolean }
  accuracy?: { origins: number; tested?: number; error_pct: number | null; skill: number | null; coverage_80: number | null }
  drivers?: {
    run_rate_per_month: number
    run_rate_per_year: number
    growth_yoy_pct: number | null
    pace_pct_per_year: number | null
    volatility_pct: number | null
    contracted_per_month?: number
  }
  seasonality?: { index: { month: number; effect_pct: number }[]; strength: number } | null
  confidence?: { level: ForecastConfidence; reasons: string[] }
}

export type ForecastPayload = {
  source: 'orion' | 'tally'
  ready: boolean
  message?: string
  as_of?: string
  filters?: Record<string, string>
  active_filters?: { key: string; label: string; value: string; display: string }[]
  options?: Record<string, { id: string; label: string }[]>
  metrics: ForecastMetric[]
  default_metric?: string
}

// --- Tenders (GeM tender searches) -------------------------------------------------------------------------------

/** 'works' is MP Tenders' only. */
export type TenderBidKind = 'all' | 'service' | 'product' | 'works'
export type TenderMatchStatus = 'new' | 'shortlisted' | 'dismissed'
/** GeM, or MP Tenders (the Madhya Pradesh e-procurement portal). */
export type TenderSource = 'gem' | 'mptenders'

export interface TenderSearchInput {
  name: string
  tender_types: string[]
  cities: string[]
  bid_kind: TenderBidKind
  min_value: number | null
  max_value: number | null
  include_unpriced: boolean
  is_active: boolean
  /** The one portal it looks on. */
  portal: TenderSource
}

export interface TenderSearch extends TenderSearchInput {
  search_id: number
  created_timestamp: string
  last_updated_timestamp: string
  new_count?: number
  shortlisted_count?: number
  open_count?: number
}

export interface TenderBid {
  bid_id: number
  bid_number: string
  category: string | null
  quantity: number | null
  ministry: string | null
  department: string | null
  is_high_value: boolean | null
  start_timestamp: string | null
  end_timestamp: string | null
  estimated_value: number | null
  emd_amount: number | null
  /** null: the document does not say (or was not read). */
  emd_required: boolean | null
  epbg_required: boolean | null
  epbg_percent: number | null
  epbg_months: number | null
  contract_period: string | null
  min_turnover: string | null
  experience_years: number | null
  location_source: 'consignee' | 'document' | null
  location_districts: string[] | null
  document_status: 'pending' | 'read' | 'failed'
  document_error: string | null
  matched_city: string | null
  location_confirmed: boolean
  status: TenderMatchStatus
  status_timestamp: string | null
  first_matched_timestamp: string
  location_excerpt: string | null
  document_url: string
  /** Where a seller signs in to GeM to apply (GeM has no link to one bid's application). */
  apply_url: string
  source: TenderSource
  /** The portal's own id: GeM's bid id, or MP's Tender ID. */
  source_ref: string | null
  title: string | null
  reference: string | null
  work_description: string | null
  /** MP Tenders: Goods, Works or Services. */
  tender_category: string | null
  tender_fee: number | null
  tender_fee_total: number | null
  tender_fee_exempt: boolean | null
  emd_exempt: boolean | null
}

export interface TenderRun {
  run_id: number
  trigger: 'schedule' | 'manual'
  status: 'running' | 'succeeded' | 'failed'
  started_timestamp: string
  finished_timestamp: string | null
  searches: number
  requests: number
  bids_seen: number
  bids_new: number
  documents_read: number
  matches_new: number
  note: string | null
  error: string | null
  /** What a running check is doing now, e.g. "Asking GeM about Bhopal, page 12". */
  progress?: string | null
  /** The search a running check is on. */
  current_search_id?: number | null
}

export interface TenderStatus {
  portal: TenderSource
  running: boolean
  active_searches: number
  every_hours: number
  /** A check looks at bids published in this many days that are still open. */
  lookback_days?: number
  next_check: string | null
  last_run: TenderRun | null
  failing: boolean
}

// --- Follow-ups of won opportunities -----------------------------------------------------------------------------------

/** Something to do after an opportunity was won: create its case, or record its EMD. */
export interface Followup {
  id: number
  kind: 'case' | 'emd'
  status: 'open' | 'done' | 'dismissed' | 'withdrawn'
  opportunity_code: string
  opportunity_name: string | null
  tender_id: string | null
  won_on: string | null
  place: string
  created_timestamp: string
  resolved_timestamp: string | null
  resolution_note: string | null
  resolved_by_name: string | null
  /** The opportunity already has a case (an EMD can only be recorded against one). */
  has_case: boolean
  waiting_for_case: boolean
  title: string
  message: string
  /** The form that does it: the record type, its label and the page address. */
  action: { label: string; entity: string; path: string }
}

export interface FollowupList {
  open: Followup[]
  /** What people decided is not needed, newest first, so a mistake can be undone. */
  dismissed: Followup[]
  count: number
}

export interface FollowupContext {
  opportunity: { opportunity_code: string; opportunity_name: string | null; tender_id: string | null; opportunity_status: string; opportunity_case_code: string | null }
  cases: { id: string; label: string }[]
}

// --- Attendance --------------------------------------------------------------------------------------------------------

export type AttendanceStatus = 'Draft' | 'Posted'

export interface AttendanceSheetSummary {
  sheet_code: string
  case_code: string
  case_name: string
  client_name: string | null
  month_year: string
  status: AttendanceStatus
  posted_timestamp: string | null
  last_updated_timestamp: string
  people: number
  employees: number
  workers: number
  amount: string
}

export interface AttendanceLine {
  line_id: number
  employee_code: string | null
  worker_code: string | null
  name: string
  designation: string | null
  days_present: string
  rate_per_day: string
  extra_amount: string
  deduction_amount: string
  amount: string
  calculated: string
  remarks: string | null
  warnings: string[]
  salary_code: string | null
  expense_code: string | null
  paid: boolean
}

export interface AttendanceSheet {
  sheet_code: string
  case_code: string
  case_name: string
  client_name: string | null
  month_year: string
  status: AttendanceStatus
  days_in_month: number
  expense_type_code: string | null
  expense_type_name: string | null
  remarks: string | null
  posted_timestamp: string | null
  posted_by_name: string | null
  created_timestamp: string
  last_updated_timestamp: string
  created_by_name: string | null
  totals: { people: number; employees: number; workers: number; amount: string; payable: number; employee_amount: string; worker_amount: string }
  lines: AttendanceLine[]
  events: { action: string; note: string | null; at: string; by_name: string | null }[]
}

export interface AttendanceRosterPerson {
  employee_code?: string
  worker_code?: string
  name: string
  designation: string | null
  rate_per_day: string | null
  phone?: string | null
  has_salary?: boolean
  case_name?: string | null
}

export interface AttendanceRoster {
  case: { case_code: string; case_name: string; client_name: string | null }
  month_year: string
  days_in_month: number
  employees: AttendanceRosterPerson[]
  workers: AttendanceRosterPerson[]
  previous: {
    sheet_code: string
    month_year: string
    lines: { employee_code: string | null; worker_code: string | null; days_present: string; rate_per_day: string; extra_amount: string; deduction_amount: string }[]
  } | null
  existing: { sheet_code: string; sheet_status: AttendanceStatus } | null
}

export interface AttendanceParsedLine {
  employee_code: string | null
  worker_code: string | null
  new_worker: { name: string; phone: string | null; designation: string | null } | null
  name: string
  designation: string
  days_present: string
  rate_per_day: string
  extra_amount: string
  deduction_amount: string
  amount: string
  calculated: string
  remarks: string
  row: number
}

export interface AttendanceWorker {
  worker_code: string
  name: string
  phone: string | null
  designation: string | null
  rate_per_day: string | null
  case_code: string | null
  case_name: string | null
  status: 'Active' | 'Inactive'
  notes: string | null
  registers: number
}

export interface AttendanceCase {
  case_code: string
  case_name: string
  case_status: string | null
  client_name: string | null
}

// ---- Tasks (the team's work: projects, tasks, reviews, to-do lists) ----------------------------------

export interface TaskPerson {
  id: number
  display_name: string
  has_avatar: boolean
  avatar_version: number
  avatar_url: string | null
}

export type TaskPriority = 'Critical' | 'High' | 'Medium' | 'Low'
export type TaskKind = 'Task' | 'Bug' | 'Story' | 'Epic' | 'Sub-task' | 'Follow-up'
export type StatusCategory = 'todo' | 'doing' | 'review' | 'done'
export type ProjectRole = 'Manager' | 'Member' | 'Viewer'
export type TaskResolution = 'Done' | "Won't do" | 'Duplicate' | 'Cancelled'

export interface TaskStatus {
  id: number
  name: string
  category: StatusCategory
  position: number
  wip_limit: number | null
  tasks: number
}

/** A task as a list or a board card shows it. */
export interface TaskCard {
  id: number
  key: string
  project_key: string
  project_name: string
  title: string
  type: TaskKind
  priority: TaskPriority
  status: { id: number; name: string; category: StatusCategory }
  assignee: TaskPerson | null
  reporter: TaskPerson | null
  reviewer: TaskPerson | null
  parent: { key: string; title: string; type: TaskKind } | null
  sprint: { id: number; name: string; state: 'Planned' | 'Active' | 'Completed' } | null
  start_date: string | null
  due_date: string | null
  overdue: boolean
  estimate_minutes: number | null
  spent_minutes: number
  story_points: number | null
  labels: string[]
  rank: number
  resolution: TaskResolution | null
  resolved: string | null
  created: string
  updated: string
  subtasks: { total: number; done: number }
  checklist: { total: number; done: number }
  comments: number
  attachments: number
  blocked_by: string[]
  recurring: boolean
}

export interface TaskReview {
  id: number
  status: 'Pending' | 'Approved' | 'Changes requested' | 'Withdrawn'
  request_note: string | null
  decision_note: string | null
  requested: string
  decided: string | null
  requester: TaskPerson | null
  reviewer: TaskPerson | null
}

export interface TaskChecklistItem {
  id: number
  text: string
  done: boolean
  position: number
  done_timestamp: string | null
}

export type TaskLinkKind = 'blocks' | 'blocked_by' | 'relates' | 'duplicates' | 'duplicated_by'

export interface TaskLink {
  id: number
  kind: TaskLinkKind
  key: string
  title: string
  status: string
  done: boolean
}

export interface TaskRecordLink {
  id: number
  type: string
  ref: string | null
  label: string | null
  restricted: boolean
}

export interface TaskTime {
  logs: { id: number; minutes: number; date: string; note: string | null; who: TaskPerson | null; can_delete: boolean }[]
  total: number
}

export interface TaskDetail extends TaskCard {
  description: string | null
  project: { key: string; name: string; state: 'Active' | 'Archived'; require_review: boolean; visibility: 'Company' | 'Private' }
  statuses: TaskStatus[]
  subtask_list: TaskCard[]
  checklist_items: TaskChecklistItem[]
  links: TaskLink[]
  records: TaskRecordLink[]
  watchers: TaskPerson[]
  time: TaskTime
  reviews: TaskReview[]
  pending_review: TaskReview | null
  permissions: { role: ProjectRole; can_edit: boolean; can_manage: boolean; can_comment: boolean; can_decide_review: boolean; can_delete: boolean }
  watching: boolean
}

export interface TaskComment {
  id: number
  author: TaskPerson | null
  body: string | null
  deleted: boolean
  created: string
  edited: string | null
  can_edit: boolean
  can_delete: boolean
}

export interface TaskAttachment {
  id: number
  comment_id: number | null
  name: string
  type: string
  size: number
  uploaded: string
  who: TaskPerson | null
  image: boolean
  can_delete: boolean
}

export interface TaskActivityLine {
  id: number
  action: string
  who: TaskPerson | null
  at: string
  text: string
}

export interface TaskProjectSummary {
  key: string
  name: string
  description: string | null
  visibility: 'Company' | 'Private'
  state: 'Active' | 'Archived'
  require_review: boolean
  color: string | null
  lead: TaskPerson | null
  role: ProjectRole | null
  created: string
  open_tasks?: number
  done_tasks?: number
  overdue_tasks?: number
  my_open_tasks?: number
  members?: number
  last_activity?: string | null
}

export interface TaskProject extends Omit<TaskProjectSummary, 'members'> {
  statuses: TaskStatus[]
  members: (TaskPerson & { role: ProjectRole })[]
}

export interface TaskListResult {
  tasks: TaskCard[]
  total: number
  limit: number
  offset: number
}

export interface TaskBoardColumn extends Omit<TaskStatus, 'tasks'> {
  count: number
  tasks: TaskCard[]
}

export interface TaskBoardData {
  project: Pick<TaskProject, 'key' | 'name' | 'state' | 'require_review' | 'visibility' | 'role' | 'lead'>
  columns: TaskBoardColumn[]
  hidden_done: number
  total: number
}

export interface TaskMine {
  buckets: { overdue: TaskCard[]; today: TaskCard[]; week: TaskCard[]; later: TaskCard[]; no_date: TaskCard[] }
  to_review: TaskCard[]
  raised: TaskCard[]
  watching: TaskCard[]
  recently_done: TaskCard[]
  counts: { assigned: number; overdue: number; today: number; to_review: number; unread: number }
  today: string
}

export interface TaskNotification {
  id: number
  kind: string
  text: string
  created: string
  read: boolean
  project_key: string | null
  task_key: string | null
  task_title: string | null
  actor: TaskPerson | null
}

export interface TaskInbox {
  items: TaskNotification[]
  unread: number
  more: boolean
}

export interface TaskMe {
  unread: number
  overdue: number
  due_today: number
  attention: number
}

export interface TodoItem {
  id: number
  list_id: number | null
  text: string
  notes: string | null
  done: boolean
  done_at: string | null
  due_date: string | null
  overdue: boolean
  my_day: string | null
  in_my_day: boolean
  position: number
  task: { key: string; title: string } | null
}

export interface TodoOverview {
  lists: { id: number; name: string; position: number; open: number }[]
  items: TodoItem[]
  inbox_open: number
  my_day_open: number
  today: string
  week: string
}

export interface TaskSprint {
  id: number
  name: string
  goal: string | null
  state: 'Planned' | 'Active' | 'Completed'
  start_date: string | null
  end_date: string | null
  started: string | null
  completed: string | null
  tasks: number
  done: number
  points: number
  points_done: number
  days_left: number | null
}

export interface TaskTemplate {
  id: number
  name: string
  title: string
  description: string | null
  type: TaskKind
  priority: TaskPriority
  assignee: TaskPerson | null
  reviewer: TaskPerson | null
  labels: string[]
  checklist: string[]
  due_offset_days: number
  estimate_minutes: number | null
  frequency: 'daily' | 'weekly' | 'monthly' | 'yearly' | null
  interval_count: number
  weekday: number | null
  day_of_month: number | null
  month_of_year: number | null
  next_run: string | null
  end_date: string | null
  last_run: string | null
  schedule: string
  active: boolean
}

export interface TaskSavedFilter {
  id: number
  name: string
  definition: Record<string, unknown>
  shared: boolean
  mine: boolean
  project_key: string | null
}

export interface TaskReports {
  days: number
  open: number
  unassigned: number
  by_status: { name: string; category: StatusCategory; count: number }[]
  by_priority: { priority: TaskPriority; count: number }[]
  by_type: { type: TaskKind; count: number }[]
  people: { id: number | null; name: string; open: number; overdue: number; finished: number; estimate_minutes: number }[]
  flow: { week: string; created: number; resolved: number }[]
  overdue: { key: string; title: string; due_date: string; priority: TaskPriority; assignee: string | null; days_late: number }[]
  finished_90: number
  cycle_days: number
  time_by_person: { name: string; minutes: number }[]
}

export interface TaskPersonRow extends TaskPerson {
  username: string
  role: string
}

export interface TaskReminder {
  key: string
  title: string
  due: string
  priority: TaskPriority
  project_key: string
  status: string
}

export interface TaskReminders {
  overdue: TaskReminder[]
  today: TaskReminder[]
  soon: TaskReminder[]
  count: number
}

export interface TaskCalendar {
  start: string
  end: string
  days: Record<string, TaskCard[]>
  total: number
}

export interface TaskSearchResult {
  tasks: TaskCard[]
  projects: TaskProjectSummary[]
}

export interface TaskBurndown {
  sprint: TaskSprint
  points: number
  days: { date: string; ideal: number; left: number | null }[]
}

/** The filters a task list understands (they are sent as query parameters). */
export interface TaskFilters {
  project?: string
  assignee?: string
  reporter?: string
  reviewer?: string
  status_id?: string
  category?: string
  priority?: string
  type?: string
  label?: string
  q?: string
  due?: string
  due_from?: string
  due_to?: string
  sprint?: string
  parent?: string
  no_parent?: string
  watching?: string
  involves_me?: string
  open?: string
  done?: string
  sort?: string
  dir?: string
  limit?: string
  offset?: string
  include_archived?: string
  record_type?: string
  record_ref?: string
}

export interface TaskInput {
  title: string
  description?: string | null
  type?: TaskKind
  priority?: TaskPriority
  status_id?: number | null
  assignee_id?: number | null
  reviewer_id?: number | null
  parent_key?: string | null
  sprint_id?: number | null
  start_date?: string | null
  due_date?: string | null
  estimate_minutes?: number | null
  story_points?: number | null
  labels?: string[]
  checklist?: string[]
  records?: { type: string; ref: string }[]
}

export type TaskChanges = Partial<Omit<TaskInput, 'status_id' | 'checklist' | 'records'>>

export interface TaskMoveInput {
  status_id: number
  note?: string
  resolution?: TaskResolution
  reviewer_id?: number
  before_key?: string
  after_key?: string
}


// ---- Clients (a client's page: who, their cases and people, and for billing what they owe) ----------------------------------

export interface ClientDirectoryRow {
  client_code: string
  client_name: string
  client_status: 'Active' | 'Inactive' | null
  client_type: string | null
  firm_priority: string | null
  client_location_city: string | null
  client_location_state: string | null
  group_name: string | null
  cases: number
  active_cases: number
  /** Only for someone who may see billing. */
  owed?: number
  oldest_days?: number | null
}

export interface ClientProfile {
  client: {
    client_code: string
    client_name: string
    client_status: 'Active' | 'Inactive' | null
    client_type: string | null
    firm_priority: string | null
    client_start_date: string | null
    client_end_date: string | null
    client_onboarded: string | null
    client_location_state: string | null
    client_location_city: string | null
    billing_name: string | null
    gstin: string | null
    billing_address: string | null
    client_group_code: string | null
    group_name: string | null
  }
  cases: { case_code: string; case_name: string; case_status: string | null; case_start_date: string | null; case_end_date: string | null; monthly_expected_revenue: number | null; employees: number }[]
  contacts: { contact_code: string; contact_name: string; designation: string | null; contact_role: string | null; contact_status: string | null; is_primary_contact: string | null; email: string | null; phone: string | null; case_code: string | null }[]
  members: { client_code: string; client_name: string; client_status: string | null }[]
  /** null for someone who may not see billing. */
  money: {
    bills: number
    billed: number
    received: number
    credited: number
    owed: number
    oldest_days: number | null
    buckets: number[]
    bucket_labels: string[]
    last_reminder: string | null
    recent: { id: string; bill_number: string; bill_date: string; service_month: string; case_name: string | null; grand_total: number; received_total: number; credited_amount: number | null; status: 'Issued' | 'Cancelled'; gst_paid: boolean }[]
  } | null
}


// ---- Cases, employees and accounts: their pages (read only) ---------------------------------------------------------------------

export interface CaseDirectoryRow {
  case_code: string
  case_name: string
  case_status: string | null
  client_code: string | null
  client_name: string | null
  case_start_date: string | null
  employees: number
  /** Only for someone who may see billing. */
  owed?: number
  oldest_days?: number | null
}

export interface CaseProfile {
  case: {
    case_code: string
    case_name: string
    case_status: string | null
    case_start_date: string | null
    case_end_date: string | null
    monthly_expected_revenue: number | null
    monthly_allowed_km: number | null
    client_code: string | null
    client_name: string | null
    capability_name: string | null
    business_domain_name: string | null
  }
  people: { employee_code: string; employee_name: string; employee_designation: string | null; employee_type: string | null; employee_status: string | null }[]
  contacts: ClientProfile['contacts']
  emds: { emd_code: string; tender_reference: string | null; emd_amount: number; emd_status: string | null; deposit_date: string | null; valid_until: string | null; refund_due_date: string | null }[]
  expenses: { total: number; count: number; recent: { expense_code: string; transaction_date: string | null; amount: number | null; description: string | null; expense_type: string | null }[] }
  money: { bills: number; billed: number; received: number; credited: number; owed: number; oldest_days: number | null; recent: NonNullable<ClientProfile['money']>['recent'] } | null
}

export interface EmployeeDirectoryRow {
  employee_code: string
  employee_name: string
  employee_designation: string | null
  employee_type: string | null
  employee_status: string | null
  client_facing: boolean | null
  case_code: string | null
  case_name: string | null
  client_name: string | null
  manager_name: string | null
}

export interface EmployeeProfile {
  employee: {
    employee_code: string
    employee_name: string
    employee_designation: string | null
    employee_type: string | null
    employee_status: string | null
    client_facing: boolean | null
    emp_start_date: string | null
    emp_end_date: string | null
    manager_code: string | null
    manager_name: string | null
    case_code: string | null
    case_name: string | null
    client_code: string | null
    client_name: string | null
  }
  reports: { employee_code: string; employee_name: string; employee_designation: string | null; employee_status: string | null }[]
  relationships: { contact_code: string; contact_name: string; client_code: string | null }[]
  /** null for someone without bank access. */
  pay: { month_year: string | null; days_worked: number | null; salary_amount: number | null; salary_paid: string | null }[] | null
}

export interface UserOverview {
  user: AppUser
  sessions: { active: number; last_seen: string | null; last_signed_in: string | null; recent: { id: number; signed_in: string; last_seen: string; ip: string | null; device: string; ended: boolean }[] }
  tasks: { open: number; overdue: number; in_review: number; projects: number }
}

// --- PDF tools -------------------------------------------------------------------------------------------------

/** What the PDF tools say about one file before anything is done to it. */
export interface PdfFileInfo {
  name: string
  bytes: number
  pages: number | null
  /** Needs a password to be opened (and none, or a wrong one, was given). */
  locked: boolean
  /** Was locked, and was opened with the password given. */
  was_locked?: boolean
  /** Why it cannot be used, in words; empty when it can. */
  error: string
  width: number | null
  height: number | null
  details?: { title: string; author: string; subject: string; keywords: string }
}

export interface PdfToolLimits {
  max_file_mb: number
  max_total_mb: number
  max_files: number
  max_pages: number
  min_password: number
  tools: Record<string, { label: string; kind: 'pdf' | 'pdfs' | 'images' }>
}

export interface PdfToolResult {
  blob: Blob
  name: string
  /** Pages of the PDF that came out, when it is one. */
  pages: number | null
  /** Files inside the ZIP, when it is one. */
  files: number | null
  note: string
  bytesIn: number
  bytesOut: number
  mediaType: string
}

// ---- EPFO and ESIC by month (Utility > EPFO and ESIC) ----------------------------------------------

export interface StatutoryMonth {
  month: string
  label: string
  epfo_charged: number
  esic_charged: number
  epfo_paid: number
  esic_paid: number
  net: number
  running_net: number
  future: boolean
}

export interface StatutoryPosition {
  fy_start_year: number
  fy_label: string
  months: StatutoryMonth[]
  totals: { epfo_charged: number; esic_charged: number; epfo_paid: number; esic_paid: number }
  /** Over all bills, not one year: what is still to pay. */
  open: { bills: number; epfo: number; esic: number; oldest_bill_date: string | null }
  /** The bills with something to pay, oldest first. */
  oldest: { id: string; bill_number: string; bill_date: string; client: string | null; epfo: number; esic: number }[]
  years: { fy_start_year: number; label: string }[]
}
