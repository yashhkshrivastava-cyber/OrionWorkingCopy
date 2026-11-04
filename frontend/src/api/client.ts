import type { FilterKind, PickList } from '../tables/columnFilter'
import type { AppearancePrefs } from '../theme/types'

/** What the EPFO and ESIC payment screen sends (see recordStatutoryPayment). */
export type StatutoryPaymentInput = { seenPaid: number; epfo: string; esic: string; paidDate: string; reference?: string; accountId?: number }

/** What the GST payment screen sends (see recordGstPayment). */
export type GstPaymentInput = { seenPaid: number; cgst: string; sgst: string; paidDate: string; reference?: string; accountId?: number }

import type { CreditNote, CreditNoteKind, CreditNoteList, CreditNotePreview, GstPosition, DeductionInput, TdsLedger, TdsSuggestion, DocumentDetail, DocumentFilters, DocumentFolders, DocumentInput, DocumentOptions, DocumentOverview, DocumentPage, DocumentSpaces, DocumentTargets, EmployeeDocument, EmployeeDocumentList, Letter, LetterInput, LetterSummary, LetterheadDesign, LetterheadSettings, AccessFlags, BackupStatus, ExploreView, RecordPage, RecordSetInfo, EtlPipeline, EtlRun, EtlRunDetail, BillCard, BillCase, BillFontOptions, SqlCatalog, SqlHistoryRow, SqlObjectDetail, SqlRun, SqlSavedQuery, SqlStatus, DriveCopyResult, DriveLink, DriveListing, DriveStatus, BillListRow, BillProfile, ExplorerPage, MoveResult, SourceLocations, BillVersionRow, DueCase, ReceivablesReport, RecordHistory, SavedBill, ShareDefaults, WarehouseStatus, AppUser, SystemHealth, UserSession, CallRing, FolderContents, ChatAssistAction, ChatAssistResult, ChatMediaKind, ChatMessage, ChatPage, ChatPeer, ChatReaction, ChatSearchHit, ChatSettings, ChatSharedItem, ChatThread, ChatThreadDetail, DashboardFilters, DashboardView, EntityMeta, SignupRequest, AiAuditRow, AiCategory, AiCloudPolicy, AiHealth, AiRouteExplanation, AiConversation, AiEvent, AiInsight, AiMessage, AiPageContext, AiSettings, AiStatus, AiTask } from '../types'
import type { AiOutcome } from '../components/ai/AiTask'
import type { BankAccount, BankAccountInput, BankAccounts, BankAlert, BankException, ExpensePaymentInput, MoneyAccount, PayableBucket, PayableDetail, PayablesList, PayrollMonth, PayrollRun, PayrollRunInput, PayrollUnpaid, BankAccountPreview, BankActivityRow, BankAiSuggestions, BankEntry, BankEntryInput, BankForecast, BankImportResult, BankImportRow, BankLedger, BankLedgerQuery, BankLines, BankMeta, BankReconciliation, BankSeries, BankStatementPreview, BankSuggestions, BankSummary } from '../types'

import type { ForecastPayload, FollowupContext, FollowupList } from '../types'
import type { PdfFileInfo, PdfToolLimits, PdfToolResult } from '../types'
import type { StatutoryPosition } from '../types'
import type { AttendanceCase, AttendanceParsedLine, AttendanceRoster, AttendanceRosterPerson, AttendanceSheet, AttendanceSheetSummary, AttendanceWorker } from '../types'
import type { TenderBid, TenderMatchStatus, TenderSearch, TenderSearchInput, TenderSource, TenderStatus } from '../types'
import type { TaskActivityLine, TaskAttachment, TaskBoardData, TaskBurndown, TaskCalendar, TaskChanges, TaskChecklistItem, TaskComment, TaskDetail, TaskFilters, TaskInbox, TaskInput, TaskKind, TaskLink, TaskLinkKind, TaskListResult, TaskMe, TaskMine, TaskMoveInput, TaskPerson, TaskPersonRow, TaskPriority, TaskProject, TaskProjectSummary, TaskRecordLink, TaskReminders, TaskReports, TaskSavedFilter, TaskSearchResult, TaskSprint, TaskStatus, TaskTemplate, TaskTime, TodoOverview, ProjectRole, StatusCategory } from '../types'
import type { CaseDirectoryRow, CaseProfile, ClientDirectoryRow, ClientProfile, EmployeeDirectoryRow, EmployeeProfile, UserOverview } from '../types'
import { idempotencyHeader } from './idempotency'

const API = '/api'

/** Fired when the server stops accepting this browser's session. AuthContext listens and signs the screen out. */
export const SESSION_ENDED_EVENT = 'orion:session-ended'

/** An answer that was not a success. ``status`` lets a screen tell a conflict (409) from a mistake it can correct. */
export class ApiError extends Error {
  status: number

  constructor(message: string, status: number) {
    super(message)
    this.name = 'ApiError'
    this.status = status
  }
}

async function request<T>(path: string, options: RequestInit = {}): Promise<T> {
  // The headers are merged AFTER the other options: spreading `options` last would replace them all, so a call that passed one
  // header (the idempotency key) would lose Content-Type and be refused.
  const res = await fetch(`${API}${path}`, {
    credentials: 'include',
    ...options,
    headers: {
      'Content-Type': 'application/json',
      ...options.headers,
    },
  })

  if (!res.ok) {
    let detail = res.statusText
    try {
      const body = await res.json()
      detail = body.detail || detail
    } catch {
      /* ignore */
    }
    // A 401 on anything but the sign-in doors means the server has ended this session (signed out elsewhere, password changed,
    // account disabled): tell the app, which returns to the sign-in page instead of leaving every screen showing errors.
    if (res.status === 401 && !path.startsWith('/auth/')) window.dispatchEvent(new Event(SESSION_ENDED_EVENT))
    throw new ApiError(typeof detail === 'string' ? detail : JSON.stringify(detail), res.status)
  }

  if (res.status === 204) return undefined as T
  return res.json()
}

async function parseError(res: Response): Promise<string> {
  let detail = res.statusText
  try {
    const body = await res.json()
    detail = body.detail || detail
  } catch {
    /* ignore */
  }
  return typeof detail === 'string' ? detail : JSON.stringify(detail)
}

export type ExcelUploadResult = {
  ok: boolean
  inserted: number
  updated?: number
  errors: { row: number; message: string }[]
  /** Rows that look like another record (saved all the same): a thing to look at, not a refusal. */
  warnings?: { row: number; message: string }[]
}

function slug(name: string): string {
  return name.toLowerCase().replace(/\s+/g, '_')
}

export type PreviewQuery = {
  q?: string
  /** Filters on columns, encoded (tables/columnFilter.ts `encodeFilters`). */
  f?: string
  sort?: string
  dir?: 'asc' | 'desc'
}

export type PreviewPayload = {
  columns: string[]
  rows: Record<string, unknown>[]
  total: number
  matched?: number
  limit?: number
  /** What each column holds, so the headers offer the right conditions. */
  kinds?: Record<string, FilterKind>
}

function previewQs(limit: number | 'all', query: PreviewQuery = {}) {
  const params = new URLSearchParams()
  params.set('limit', String(limit))
  if (query.q) params.set('q', query.q)
  if (query.f) params.set('f', query.f)
  if (query.sort) {
    params.set('sort', query.sort)
    params.set('dir', query.dir || 'desc')
  }
  return params.toString()
}

function valuesQs(column: string, query: PreviewQuery, contains: string) {
  const params = new URLSearchParams({ column })
  if (query.q) params.set('q', query.q)
  if (query.f) params.set('f', query.f)
  if (contains) params.set('contains', contains)
  return params.toString()
}

async function downloadFile(path: string, filename: string) {
  const res = await fetch(`${API}${path}`, { credentials: 'include' })
  if (!res.ok) throw new Error(await parseError(res))
  const blob = await res.blob()
  const url = URL.createObjectURL(blob)
  const link = document.createElement('a')
  link.href = url
  link.download = filename
  document.body.appendChild(link)
  link.click()
  link.remove()
  URL.revokeObjectURL(url)
}

function recordQuery(
  filters: Record<string, string | undefined>,
  options: { q?: string; f?: string; sort?: string; dir?: string; page?: number; size?: number; export?: boolean; measure?: string },
): string {
  const params = new URLSearchParams()
  Object.entries(filters).forEach(([key, value]) => value && params.set(key, value))
  if (options.q) params.set('q', options.q)
  if (options.f) params.set('f', options.f)
  if (options.sort) params.set('sort', options.sort)
  if (options.dir) params.set('dir', options.dir)
  if (options.page) params.set('page', String(options.page))
  if (options.size) params.set('size', String(options.size))
  if (options.export) params.set('export', 'true')
  if (options.measure) params.set('measure', options.measure)
  return params.toString()
}

export const api = {
  login: (username: string, password: string) =>
    request('/auth/login', { method: 'POST', body: JSON.stringify({ username, password }) }),

  register: (body: {
    username: string
    display_name: string
    password: string
    email: string
    phone?: string
  }) => request('/auth/register', { method: 'POST', body: JSON.stringify(body) }),

  forgotPassword: (body: { username: string; email: string }) =>
    request('/auth/forgot-password', { method: 'POST', body: JSON.stringify(body) }),

  resetPasswordStatus: (token: string) =>
    request<{ valid: boolean }>(`/auth/reset-password?token=${encodeURIComponent(token)}`),

  resetPassword: (body: { token: string; password: string }) =>
    request('/auth/reset-password', { method: 'POST', body: JSON.stringify(body) }),

  logout: () => request('/auth/logout', { method: 'POST' }),

  systemHealth: () => request<SystemHealth>('/health/details'),

  mySessions: () => request<{ sessions: UserSession[] }>('/auth/sessions'),

  endSession: (id: number) => request<{ ok: boolean }>(`/auth/sessions/${id}`, { method: 'DELETE' }),

  signOutOtherDevices: () => request<{ ok: boolean; ended: number }>('/auth/sessions/revoke-others', { method: 'POST' }),

  signOutUserEverywhere: (id: number) => request<{ ok: boolean; ended: number }>(`/users/${id}/sign-out`, { method: 'POST' }),

  me: () => request('/auth/me'),

  updateProfile: (body: {
    display_name?: string
    preferred_theme?: 'light' | 'dark'
    appearance?: AppearancePrefs
    email?: string
    phone?: string
  }) => request('/auth/me', { method: 'PATCH', body: JSON.stringify(body) }),

  uploadAvatar: async (file: File) => {
    const body = new FormData()
    body.append('file', file)
    const res = await fetch(`${API}/auth/me/avatar`, {
      method: 'POST',
      credentials: 'include',
      body,
    })
    if (!res.ok) throw new Error(await parseError(res))
    return res.json()
  },

  removeAvatar: () => request('/auth/me/avatar', { method: 'DELETE' }),

  avatarUrl: (userId: number, version = 0) =>
    `${API}/auth/avatar/${userId}${version ? `?v=${version}` : ''}`,

  dashboard: (view: string, filters: DashboardFilters = {}) => {
    const query = new URLSearchParams(
      Object.entries(filters).filter(([, value]) => Boolean(value)) as [string, string][],
    ).toString()
    return request<DashboardView>(
      `/dashboard/${encodeURIComponent(view)}${query ? `?${query}` : ''}`,
    )
  },

  /** The record sets the signed-in user may open from a dashboard chart. */
  dashboardRecordSets: () => request<{ datasets: RecordSetInfo[] }>('/dashboard/records'),

  /** The rows behind a dashboard figure, filtered the way the charts are. */
  dashboardRecords: (
    dataset: string,
    filters: Record<string, string | undefined>,
    options: { q?: string; f?: string; sort?: string; dir?: 'asc' | 'desc'; page?: number; size?: number; export?: boolean; measure?: string } = {},
  ) => request<RecordPage>(`/dashboard/records/${encodeURIComponent(dataset)}?${recordQuery(filters, options)}`),

  /** The same for a Tally figure: billed documents, or the ledgers behind a books balance. */
  tallyRecords: (
    dataset: string,
    filters: Record<string, string | undefined>,
    options: { q?: string; f?: string; sort?: string; dir?: 'asc' | 'desc'; page?: number; size?: number; export?: boolean; measure?: string } = {},
  ) => request<RecordPage>(`/tally-dashboard/records/${encodeURIComponent(dataset)}?${recordQuery(filters, options)}`),

  /** A key figure by year, month and every dimension that applies, for the drill-down opened from its tile. */
  exploreMeasure: (source: 'orion' | 'tally', measure: string, filters: Record<string, string | undefined>) => {
    const query = recordQuery(filters, {})
    const base = source === 'orion' ? '/dashboard/explore' : '/tally-dashboard/explore'
    return request<ExploreView>(`${base}/${encodeURIComponent(measure)}${query ? `?${query}` : ''}`)
  },

  tallyDashboard: (filters: DashboardFilters = {}) => {
    const query = new URLSearchParams(
      Object.entries(filters).filter(([, value]) => Boolean(value)) as [string, string][],
    ).toString()
    return request<DashboardView>(`/tally-dashboard${query ? `?${query}` : ''}`)
  },

  billingCases: () => request<{ cases: BillCase[] }>('/billing/cases'),

  billingProfile: () => request<BillProfile>('/billing/profile'),

  saveBillingProfile: (profile: BillProfile) =>
    request<BillProfile>('/billing/profile', { method: 'PUT', body: JSON.stringify(profile) }),

  billingFonts: () => request<BillFontOptions>('/billing/fonts'),

  /** A bill's own typeface and size; both null make it follow the company's setting again. Not a new version of the bill. */
  setBillFont: (id: string, font: { font_family: string | null; font_size: number | null }) =>
    request<SavedBill>(`/billing/bills/${encodeURIComponent(id)}/font`, { method: 'PUT', body: JSON.stringify(font) }),

  billingNextNumber: (day: string) =>
    request<{ fy: string; seq: number; bill_number: string }>(`/billing/next-number?date=${encodeURIComponent(day)}`),

  billingYears: () => request<{ years: { id: string; label: string }[] }>('/billing/years'),

  /** The register. Any of a financial year, a search, a client, a case and the month a bill is for; none means every bill (the newest 500). */
  bills: (fy?: string, q?: string, filters: { client_code?: string; case_code?: string; month?: string } = {}) => {
    const params = new URLSearchParams()
    if (fy) params.set('fy', fy)
    if (q) params.set('q', q)
    if (filters.client_code) params.set('client_code', filters.client_code)
    if (filters.case_code) params.set('case_code', filters.case_code)
    if (filters.month) params.set('month', filters.month)
    const query = params.toString()
    return request<{ bills: BillListRow[] }>(`/billing/bills${query ? `?${query}` : ''}`)
  },

  bill: (id: string) => request<SavedBill>(`/billing/bills/${encodeURIComponent(id)}`),

  /** The hover card on a bill number. Found by the bill's code or by the number printed on it. */
  billCard: (by: { number?: string; code?: string }) => {
    const params = new URLSearchParams()
    if (by.code) params.set('code', by.code)
    else if (by.number) params.set('number', by.number)
    return request<BillCard>(`/billing/card?${params.toString()}`)
  },

  /** `key` is this form's idempotency key (see idempotency.ts): the same request sent twice saves one bill. */
  createBill: (body: Record<string, unknown>, key?: string) =>
    request<SavedBill>('/billing/bills', { method: 'POST', body: JSON.stringify(body), headers: idempotencyHeader(key) }),

  updateBill: (id: string, body: Record<string, unknown>, key?: string) =>
    request<SavedBill>(`/billing/bills/${encodeURIComponent(id)}`, { method: 'PUT', body: JSON.stringify(body), headers: idempotencyHeader(key) }),

  billVersions: (id: string) =>
    request<{ versions: BillVersionRow[] }>(`/billing/bills/${encodeURIComponent(id)}/versions`),

  billVersion: (id: string, versionNo: number) =>
    request<SavedBill>(`/billing/bills/${encodeURIComponent(id)}/versions/${versionNo}`),

  cancelBill: (id: string, reason: string) =>
    request<SavedBill>(`/billing/bills/${encodeURIComponent(id)}/cancel`, {
      method: 'POST',
      body: JSON.stringify({ reason }),
    }),

  /** The accounts a payment can be received into or paid from (names only). */
  moneyAccounts: () => request<{ accounts: MoneyAccount[] }>('/billing/accounts'),

  recordBillPayment: (id: string, amount: string, receivedDate: string, key?: string, accountId?: number, deductions?: DeductionInput[]) =>
    request<SavedBill>(`/billing/bills/${encodeURIComponent(id)}/payments`, {
      method: 'POST',
      body: JSON.stringify({ amount, received_date: receivedDate, account_id: accountId, deductions: deductions ?? [] }),
      headers: idempotencyHeader(key),
    }),

  tdsLedger: (filters: { fy?: number; client_code?: string; section?: string; match?: string; quarter?: string } = {}) => {
    const query = new URLSearchParams()
    for (const [key, value] of Object.entries(filters)) if (value !== undefined && value !== '') query.set(key, String(value))
    return request<TdsLedger>(`/tds/ledger${query.size ? `?${query}` : ''}`)
  },

  creditNotes: (filters: { status?: string; fy?: number } = {}) => {
    const query = new URLSearchParams()
    if (filters.status) query.set('status', filters.status)
    if (filters.fy) query.set('fy', String(filters.fy))
    return request<CreditNoteList>(`/credit-notes${query.size ? `?${query}` : ''}`)
  },

  billCreditNotes: (billCode: string) => request<{ credit_notes: CreditNote[] }>(`/credit-notes/bill/${encodeURIComponent(billCode)}`),

  creditNotePreview: (billCode: string, total: string) =>
    request<CreditNotePreview>(`/credit-notes/preview?bill_code=${encodeURIComponent(billCode)}&total=${encodeURIComponent(total)}`),

  makeCreditNote: (body: { bill_code: string; kind: CreditNoteKind; total: string; note_date: string; reason: string }, key?: string) =>
    request<CreditNote>('/credit-notes', { method: 'POST', body: JSON.stringify(body), headers: idempotencyHeader(key) }),

  approveCreditNote: (id: number, seenTotal: number) =>
    request<CreditNote>(`/credit-notes/${id}/approve`, { method: 'POST', body: JSON.stringify({ confirm: true, seen_total: seenTotal }) }),

  rejectCreditNote: (id: number, note: string) => request<CreditNote>(`/credit-notes/${id}/reject`, { method: 'POST', body: JSON.stringify({ note }) }),

  withdrawCreditNote: (id: number) => request<CreditNote>(`/credit-notes/${id}/withdraw`, { method: 'POST' }),

  reverseCreditNote: (id: number, reason: string) => request<CreditNote>(`/credit-notes/${id}/reverse`, { method: 'POST', body: JSON.stringify({ reason }) }),

  gstPosition: (fy?: number) => request<GstPosition>(`/gst/position${fy ? `?fy=${fy}` : ''}`),

  tdsSuggestion: (billCode: string) => request<TdsSuggestion>(`/tds/suggestion?bill_code=${encodeURIComponent(billCode)}`),

  tdsMatch: (deductionId: number, matched: boolean, certificateRef?: string) =>
    request<{ deduction_id: number; matched: boolean; certificate_ref: string | null }>(`/tds/deductions/${deductionId}/matched`, {
      method: 'PUT',
      body: JSON.stringify({ matched, certificate_ref: certificateRef || null }),
    }),

  reverseBillPayment: (id: string, entryId: string) =>
    request<SavedBill>(`/billing/bills/${encodeURIComponent(id)}/payments/${encodeURIComponent(entryId)}`, {
      method: 'DELETE',
    }),

  /**
   * Record a payment of GST to the government: an amount of CGST, of SGST or of both, on a day. A bill's GST may be paid in several payments.
   * `seenPaid` is how much had been paid when the person opened the bill: if somebody recorded more since, the server answers 409 and writes
   * nothing.
   */
  recordGstPayment: (id: string, payment: GstPaymentInput) =>
    request<SavedBill>(`/billing/bills/${encodeURIComponent(id)}/gst-payments`, {
      method: 'POST',
      body: JSON.stringify({
        confirm: true,
        seen_paid: payment.seenPaid,
        cgst: payment.cgst,
        sgst: payment.sgst,
        paid_date: payment.paidDate,
        reference: payment.reference || undefined,
        account_id: payment.accountId,
      }),
    }),

  /** Take a recorded GST payment back (everything recorded together), with the reason. It stays in the history, marked reversed. */
  /**
   * Records a payment of EPFO and/or ESIC on a bill. `seenPaid` is what the person saw as paid when they opened the bill; if it has changed, the server refuses (409).
   */
  recordStatutoryPayment: (id: string, payment: StatutoryPaymentInput) =>
    request<SavedBill>(`/billing/bills/${encodeURIComponent(id)}/statutory-payments`, {
      method: 'POST',
      body: JSON.stringify({
        confirm: true,
        seen_paid: payment.seenPaid,
        epfo: payment.epfo,
        esic: payment.esic,
        paid_date: payment.paidDate,
        reference: payment.reference || undefined,
        account_id: payment.accountId,
      }),
    }),

  /** Takes a recorded EPFO or ESIC payment back (everything recorded together), with the reason; the payment stays in the history. */
  reverseStatutoryPayment: (id: string, batchId: string, reason: string) =>
    request<SavedBill>(`/billing/bills/${encodeURIComponent(id)}/statutory-payments/${encodeURIComponent(batchId)}/reverse`, {
      method: 'POST',
      body: JSON.stringify({ confirm: true, reason }),
    }),

  statutoryPosition: (fy?: number) => request<StatutoryPosition>(`/statutory/position${fy ? `?fy=${fy}` : ''}`),

  reverseGstPayment: (id: string, batchId: string, reason: string) =>
    request<SavedBill>(`/billing/bills/${encodeURIComponent(id)}/gst-payments/${encodeURIComponent(batchId)}/reverse`, {
      method: 'POST',
      body: JSON.stringify({ confirm: true, reason }),
    }),

  billsDueFor: (month?: string) =>
    request<{ month: string; cases: DueCase[]; billed?: { cases: number; total: number } }>(`/billing/due${month ? `?month=${encodeURIComponent(month)}` : ''}`),

  receivables: () => request<ReceivablesReport>('/billing/receivables'),

  /** Sending a bill, or a reminder for a client's unpaid bills. `target` is the path under /billing. */
  shareDefaults: (target: string) => request<ShareDefaults>(`/billing/${target}/share`),

  shareByEmail: (target: string, to: string, message: string, letterhead = false) =>
    request<{ ok: boolean; to: string }>(`/billing/${target}/email`, {
      method: 'POST',
      body: JSON.stringify({ to, message, letterhead }),
    }),

  shareByWhatsApp: (target: string, phone: string, message: string) =>
    request<{ url: string }>(`/billing/${target}/whatsapp`, {
      method: 'POST',
      body: JSON.stringify({ phone, message }),
    }),

  /** Fetches a PDF the API makes and saves it, so the signed-in cookie is used and no link is exposed. */
  downloadPdf: async (path: string, filename: string) => {
    const res = await fetch(`${API}/billing/${path}`, { credentials: 'include' })
    if (!res.ok) throw new Error(await parseError(res))
    const url = URL.createObjectURL(await res.blob())
    const link = document.createElement('a')
    link.href = url
    link.download = filename
    document.body.appendChild(link)
    link.click()
    link.remove()
    setTimeout(() => URL.revokeObjectURL(url), 1000)
  },

  /** A PDF the API makes, kept in memory for the in-app preview. `path` is the whole path under /api. */
  pdfBlob: async (path: string) => {
    const res = await fetch(`${API}${path}`, { credentials: 'include' })
    if (!res.ok) throw new Error(await parseError(res))
    return res.blob()
  },

  // --- Letterhead ---------------------------------------------------------------------------------------------

  // --- Employee documents -------------------------------------------------------------------------------------

  /** The kinds of document and file that can be uploaded, for the Add screen where there is no employee yet. */
  employeeDocumentOptions: () => request<Omit<EmployeeDocumentList, 'documents'>>('/employees/document-options'),

  employeeDocuments: (employeeCode: string) =>
    request<EmployeeDocumentList>(`/employees/${encodeURIComponent(employeeCode)}/documents`),

  uploadEmployeeDocument: async (employeeCode: string, file: File, docType: string, title: string) => {
    const body = new FormData()
    body.append('file', file)
    body.append('doc_type', docType)
    body.append('title', title)
    const res = await fetch(`${API}/employees/${encodeURIComponent(employeeCode)}/documents`, {
      method: 'POST',
      credentials: 'include',
      body,
    })
    if (!res.ok) throw new Error(await parseError(res))
    return res.json() as Promise<EmployeeDocument>
  },

  /** One document's file, kept in memory to show or save, so the signed-in cookie is used and no link is exposed. */
  employeeDocumentFile: async (employeeCode: string, documentId: number) => {
    const res = await fetch(`${API}/employees/${encodeURIComponent(employeeCode)}/documents/${documentId}/file`, {
      credentials: 'include',
    })
    if (!res.ok) throw new Error(await parseError(res))
    return res.blob()
  },

  deleteEmployeeDocument: (employeeCode: string, documentId: number) =>
    request<{ ok: boolean }>(`/employees/${encodeURIComponent(employeeCode)}/documents/${documentId}`, { method: 'DELETE' }),

  // --- EMD documents (the same shape as an employee's) ---------------------------------------------------------

  emdDocumentOptions: () => request<Omit<EmployeeDocumentList, 'documents'>>('/emds/document-options'),

  emdDocuments: (emdCode: string) => request<EmployeeDocumentList>(`/emds/${encodeURIComponent(emdCode)}/documents`),

  uploadEmdDocument: async (emdCode: string, file: File, docType: string, title: string) => {
    const body = new FormData()
    body.append('file', file)
    body.append('doc_type', docType)
    body.append('title', title)
    const res = await fetch(`${API}/emds/${encodeURIComponent(emdCode)}/documents`, { method: 'POST', credentials: 'include', body })
    if (!res.ok) throw new Error(await parseError(res))
    return res.json() as Promise<EmployeeDocument>
  },

  emdDocumentFile: async (emdCode: string, documentId: number) => {
    const res = await fetch(`${API}/emds/${encodeURIComponent(emdCode)}/documents/${documentId}/file`, { credentials: 'include' })
    if (!res.ok) throw new Error(await parseError(res))
    return res.blob()
  },

  deleteEmdDocument: (emdCode: string, documentId: number) =>
    request<{ ok: boolean }>(`/emds/${encodeURIComponent(emdCode)}/documents/${documentId}`, { method: 'DELETE' }),

  letterheadDesign: () => request<LetterheadDesign>('/letterhead/design'),

  saveLetterheadSettings: (settings: LetterheadSettings) =>
    request<LetterheadDesign>('/letterhead/design', { method: 'PUT', body: JSON.stringify(settings) }),

  uploadLetterheadImage: async (part: 'header' | 'footer', file: File) => {
    const body = new FormData()
    body.append('file', file)
    const res = await fetch(`${API}/letterhead/design/${part}`, { method: 'POST', credentials: 'include', body })
    if (!res.ok) throw new Error(await parseError(res))
    return res.json() as Promise<LetterheadDesign>
  },

  resetLetterheadImage: (part: 'header' | 'footer') =>
    request<LetterheadDesign>(`/letterhead/design/${part}`, { method: 'DELETE' }),

  letters: (search = '') =>
    request<{ letters: LetterSummary[] }>(`/letterhead/letters${search ? `?q=${encodeURIComponent(search)}` : ''}`),

  letter: (id: number | string) => request<Letter>(`/letterhead/letters/${encodeURIComponent(String(id))}`),

  createLetter: (letter: LetterInput) =>
    request<Letter>('/letterhead/letters', { method: 'POST', body: JSON.stringify(letter) }),

  updateLetter: (id: number, letter: LetterInput) =>
    request<Letter>(`/letterhead/letters/${id}`, { method: 'PUT', body: JSON.stringify(letter) }),

  deleteLetter: (id: number) => request<{ ok: boolean }>(`/letterhead/letters/${id}`, { method: 'DELETE' }),

  /** Sends a PDF made elsewhere and gets it back on the letterhead. Nothing is stored on the server. */
  stampPdf: async (
    file: File,
    options: { fit: boolean; firstPageOnly: boolean; header: boolean; footer: boolean },
  ) => {
    const body = new FormData()
    body.append('file', file)
    body.append('fit', String(options.fit))
    body.append('first_page_only', String(options.firstPageOnly))
    body.append('header', String(options.header))
    body.append('footer', String(options.footer))
    const res = await fetch(`${API}/letterhead/stamp`, { method: 'POST', credentials: 'include', body })
    if (!res.ok) throw new Error(await parseError(res))
    return { blob: await res.blob(), pages: Number(res.headers.get('X-Orion-Pages') ?? 0) }
  },

  // --- PDF tools ----------------------------------------------------------------------------------------------

  /** What a job may be (sizes, number of files) and the list of tools. */
  pdfToolLimits: () => request<PdfToolLimits>('/pdf-tools/limits'),

  /** Pages, size and whether each file is locked, before anything is done. `passwords` is one per file, in order. */
  pdfInspect: async (files: File[], passwords: string[] = []) => {
    const body = new FormData()
    for (const file of files) body.append('files', file)
    body.append('options', JSON.stringify({ passwords }))
    const res = await fetch(`${API}/pdf-tools/inspect`, { method: 'POST', credentials: 'include', body })
    if (!res.ok) throw new Error(await parseError(res))
    return ((await res.json()) as { files: PdfFileInfo[] }).files
  },

  /** Does one tool to the files and returns what came out (a PDF, a ZIP or a text file). Nothing is kept on the server. */
  pdfTool: async (tool: string, files: File[], options: Record<string, unknown>): Promise<PdfToolResult> => {
    const body = new FormData()
    for (const file of files) body.append('files', file)
    body.append('options', JSON.stringify(options))
    const res = await fetch(`${API}/pdf-tools/${encodeURIComponent(tool)}`, { method: 'POST', credentials: 'include', body })
    if (!res.ok) throw new Error(await parseError(res))
    const summary = JSON.parse(res.headers.get('X-Orion-Result') ?? '{}') as {
      name?: string
      pages?: number | null
      files?: number | null
      note?: string
      bytes_in?: number
      bytes_out?: number
    }
    const blob = await res.blob()
    return {
      blob,
      name: summary.name ?? 'Result',
      pages: summary.pages ?? null,
      files: summary.files ?? null,
      note: summary.note ?? '',
      bytesIn: summary.bytes_in ?? 0,
      bytesOut: summary.bytes_out ?? blob.size,
      mediaType: res.headers.get('Content-Type') ?? blob.type,
    }
  },

  // --- Document Center ----------------------------------------------------------------------------------------
  documentOptions: () => request<DocumentOptions>('/documents/options'),

  documentOverview: () => request<DocumentOverview>('/documents/overview'),

  documentSpaces: () => request<DocumentSpaces>('/documents/spaces'),

  documentTargets: (q: string) => request<DocumentTargets>(`/documents/targets?q=${encodeURIComponent(q)}`),

  documents: (filters: DocumentFilters) => {
    const qs = new URLSearchParams()
    for (const [key, value] of Object.entries(filters)) {
      if (value !== undefined && value !== '' && value !== false) qs.set(key, String(value))
    }
    return request<DocumentPage>(`/documents/items?${qs}`)
  },

  document: (id: number) => request<DocumentDetail>(`/documents/items/${id}`),

  uploadDocument: async (input: DocumentInput, file: File) => {
    const body = new FormData()
    body.append('file', file)
    for (const [key, value] of Object.entries(input)) {
      if (value !== undefined && value !== null) body.append(key, String(value))
    }
    const res = await fetch(`${API}/documents/items`, { method: 'POST', credentials: 'include', body })
    if (!res.ok) throw new Error(await parseError(res))
    return res.json() as Promise<{ id: number; code: string; title: string; duplicates: string[] }>
  },

  updateDocument: (id: number, changes: Record<string, unknown>) =>
    request<{ ok: boolean }>(`/documents/items/${id}`, { method: 'PATCH', body: JSON.stringify(changes) }),

  deleteDocument: (id: number) => request<{ ok: boolean }>(`/documents/items/${id}`, { method: 'DELETE' }),

  restoreDocument: (id: number) => request<{ ok: boolean }>(`/documents/items/${id}/restore`, { method: 'POST' }),

  purgeDocument: (id: number) => request<{ ok: boolean }>(`/documents/items/${id}/purge`, { method: 'DELETE' }),

  uploadDocumentVersion: async (id: number, file: File, note: string) => {
    const body = new FormData()
    body.append('file', file)
    body.append('note', note)
    const res = await fetch(`${API}/documents/items/${id}/versions`, { method: 'POST', credentials: 'include', body })
    if (!res.ok) throw new Error(await parseError(res))
    return res.json() as Promise<{ version_no: number }>
  },

  restoreDocumentVersion: (id: number, versionNo: number) =>
    request<{ version_no: number }>(`/documents/items/${id}/versions/${versionNo}/restore`, { method: 'POST' }),

  documentFile: async (id: number, version?: number) => {
    const qs = new URLSearchParams()
    if (version) qs.set('version', String(version))
    const res = await fetch(`${API}/documents/items/${id}/file?${qs}`, { credentials: 'include' })
    if (!res.ok) throw new Error(await parseError(res))
    return res.blob()
  },

  bulkDocuments: (
    ids: number[],
    action: 'move' | 'status' | 'delete' | 'restore',
    value: { folder_id?: number | null; status?: string } = {},
  ) => request<{ changed: number }>('/documents/bulk', { method: 'POST', body: JSON.stringify({ ids, action, ...value }) }),

  /** A place in the Document Center: the way back, its folders and its documents (its own, or everything inside it when searching). */
  documentBrowse: (
    node: string,
    params: { q?: string; category?: string; status?: string; expiry?: string; tag?: string; sort?: string; direction?: string; limit?: number; offset?: number; foldersOnly?: boolean } = {},
  ) => {
    const qs = new URLSearchParams({ node })
    for (const [key, value] of Object.entries(params)) {
      if (value === undefined || value === '' || value === false) continue
      qs.set(key === 'foldersOnly' ? 'folders_only' : key, String(value))
    }
    return request<ExplorerPage>(`/documents/browse?${qs}`)
  },

  // --- The SQL editor (administrators) ---------------------------------------------------------------------------------

  sqlStatus: () => request<SqlStatus>('/sql/status'),

  sqlCatalog: () => request<SqlCatalog>('/sql/catalog'),

  sqlObject: (schema: string, name: string) => request<SqlObjectDetail>(`/sql/objects/${encodeURIComponent(schema)}/${encodeURIComponent(name)}`),

  sqlRun: (body: { sql: string; write: boolean; rollback: boolean; limit: number; timeout: number; run_id: string; confirm?: boolean }) =>
    request<SqlRun>('/sql/run', { method: 'POST', body: JSON.stringify(body) }),

  sqlCancel: (runId: string) => request<{ cancelled: boolean }>('/sql/cancel', { method: 'POST', body: JSON.stringify({ run_id: runId }) }),

  sqlCheck: (sql: string, write: boolean) =>
    request<{ ok: boolean; message?: string; statements?: { kind: string; first: string; confirm: string[] }[] }>('/sql/check', {
      method: 'POST',
      body: JSON.stringify({ sql, write }),
    }),

  /** Every row (to a hundred thousand) of one SELECT, as a CSV file. */
  sqlExport: async (sql: string) => {
    const res = await fetch(`${API}/sql/export`, { method: 'POST', credentials: 'include', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ sql }) })
    if (!res.ok) throw new Error(await parseError(res))
    return res.blob()
  },

  sqlSaved: () => request<{ queries: SqlSavedQuery[] }>('/sql/saved'),

  sqlSave: (id: number | null, body: { title: string; sql: string; folder?: string | null; description?: string | null; shared: boolean }) =>
    request<{ id: number }>(id ? `/sql/saved/${id}` : '/sql/saved', { method: id ? 'PUT' : 'POST', body: JSON.stringify(body) }),

  sqlDeleteSaved: (id: number) => request<{ ok: boolean }>(`/sql/saved/${id}`, { method: 'DELETE' }),

  sqlHistory: (everyone: boolean, q: string) => request<{ runs: SqlHistoryRow[] }>(`/sql/history?everyone=${everyone}&q=${encodeURIComponent(q)}&limit=100`),

  // --- Google Drive (the Document Center) -------------------------------------------------------------------------

  driveStatus: () => request<DriveStatus>('/gdrive/status'),

  /** Connect. With Google's credentials this answers the address to send the admin to; the stand-in Drive connects at once. */
  driveConnect: () => request<{ connected: boolean; url?: string }>('/gdrive/connect', { method: 'POST' }),

  driveDisconnect: () => request<{ ok: boolean }>('/gdrive/disconnect', { method: 'POST' }),

  driveSettings: (billsMode: string, folderId: string | null) =>
    request<DriveStatus>('/gdrive/settings', { method: 'PUT', body: JSON.stringify({ bills_mode: billsMode, folder_id: folderId }) }),

  driveBrowse: (folder?: string, q?: string, pageToken?: string) => {
    const qs = new URLSearchParams()
    if (folder) qs.set('folder', folder)
    if (q) qs.set('q', q)
    if (pageToken) qs.set('page_token', pageToken)
    return request<DriveListing>(`/gdrive/browse?${qs}`)
  },

  driveNewFolder: (parentId: string, name: string) =>
    request<DriveListing['folders'][number]>('/gdrive/folders', { method: 'POST', body: JSON.stringify({ parent_id: parentId, name }) }),

  driveRename: (id: string, name: string) => request<unknown>(`/gdrive/files/${encodeURIComponent(id)}`, { method: 'PATCH', body: JSON.stringify({ name }) }),

  driveMove: (id: string, folderId: string) =>
    request<unknown>(`/gdrive/files/${encodeURIComponent(id)}`, { method: 'PATCH', body: JSON.stringify({ folder_id: folderId }) }),

  driveTrash: (id: string) => request<{ ok: boolean }>(`/gdrive/files/${encodeURIComponent(id)}`, { method: 'DELETE' }),

  driveUpload: async (parentId: string, file: File) => {
    const body = new FormData()
    body.set('parent_id', parentId)
    body.set('file', file)
    const res = await fetch(`${API}/gdrive/upload`, { method: 'POST', credentials: 'include', body })
    if (!res.ok) throw new Error(await parseError(res))
    return res.json()
  },

  /** A file from Drive, kept in memory to save: Google Docs come as PDF or Excel. */
  driveDownload: async (id: string) => {
    const res = await fetch(`${API}/gdrive/files/${encodeURIComponent(id)}/download`, { credentials: 'include' })
    if (!res.ok) throw new Error(await parseError(res))
    return res.blob()
  },

  driveCopyTo: (ids: number[], folderId: string, move: boolean, allowConfidential: boolean) =>
    request<DriveCopyResult>('/gdrive/copy-to-drive', { method: 'POST', body: JSON.stringify({ ids, folder_id: folderId, move, allow_confidential: allowConfidential }) }),

  driveCopyFrom: (fileIds: string[], to: string, move: boolean) =>
    request<DriveCopyResult>('/gdrive/copy-from-drive', { method: 'POST', body: JSON.stringify({ file_ids: fileIds, to, move }) }),

  driveLinks: (kind: 'bill' | 'document', ref: string) =>
    request<{ links: DriveLink[] }>(`/gdrive/links?kind=${kind}&ref=${encodeURIComponent(ref)}`),

  driveBillLink: (code: string) => request<{ link: DriveLink | null }>(`/gdrive/bills/${encodeURIComponent(code)}`),

  driveSaveBill: (code: string, folderId: string) =>
    request<{ link: DriveLink | null }>(`/gdrive/bills/${encodeURIComponent(code)}`, { method: 'PUT', body: JSON.stringify({ folder_id: folderId }) }),

  driveSyncBill: (code: string) => request<{ link: DriveLink | null }>(`/gdrive/bills/${encodeURIComponent(code)}/sync`, { method: 'POST' }),

  driveStopBill: (code: string) => request<{ link: DriveLink | null }>(`/gdrive/bills/${encodeURIComponent(code)}`, { method: 'DELETE' }),

  /** Move documents and folders to a folder (or the top of a case, client or the company). A filed paper is kept there by choice. */
  moveDocuments: (items: { ids: number[]; folder_ids: number[] }, to: string) =>
    request<MoveResult>('/documents/move', { method: 'POST', body: JSON.stringify({ ...items, to }) }),

  /** Where a paper Orion filed by itself is kept, for example a bill (`bill`, its code). */
  sourceLocations: (type: string, ref: string) =>
    request<SourceLocations>(`/documents/source/${encodeURIComponent(type)}/${encodeURIComponent(ref)}`),

  /** Keep that paper in the folder `to`, or (null) back where Orion files it by itself. */
  chooseSourceHome: (type: string, ref: string, to: string | null) =>
    request<SourceLocations>(`/documents/source/${encodeURIComponent(type)}/${encodeURIComponent(ref)}`, { method: 'PUT', body: JSON.stringify({ to }) }),

  /** Where a bill for this case and day will be filed, with the folder chosen or by itself. */
  billFilingPreview: (caseCode: string, billDate: string, to?: string | null) => {
    const qs = new URLSearchParams({ case_code: caseCode, bill_date: billDate })
    if (to) qs.set('to', to)
    return request<{ locations: { home: boolean; label: string }[] }>(`/documents/filing/preview?${qs}`)
  },

  documentFolders: (space: { scope: string; case_code?: string; client_code?: string }) => {
    const qs = new URLSearchParams({ scope: space.scope })
    if (space.case_code) qs.set('case_code', space.case_code)
    if (space.client_code) qs.set('client_code', space.client_code)
    return request<DocumentFolders>(`/documents/folders?${qs}`)
  },

  createDocumentFolder: (space: { scope: string; case_code?: string; client_code?: string }, name: string, parentId?: number | null) =>
    request<{ id: number; name: string }>('/documents/folders', {
      method: 'POST',
      body: JSON.stringify({ ...space, name, parent_id: parentId ?? null }),
    }),

  /** Get or create the folders of an uploaded folder (`a/b/c` paths) inside a place, and inside `parentId` if given. Returns each path's folder id. */
  createDocumentFolderTree: (space: { scope: string; case_code?: string; client_code?: string }, paths: string[], parentId?: number | null) =>
    request<{ folders: Record<string, number | null>; created: number; flattened: number }>('/documents/folders/tree', {
      method: 'POST',
      body: JSON.stringify({ ...space, paths, parent_id: parentId ?? null }),
    }),

  // --- Follow-ups of won opportunities ---------------------------------------------------------------------------

  followups: () => request<FollowupList>('/followups'),

  followupContext: (opportunityCode: string) => request<FollowupContext>(`/followups/opportunity/${encodeURIComponent(opportunityCode)}`),

  dismissFollowup: (id: number, note: string) =>
    request<{ ok: boolean }>(`/followups/${id}/dismiss`, { method: 'POST', body: JSON.stringify({ note: note.trim() || null }) }),

  reopenFollowup: (id: number) => request<{ ok: boolean }>(`/followups/${id}/reopen`, { method: 'POST' }),

  /** File anything not yet in the Document Center and bring the filed papers in step with their sources. */
  updateDocumentFiling: () => request<{ filed: number; updated: number; unchanged: number; retired: number; failed: number }>('/documents/filing/update', { method: 'POST' }),

  createStandardFolders: (space: { scope: string; case_code?: string; client_code?: string }) =>
    request<{ added: number }>('/documents/folders/standard', { method: 'POST', body: JSON.stringify(space) }),

  renameDocumentFolder: (id: number, name: string) =>
    request<{ ok: boolean }>(`/documents/folders/${id}`, { method: 'PATCH', body: JSON.stringify({ name }) }),

  deleteDocumentFolder: (id: number) => request<{ ok: boolean }>(`/documents/folders/${id}`, { method: 'DELETE' }),

  /** What deleting this folder with everything in it would take away, to be read before it is confirmed. */
  documentFolderContents: (id: number) => request<FolderContents>(`/documents/folders/${id}/contents`),

  /** Deletes a folder with everything in it. `seen_*` are the numbers the person was shown: if the folder has changed since, nothing is deleted. */
  dropDocumentFolder: (id: number, seen: { seen_documents: number; seen_subfolders: number }) =>
    request<{ documents: number; folders: number }>(`/documents/folders/${id}/drop`, { method: 'POST', body: JSON.stringify(seen) }),

  caseChecklist: (caseCode: string) =>
    request<{ checklist: { category: string; count: number; present: boolean }[] }>(
      `/documents/cases/${encodeURIComponent(caseCode)}/checklist`,
    ),

  entities: () => request<{ entities: EntityMeta[] }>('/entities'),

  entityPreview: (name: string, limit: number = 3, query: PreviewQuery = {}) =>
    request<PreviewPayload>(`/entities/${encodeURIComponent(name)}/preview?${previewQs(limit, query)}`),

  downloadEntityExport: (name: string, limit: number | 'all', query: PreviewQuery = {}) =>
    downloadFile(
      `/entities/${encodeURIComponent(name)}/export?${previewQs(limit, query)}`,
      `orion_${slug(name)}_${limit === 'all' ? 'all' : query.q || query.sort || query.f ? 'filtered' : `latest_${limit}`}.xlsx`,
    ),

  /** The values a column holds, with how many rows each is on, for the pick list in its header (the search and the other columns' filters apply). */
  entityValues: (name: string, column: string, query: PreviewQuery, contains: string) =>
    request<PickList>(`/entities/${encodeURIComponent(name)}/values?${valuesQs(column, query, contains)}`),

  dwValues: (name: string, column: string, query: PreviewQuery, contains: string) =>
    request<PickList>(`/dw/${encodeURIComponent(name)}/values?${valuesQs(column, query, contains)}`),

  tallyValues: (name: string, column: string, query: PreviewQuery, contains: string) =>
    request<PickList>(`/tally/${encodeURIComponent(name)}/values?${valuesQs(column, query, contains)}`),

  tallyDwValues: (name: string, column: string, query: PreviewQuery, contains: string) =>
    request<PickList>(`/tally-dw/${encodeURIComponent(name)}/values?${valuesQs(column, query, contains)}`),

  entityOptions: (name: string) =>
    request<{ id: string; label: string }[]>(`/entities/${encodeURIComponent(name)}/options`),

  fieldOptions: (entity: string, field: string) =>
    request<{ id: string; label: string }[]>(
      `/entities/${encodeURIComponent(entity)}/field-options/${encodeURIComponent(field)}`,
    ),

  getRecord: (entity: string, id: string) =>
    request<Record<string, unknown>>(`/entities/${encodeURIComponent(entity)}/records/${encodeURIComponent(id)}`),

  /** What is already recorded that a record about to be added looks like (an expense: same type, case and amount within a week). Nothing is saved. */
  duplicateCheck: (entity: string, data: Record<string, unknown>) =>
    request<{ matches: { expense_code: string; note: string }[] }>(`/entities/${encodeURIComponent(entity)}/duplicate-check`, {
      method: 'POST',
      body: JSON.stringify({ data }),
    }),

  /** `key` (see `newIdempotencyKey`) makes a record that is also paid (an expense with Paid On) save and pay once, however often it is sent. */
  createRecord: (entity: string, data: Record<string, unknown>, key?: string) =>
    request<{ ok: boolean; id?: string }>(`/entities/${encodeURIComponent(entity)}/records`, {
      method: 'POST',
      body: JSON.stringify({ data }),
      headers: idempotencyHeader(key),
    }),

  /** `expectedUpdated` is the record's last_updated_timestamp as it was opened; if it has been saved since, the server refuses. */
  updateRecord: (entity: string, id: string, data: Record<string, unknown>, expectedUpdated?: string) =>
    request(`/entities/${encodeURIComponent(entity)}/records/${encodeURIComponent(id)}`, {
      method: 'PUT',
      body: JSON.stringify({ data, expected_updated: expectedUpdated ?? null }),
    }),

  deleteRecord: (entity: string, id: string) =>
    request(`/entities/${encodeURIComponent(entity)}/records/${encodeURIComponent(id)}`, {
      method: 'DELETE',
    }),

  downloadExcelTemplate: (entity: string) =>
    downloadFile(
      `/entities/${encodeURIComponent(entity)}/excel-template`,
      `orion_${slug(entity)}_template.xlsx`,
    ),

  uploadExcel: async (entity: string, file: File) => {
    const body = new FormData()
    body.append('file', file)
    const res = await fetch(`${API}/entities/${encodeURIComponent(entity)}/excel`, {
      method: 'POST',
      credentials: 'include',
      body,
    })
    if (!res.ok) throw new Error(await parseError(res))
    return res.json() as Promise<ExcelUploadResult>
  },

  states: () => request<{ states: string[] }>('/location/states'),

  cities: (state: string) =>
    request<{ cities: string[] }>(`/location/cities?state=${encodeURIComponent(state)}`),

  dwTables: () =>
    request<{ tables: { name: string; kind: 'dimension' | 'fact'; rows: number; current: number }[] }>(
      '/dw/tables',
    ),

  dwDimensions: () => request<{ dimensions: string[] }>('/dw/dimensions'),

  dwPreview: (dimension: string, limit: number = 3, query: PreviewQuery = {}) =>
    request<PreviewPayload>(`/dw/${encodeURIComponent(dimension)}/preview?${previewQs(limit, query)}`),

  downloadDwExport: (dimension: string, limit: number | 'all', query: PreviewQuery = {}) =>
    downloadFile(
      `/dw/${encodeURIComponent(dimension)}/export?${previewQs(limit, query)}`,
      `orion_${slug(dimension)}_${limit === 'all' ? 'all' : query.q || query.sort || query.f ? 'filtered' : `latest_${limit}`}.xlsx`,
    ),

  /** When the warehouse was last loaded. `source` picks the route the signed-in user is allowed to use. */
  warehouseStatus: (source: 'dashboard' | 'dw') =>
    request<WarehouseStatus>(source === 'dashboard' ? '/dashboard/warehouse-status' : '/dw/status'),

  recordHistory: (entity: string, id: string) =>
    request<RecordHistory>(`/entities/${encodeURIComponent(entity)}/records/${encodeURIComponent(id)}/history`),

  tallyStatus: () =>
    request<{
      running: boolean
      host?: string
      port?: number
      company?: string | null
      error?: string | null
      warning?: string | null
      companies_loaded?: string[]
      companies_not_open?: string[]
      companies_on_disk?: {
        name: string
        starting_from?: string | null
        ending_at?: string | null
        company_number?: string | null
        open: boolean
      }[]
    }>('/tally/status'),

  tallyTables: () =>
    request<{ tables: { name: string; kind: 'master' | 'transaction'; rows: number }[] }>('/tally/tables'),

  tallyPreview: (name: string, limit: number = 3, query: PreviewQuery = {}) =>
    request<PreviewPayload>(`/tally/${encodeURIComponent(name)}/preview?${previewQs(limit, query)}`),

  downloadTallyExport: (name: string, limit: number | 'all', query: PreviewQuery = {}) =>
    downloadFile(
      `/tally/${encodeURIComponent(name)}/export?${previewQs(limit, query)}`,
      `orion_tally_${slug(name)}_${limit === 'all' ? 'all' : query.q || query.sort || query.f ? 'filtered' : `latest_${limit}`}.xlsx`,
    ),

  tallyDwTables: () =>
    request<{ tables: { name: string; kind: 'dimension' | 'fact'; rows: number; current: number }[] }>(
      '/tally-dw/tables',
    ),

  tallyDwPreview: (name: string, limit: number = 3, query: PreviewQuery = {}) =>
    request<PreviewPayload>(`/tally-dw/${encodeURIComponent(name)}/preview?${previewQs(limit, query)}`),

  downloadTallyDwExport: (name: string, limit: number | 'all', query: PreviewQuery = {}) =>
    downloadFile(
      `/tally-dw/${encodeURIComponent(name)}/export?${previewQs(limit, query)}`,
      `orion_tally_dw_${slug(name)}_${limit === 'all' ? 'all' : query.q || query.sort || query.f ? 'filtered' : `latest_${limit}`}.xlsx`,
    ),

  etlPipelines: () => request<{ pipelines: EtlPipeline[] }>('/etl/pipelines'),

  etlRuns: (filters: { pipeline?: string; status?: string; trigger?: string; limit?: number; offset?: number } = {}) => {
    const params = new URLSearchParams()
    Object.entries(filters).forEach(([key, value]) => {
      if (value !== undefined && value !== '') params.set(key, String(value))
    })
    const query = params.toString()
    return request<{ runs: EtlRun[]; total: number }>(`/etl/runs${query ? `?${query}` : ''}`)
  },

  etlRun: (id: number) => request<EtlRunDetail>(`/etl/runs/${id}`),

  /** Starts a pipeline (or one table of it) in the background and returns the run to follow. */
  startEtl: (pipeline: string, table?: string) =>
    request<{ run_id: number }>(`/etl/pipelines/${encodeURIComponent(pipeline)}/run`, {
      method: 'POST',
      body: JSON.stringify({ table: table ?? null }),
    }),

  /** Admin only: when the database was last backed up, and whether backups are healthy. */
  backupStatus: () => request<BackupStatus>('/backup/status'),

  /** Admin only: starts a backup in the background; follow it through backupStatus. */
  runBackup: () => request<{ started: boolean }>('/backup/run', { method: 'POST' }),

  users: () => request<AppUser[]>('/users'),

  usersMeta: () =>
    request<{
      roles: { id: string; label: string }[]
      default_data_access: Record<string, AccessFlags>
    }>('/users/meta'),

  createUser: (body: Record<string, unknown>) =>
    request('/users', { method: 'POST', body: JSON.stringify(body) }),

  updateUserRole: (id: number, role: string) =>
    request(`/users/${id}/role`, { method: 'PATCH', body: JSON.stringify({ role }) }),

  updateUserActive: (id: number, is_active: boolean) =>
    request(`/users/${id}/active`, { method: 'PATCH', body: JSON.stringify({ is_active }) }),

  updateUserDataAccess: (
    id: number,
    access: AccessFlags,
  ) =>
    request(`/users/${id}/data-access`, {
      method: 'PATCH',
      body: JSON.stringify(access),
    }),

  updateUserPassword: (id: number, password: string) =>
    request(`/users/${id}/password`, { method: 'PATCH', body: JSON.stringify({ password }) }),

  sendUserPasswordReset: (id: number) =>
    request<{ ok: boolean; email: string }>(`/users/${id}/password-reset`, { method: 'POST' }),

  updateUserContact: (id: number, body: { email?: string; phone?: string }) =>
    request(`/users/${id}/contact`, { method: 'PATCH', body: JSON.stringify(body) }),

  deleteUser: (id: number) => request(`/users/${id}`, { method: 'DELETE' }),

  signups: () =>
    request<{ pending: SignupRequest[]; reviewed: SignupRequest[] }>('/users/signups'),

  approveSignup: (
    id: number,
    body: { role: string } & AccessFlags,
  ) => request<{ ok: boolean; email: string; user_id: number }>(`/users/signups/${id}/approve`, {
    method: 'POST',
    body: JSON.stringify(body),
  }),

  rejectSignup: (id: number, reason?: string) =>
    request(`/users/signups/${id}/reject`, {
      method: 'POST',
      body: JSON.stringify({ reason: reason || null }),
    }),

  chatDirectory: () => request<ChatPeer[]>('/messages/directory'),

  chats: () => request<ChatThread[]>('/messages/chats'),

  chatUnread: () => request<{ count: number }>('/messages/unread'),

  createGroup: (title: string, userIds: number[]) =>
    request<ChatThread>('/messages/groups', { method: 'POST', body: JSON.stringify({ title, user_ids: userIds }) }),

  renameGroup: (chatId: number, title: string) => request<ChatThread>(`/messages/groups/${chatId}`, { method: 'PATCH', body: JSON.stringify({ title }) }),

  addGroupMembers: (chatId: number, userIds: number[]) =>
    request<ChatThread>(`/messages/groups/${chatId}/members`, { method: 'POST', body: JSON.stringify({ user_ids: userIds }) }),

  /** An admin removes someone, or a person leaves (their own id). */
  removeGroupMember: (chatId: number, userId: number) =>
    request<{ ok: boolean; deleted: boolean }>(`/messages/groups/${chatId}/members/${userId}`, { method: 'DELETE' }),

  setGroupRole: (chatId: number, userId: number, role: 'admin' | 'member') =>
    request<ChatThread>(`/messages/groups/${chatId}/members/${userId}/role`, { method: 'PUT', body: JSON.stringify({ role }) }),

  /** The servers the browser uses to reach the other person on a call (none on one network or over Tailscale). */
  callConfig: () => request<{ ice_servers: RTCIceServer[] }>('/messages/calls/config'),

  /** The call ringing for this person right now, if a page has just loaded and missed the ring. */
  callRinging: () => request<{ call: CallRing | null }>('/messages/calls/ringing'),

  startChat: (userId: number) =>
    request<ChatThread>('/messages/chats', { method: 'POST', body: JSON.stringify({ user_id: userId }) }),

  chatThread: (chatId: number) => request<ChatThreadDetail>(`/messages/chats/${chatId}`),

  /** Older messages (`before`), the ones missed while offline (`after`), or the stretch around one message (`around`). */
  chatPage: (chatId: number, options: { before?: number; after?: number; around?: number; limit?: number } = {}) => {
    const query = new URLSearchParams()
    for (const [key, value] of Object.entries(options)) if (value) query.set(key, String(value))
    return request<ChatPage>(`/messages/chats/${chatId}/messages${query.size ? `?${query}` : ''}`)
  },

  /**
   * Sends a message. With a file it uses XHR so the upload's progress can be shown; `clientId` makes a retry of the same send
   * the same message on the server, so a dropped connection never leaves a duplicate.
   */
  sendChat: (
    chatId: number,
    body: string,
    file?: File | null,
    options: {
      replyTo?: number | null
      clientId?: string
      onProgress?: (fraction: number) => void
      /** A voice note's length and loudness picture, sent with the recording. */
      voice?: { durationMs: number; waveform: number[] }
    } = {},
  ) => {
    const url = `${API}/messages/chats/${chatId}/messages`
    if (!file) {
      return request<ChatMessage>(`/messages/chats/${chatId}/messages`, {
        method: 'POST',
        body: JSON.stringify({ body, reply_to: options.replyTo || undefined, client_id: options.clientId }),
      })
    }
    return new Promise<ChatMessage>((resolve, reject) => {
      const data = new FormData()
      data.append('body', body)
      data.append('file', file)
      if (options.replyTo) data.append('reply_to', String(options.replyTo))
      if (options.clientId) data.append('client_id', options.clientId)
      if (options.voice) {
        data.append('duration_ms', String(Math.round(options.voice.durationMs)))
        data.append('waveform', options.voice.waveform.join(','))
      }
      const xhr = new XMLHttpRequest()
      xhr.open('POST', url)
      xhr.withCredentials = true
      xhr.upload.onprogress = (event) => {
        if (event.lengthComputable) options.onProgress?.(event.loaded / event.total)
      }
      xhr.onload = () => {
        let parsed: unknown = null
        try {
          parsed = JSON.parse(xhr.responseText)
        } catch {
          /* not JSON */
        }
        if (xhr.status >= 200 && xhr.status < 300) {
          resolve(parsed as ChatMessage)
          return
        }
        const detail = (parsed as { detail?: unknown } | null)?.detail
        reject(new Error(typeof detail === 'string' ? detail : xhr.statusText || 'Could not send'))
      }
      xhr.onerror = () => reject(new Error('Could not reach the server. Check your connection.'))
      xhr.onabort = () => reject(new Error('Cancelled'))
      xhr.send(data)
    })
  },

  editChatMessage: (messageId: number, body: string) =>
    request<ChatMessage>(`/messages/${messageId}`, { method: 'PATCH', body: JSON.stringify({ body }) }),

  deleteChatMessage: (messageId: number) => request<ChatMessage>(`/messages/${messageId}`, { method: 'DELETE' }),

  reactToChatMessage: (messageId: number, emoji: string) =>
    request<{ chat_id: number; message_id: number; reactions: ChatReaction[] }>(`/messages/${messageId}/reactions`, {
      method: 'PUT',
      body: JSON.stringify({ emoji }),
    }),

  forwardChatMessage: (messageId: number, target: { chat_id?: number; user_id?: number }) =>
    request<ChatMessage>(`/messages/${messageId}/forward`, { method: 'POST', body: JSON.stringify(target) }),

  pinChatMessage: (chatId: number, messageId: number, pinned: boolean) =>
    request<{ pins: ChatMessage[] }>(`/messages/chats/${chatId}/pins/${messageId}`, { method: pinned ? 'PUT' : 'DELETE' }),

  chatSettings: (chatId: number, changes: Partial<ChatSettings>) =>
    request<ChatSettings>(`/messages/chats/${chatId}/settings`, { method: 'PATCH', body: JSON.stringify(changes) }),

  searchChats: (q: string, chatId?: number | null) =>
    request<{ results: ChatSearchHit[] }>(`/messages/search?q=${encodeURIComponent(q)}${chatId ? `&chat_id=${chatId}` : ''}`),

  chatMedia: (chatId: number, kind?: ChatMediaKind) =>
    request<{ items: ChatSharedItem[] }>(`/messages/chats/${chatId}/media${kind ? `?kind=${kind}` : ''}`),

  chatAssist: (chatId: number, body: { action: ChatAssistAction; text?: string; tone?: string; language?: string; allow_cloud_once?: boolean }) =>
    request<ChatAssistResult>(`/messages/chats/${chatId}/assist`, { method: 'POST', body: JSON.stringify(body) }),

  readChat: (chatId: number) =>
    request<{ count: number }>(`/messages/chats/${chatId}/read`, { method: 'POST' }),

  deleteChat: (chatId: number) =>
    request<{ ok: boolean }>(`/messages/chats/${chatId}`, { method: 'DELETE' }),

  // ---- AI help inside screens (each answer is a draft; nothing is saved or sent by it) ----

  letterAi: (body: {
    mode: 'draft' | 'improve'
    brief?: string
    text?: string
    action?: 'tone' | 'shorter' | 'longer' | 'grammar' | 'translate'
    tone?: string
    language?: string
    allow_cloud_once?: boolean
  }) => request<AiOutcome<{ html: string; text: string }>>('/letterhead/ai', { method: 'POST', body: JSON.stringify(body) }),

  reminderAi: (clientCode: string, body: { tone: string; allow_cloud_once?: boolean }) =>
    request<AiOutcome<{ message: string }>>(`/billing/receivables/${encodeURIComponent(clientCode)}/reminder/ai`, {
      method: 'POST',
      body: JSON.stringify(body),
    }),

  documentSuggestAi: async (file: File, scope: string, allowCloudOnce: boolean) => {
    const data = new FormData()
    data.append('file', file)
    data.append('scope', scope)
    data.append('allow_cloud_once', String(allowCloudOnce))
    const res = await fetch(`${API}/documents/ai/suggest`, { method: 'POST', credentials: 'include', body: data })
    if (!res.ok) throw new Error(await parseError(res))
    return res.json() as Promise<
      AiOutcome<{
        suggestion: { title: string; category: string; document_date: string; expiry_date: string; tags: string[]; description: string }
        read_text: boolean
      }>
    >
  },

  entityFillAi: (entity: string, text: string, allowCloudOnce: boolean) =>
    request<AiOutcome<{ values: Record<string, unknown>; labels: Record<string, string> }>>(
      `/entities/${encodeURIComponent(entity)}/ai/fill`,
      { method: 'POST', body: JSON.stringify({ text, allow_cloud_once: allowCloudOnce }) },
    ),

  etlExplainAi: (runId: number, allowCloudOnce: boolean) =>
    request<AiOutcome<{ text: string }>>(`/etl/runs/${runId}/explain`, {
      method: 'POST',
      body: JSON.stringify({ allow_cloud_once: allowCloudOnce }),
    }),

  raiseRequest: async (body: { subject: string; details: string; files: File[] }) => {
    const data = new FormData()
    data.append('subject', body.subject)
    data.append('details', body.details)
    for (const file of body.files) {
      data.append('files', file)
    }
    const res = await fetch(`${API}/support/requests`, {
      method: 'POST',
      credentials: 'include',
      body: data,
    })
    if (!res.ok) throw new Error(await parseError(res))
    return res.json() as Promise<{ ok: boolean }>
  },
}

/** A blank line ends one server-sent event. */
const SSE_BREAK = '\n\n'

/** The Copilot. Questions stream back as server-sent events; everything else is plain JSON. */
export const aiApi = {
  status: () => request<AiStatus>('/ai/status'),

  saveSettings: (body: Partial<AiSettings>) =>
    request<AiSettings>('/ai/settings', { method: 'PUT', body: JSON.stringify(body) }),

  clearHistory: () => request<{ deleted: number }>('/ai/history', { method: 'DELETE' }),

  health: () => request<AiHealth>('/ai/health'),

  setPolicy: (cloud_mode: AiCloudPolicy) =>
    request<{ cloud_mode: AiCloudPolicy }>('/ai/policy', { method: 'PUT', body: JSON.stringify({ cloud_mode }) }),

  explainRoute: (message: string, context?: AiPageContext) =>
    request<AiRouteExplanation>('/ai/route/explain', { method: 'POST', body: JSON.stringify({ message, context }) }),

  conversations: (q = '', category: AiCategory | '' = '') => {
    const params = new URLSearchParams()
    if (q) params.set('q', q)
    if (category) params.set('category', category)
    return request<{ conversations: AiConversation[] }>(`/ai/conversations?${params.toString()}`)
  },

  conversation: (id: number) =>
    request<{ conversation: AiConversation; messages: AiMessage[] }>(`/ai/conversations/${id}`),

  renameConversation: (id: number, body: { title?: string; category?: AiCategory }) =>
    request<{ ok: boolean }>(`/ai/conversations/${id}`, { method: 'PATCH', body: JSON.stringify(body) }),

  deleteConversation: (id: number) => request<{ ok: boolean }>(`/ai/conversations/${id}`, { method: 'DELETE' }),

  confirmAction: (id: string) =>
    request<{ ok: boolean; summary: string }>(`/ai/actions/${id}/confirm`, { method: 'POST' }),

  cancelAction: (id: string) => request<{ ok: boolean }>(`/ai/actions/${id}/cancel`, { method: 'POST' }),

  insights: (fresh = false) => request<{ insights: AiInsight[] }>(`/ai/insights${fresh ? '?fresh=true' : ''}`),

  dismissInsight: (id: string, days = 7) =>
    request<{ ok: boolean }>(`/ai/insights/${encodeURIComponent(id)}/dismiss`, { method: 'POST', body: JSON.stringify({ days }) }),

  suggestions: (context: AiPageContext) => {
    const params = new URLSearchParams()
    if (context.path) params.set('path', context.path)
    if (context.area) params.set('area', context.area)
    if (context.view) params.set('view', context.view)
    return request<{ suggestions: string[] }>(`/ai/suggestions?${params.toString()}`)
  },

  tasks: (state: 'open' | 'done' | 'dismissed' | 'all' = 'open') => request<{ tasks: AiTask[] }>(`/ai/tasks?state=${state}`),

  updateTask: (id: number, status: 'open' | 'done' | 'dismissed') =>
    request<{ ok: boolean }>(`/ai/tasks/${id}`, { method: 'PATCH', body: JSON.stringify({ status }) }),

  audit: (mine = false) => request<{ audit: AiAuditRow[] }>(`/ai/audit?limit=200${mine ? '&mine=true' : ''}`),

  fileUrl: (path: string) => path,

  /**
   * Asks a question and calls `onEvent` for each event as it arrives. Resolves when the answer is complete, was stopped
   * (the signal aborted) or failed; failures to connect are reported as an `error` event rather than thrown, so the
   * caller has one place to handle them.
   */
  chat: async (
    body: {
      message: string
      conversation_id?: number | null
      context?: AiPageContext
      regenerate?: boolean
      /** The person chose cloud AI for this one question. The organisation's policy still decides. */
      cloud_once?: boolean
      history?: { role: 'user' | 'assistant'; text: string }[]
    },
    onEvent: (event: AiEvent) => void,
    signal: AbortSignal,
  ): Promise<void> => {
    const failure = (message: string, retryable = true) =>
      onEvent({ type: 'error', code: 'failed', message, retryable })
    let res: Response
    try {
      res = await fetch(`${API}/ai/chat`, {
        method: 'POST',
        credentials: 'include',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
        signal,
      })
    } catch (err) {
      if ((err as Error).name === 'AbortError') return
      failure('I could not reach the server. Check your connection and try again.')
      return
    }
    if (!res.ok || !res.body) {
      failure(res.status === 403 ? 'The Copilot is not turned on for your account.' : await parseError(res), res.status >= 500)
      return
    }
    const reader = res.body.getReader()
    const decoder = new TextDecoder()
    let buffer = ''
    try {
      for (;;) {
        const { done, value } = await reader.read()
        if (done) break
        buffer += decoder.decode(value, { stream: true })
        let cut = buffer.indexOf(SSE_BREAK)
        while (cut !== -1) {
          const line = buffer.slice(0, cut).trim()
          buffer = buffer.slice(cut + 2)
          if (line.startsWith('data:')) {
            try {
              onEvent(JSON.parse(line.slice(5)) as AiEvent)
            } catch {
              /* a malformed event is skipped; the next one carries on */
            }
          }
          cut = buffer.indexOf(SSE_BREAK)
        }
      }
    } catch (err) {
      if ((err as Error).name === 'AbortError') return
      failure('The connection was interrupted. Please try again.')
    }
  },
}

function queryString(params: Record<string, string | number | boolean | undefined | null>): string {
  const qs = new URLSearchParams()
  for (const [key, value] of Object.entries(params)) {
    if (value !== undefined && value !== null && value !== '') qs.set(key, String(value))
  }
  const text = qs.toString()
  return text ? `?${text}` : ''
}

/** A statement file with the column choices the person made, if any. */
function statementForm(file: File, mapping?: Record<string, number>, headerRow?: number, accountId?: number): FormData {
  const body = new FormData()
  body.append('file', file)
  if (accountId !== undefined) body.append('account_id', String(accountId))
  if (mapping && Object.keys(mapping).length) body.append('mapping', JSON.stringify(mapping))
  if (headerRow !== undefined) body.append('header_row', String(headerRow))
  return body
}

async function upload<T>(path: string, body: FormData): Promise<T> {
  const res = await fetch(`${API}${path}`, { method: 'POST', credentials: 'include', body })
  if (res.status === 401) window.dispatchEvent(new Event(SESSION_ENDED_EVENT))
  if (!res.ok) throw new ApiError(await parseError(res), res.status)
  return res.json() as Promise<T>
}

/** The forecast tab of a dashboard: every month ahead for each figure, with its range, for the whole business or one slice of it. */
export const forecastApi = {
  get: (source: 'orion' | 'tally', filters: Record<string, string>) =>
    request<ForecastPayload>(`${source === 'orion' ? '/dashboard' : '/tally-dashboard'}/forecast${queryString(filters)}`),
}

/** Salary pay runs: a month's salary lines paid by one transfer. Marking salary paid takes an idempotency key (see `newIdempotencyKey`). */
/** A client's page: the directory, and one client with its cases, people and (for billing) its money. Read only. */
export const clientsApi = {
  list: (search = '') => request<{ clients: ClientDirectoryRow[] }>(`/clients${search ? `?search=${encodeURIComponent(search)}` : ''}`),

  get: (code: string) => request<ClientProfile>(`/clients/${encodeURIComponent(code)}`),
}

/** A case's page and the case directory. Read only. */
export const casesApi = {
  list: (search = '') => request<{ cases: CaseDirectoryRow[] }>(`/cases${search ? `?search=${encodeURIComponent(search)}` : ''}`),

  get: (code: string) => request<CaseProfile>(`/cases/${encodeURIComponent(code)}`),
}

/** An employee's page and the employee directory. Read only; nothing private is in either. */
export const employeesApi = {
  list: (search = '') => request<{ employees: EmployeeDirectoryRow[] }>(`/employees${search ? `?search=${encodeURIComponent(search)}` : ''}`),

  get: (code: string) => request<EmployeeProfile>(`/employees/${encodeURIComponent(code)}`),

  /** An account's page (administrators only). */
  account: (id: number) => request<UserOverview>(`/users/${id}/overview`),
}

export const payrollApi = {
  months: () => request<{ months: PayrollMonth[] }>('/payroll/months'),

  unpaid: (month: string) => request<PayrollUnpaid>(`/payroll/months/${encodeURIComponent(month)}/unpaid`),

  runs: (query: { month_year?: string; limit?: number } = {}) => request<{ runs: PayrollRun[] }>(`/payroll/runs${queryString(query)}`),

  record: (input: PayrollRunInput, key?: string) =>
    request<{ run_id: number; lines: number; total: string }>('/payroll/runs', { method: 'POST', body: JSON.stringify(input), headers: idempotencyHeader(key) }),

  reverse: (runId: number, reason: string) =>
    request<{ run_id: number; lines: number }>(`/payroll/runs/${runId}/reverse`, { method: 'POST', body: JSON.stringify({ reason, confirm: true }) }),
}

/** What is owed on expenses, and the payments that settle them. Recording a payment takes an idempotency key (see `newIdempotencyKey`). */
export const payablesApi = {
  list: (query: { status?: 'open' | 'paid'; bucket?: PayableBucket; q?: string; case_code?: string; page?: number; limit?: number }) =>
    request<PayablesList>(`/payables${queryString(query)}`),

  get: (code: string) => request<PayableDetail>(`/payables/${encodeURIComponent(code)}`),

  pay: (code: string, input: ExpensePaymentInput, key?: string) =>
    request<{ payment_id: number; paid: string; left: string; payment_status: string }>(`/payables/${encodeURIComponent(code)}/payments`, {
      method: 'POST',
      body: JSON.stringify(input),
      headers: idempotencyHeader(key),
    }),

  reverse: (paymentId: number, reason: string) =>
    request<{ payment_id: number }>(`/payables/payments/${paymentId}/reverse`, { method: 'POST', body: JSON.stringify({ reason, confirm: true }) }),
}

/** The bank: the balance, its book, statements and reconciliation. Money-recording calls take an idempotency key (see `newIdempotencyKey`). */
export const bankApi = {
  meta: () => request<BankMeta>('/bank/meta'),

  account: (accountId?: number) => request<BankAccount>(`/bank/account${queryString({ account_id: accountId })}`),

  accounts: () => request<BankAccounts>('/bank/accounts'),

  createAccount: (input: BankAccountInput) => request<BankAccount>('/bank/accounts', { method: 'POST', body: JSON.stringify(input) }),

  previewAccount: (openingBalance: string, openingDate: string, accountId?: number) =>
    request<BankAccountPreview>(`/bank/account/preview${queryString({ opening_balance: openingBalance, opening_date: openingDate, account_id: accountId })}`),

  saveAccount: (input: BankAccountInput) => request<BankAccount>('/bank/account', { method: 'PUT', body: JSON.stringify(input) }),

  summary: (accountId?: number) => request<BankSummary>(`/bank/summary${queryString({ account_id: accountId })}`),

  series: (months = 12, accountId?: number) => request<BankSeries>(`/bank/series${queryString({ months, account_id: accountId })}`),

  alerts: () => request<{ alerts: BankAlert[] }>('/bank/alerts'),

  forecast: (includeOverdue = false) => request<BankForecast>(`/bank/forecast${queryString({ include_overdue: includeOverdue })}`),

  ledger: (query: BankLedgerQuery) => request<BankLedger>(`/bank/ledger${queryString({ ...query })}`),

  /** Where the ledger (with these filters) downloads as a CSV. */
  ledgerCsvUrl: (query: BankLedgerQuery) => `${API}/bank/ledger.csv${queryString({ ...query, page: undefined, limit: undefined })}`,

  createEntry: (input: BankEntryInput, key?: string) =>
    request<BankEntry>('/bank/entries', { method: 'POST', body: JSON.stringify(input), headers: idempotencyHeader(key) }),

  voidEntry: (id: number, reason: string) =>
    request<BankEntry>(`/bank/entries/${id}/void`, { method: 'POST', body: JSON.stringify({ reason }) }),

  activity: (limit = 50) => request<{ activity: BankActivityRow[] }>(`/bank/activity${queryString({ limit })}`),

  reconciliation: (accountId?: number) => request<BankReconciliation>(`/bank/reconciliation${queryString({ account_id: accountId })}`),

  statements: (accountId?: number) => request<{ imports: BankImportRow[] }>(`/bank/statements${queryString({ account_id: accountId })}`),

  previewStatement: (file: File, mapping?: Record<string, number>, headerRow?: number, accountId?: number) =>
    upload<BankStatementPreview>('/bank/statements/preview', statementForm(file, mapping, headerRow, accountId)),

  importStatement: (file: File, mapping?: Record<string, number>, headerRow?: number, accountId?: number) =>
    upload<BankImportResult>('/bank/statements', statementForm(file, mapping, headerRow, accountId)),

  removeStatement: (id: number) => request<void>(`/bank/statements/${id}`, { method: 'DELETE' }),

  exceptions: (accountId?: number) => request<{ exceptions: BankException[] }>(`/bank/exceptions${queryString({ account_id: accountId })}`),

  clearException: (lineId: number) => request<{ line_id: number; rematched: number }>(`/bank/exceptions/${lineId}/clear`, { method: 'POST' }),

  lines: (query: { status?: string; q?: string; date_from?: string; date_to?: string; account_id?: number; page?: number; limit?: number }) =>
    request<BankLines>(`/bank/lines${queryString(query)}`),

  suggestions: (lineId: number) => request<BankSuggestions>(`/bank/lines/${lineId}/suggestions`),

  matchLine: (lineId: number, movements: { source: string; source_ref: string }[]) =>
    request<{ line_id: number; matched: number }>(`/bank/lines/${lineId}/match`, { method: 'POST', body: JSON.stringify({ movements }) }),

  unmatchLine: (lineId: number) => request<{ line_id: number }>(`/bank/lines/${lineId}/unmatch`, { method: 'POST' }),

  ignoreLine: (lineId: number, reason: string) =>
    request<{ line_id: number }>(`/bank/lines/${lineId}/ignore`, { method: 'POST', body: JSON.stringify({ reason }) }),

  unignoreLine: (lineId: number) => request<{ line_id: number }>(`/bank/lines/${lineId}/unignore`, { method: 'POST' }),

  entryFromLine: (lineId: number, input: { category: string; counterparty?: string; description?: string; reference?: string }, key?: string) =>
    request<BankEntry>(`/bank/lines/${lineId}/entry`, { method: 'POST', body: JSON.stringify(input), headers: idempotencyHeader(key) }),

  autoMatch: (accountId?: number) => request<{ matched: number }>(`/bank/match/auto${queryString({ account_id: accountId })}`, { method: 'POST' }),

  /** Asks the AI to name the lines Orion's rules could not. Suggestions only. */
  categorise: (allowCloudOnce: boolean) =>
    request<AiOutcome<BankAiSuggestions>>('/bank/lines/categorise', { method: 'POST', body: JSON.stringify({ allow_cloud_once: allowCloudOnce }) }),
}

export const tendersApi = {
  status: (portal: TenderSource) => request<TenderStatus>(`/tenders/status${queryString({ portal })}`),

  searches: (portal: TenderSource) => request<TenderSearch[]>(`/tenders/searches${queryString({ portal })}`),

  createSearch: (input: TenderSearchInput) => request<TenderSearch>('/tenders/searches', { method: 'POST', body: JSON.stringify(input) }),

  saveSearch: (searchId: number, input: TenderSearchInput) =>
    request<TenderSearch>(`/tenders/searches/${searchId}`, { method: 'PUT', body: JSON.stringify(input) }),

  deleteSearch: (searchId: number) => request<{ ok: boolean }>(`/tenders/searches/${searchId}`, { method: 'DELETE' }),

  bids: (searchId: number, status: TenderMatchStatus | 'all', includeClosed = false) =>
    request<TenderBid[]>(`/tenders/searches/${searchId}/bids${queryString({ status, include_closed: includeClosed })}`),

  setStatus: (searchId: number, bidId: number, status: TenderMatchStatus) =>
    request<{ status: TenderMatchStatus }>(`/tenders/searches/${searchId}/bids/${bidId}/status`, { method: 'PUT', body: JSON.stringify({ status }) }),

  /** Checks GeM now, in the background; status() says when it has finished. */
  check: (portal: TenderSource) => request<{ started: boolean }>(`/tenders/check${queryString({ portal })}`, { method: 'POST' }),
}

/** Attendance: who worked at a case in a month, and the pay that follows. Posting takes an idempotency key (see `newIdempotencyKey`). */
export const attendanceApi = {
  cases: (q = '') => request<{ cases: AttendanceCase[] }>(`/attendance/cases?q=${encodeURIComponent(q)}`),

  expenseTypes: () => request<{ expense_types: { code: string; name: string }[] }>('/attendance/expense-types'),

  roster: (caseCode: string, month: string) => request<AttendanceRoster>(`/attendance/roster${queryString({ case_code: caseCode, month })}`),

  people: (q: string, month?: string) =>
    request<{ employees: AttendanceRosterPerson[]; workers: AttendanceRosterPerson[] }>(`/attendance/people${queryString({ q, month })}`),

  sheets: (query: { case_code?: string; month?: string; status?: string; q?: string } = {}) =>
    request<{ sheets: AttendanceSheetSummary[] }>(`/attendance/sheets${queryString(query)}`),

  sheet: (code: string) => request<AttendanceSheet>(`/attendance/sheets/${encodeURIComponent(code)}`),

  create: (body: Record<string, unknown>) => request<{ sheet_code: string; lines: number }>('/attendance/sheets', { method: 'POST', body: JSON.stringify(body) }),

  save: (code: string, body: Record<string, unknown>) =>
    request<{ sheet_code: string; lines: number }>(`/attendance/sheets/${encodeURIComponent(code)}`, { method: 'PUT', body: JSON.stringify(body) }),

  remove: (code: string) => request<{ ok: boolean }>(`/attendance/sheets/${encodeURIComponent(code)}`, { method: 'DELETE' }),

  post: (code: string, input: { seen_count: number; seen_total: string }, key?: string) =>
    request<{ sheet_code: string; salary_lines: number; expenses: number; total: string; pay_date: string }>(`/attendance/sheets/${encodeURIComponent(code)}/post`, {
      method: 'POST',
      body: JSON.stringify({ ...input, confirm: true }),
      headers: idempotencyHeader(key),
    }),

  reopen: (code: string, reason: string) =>
    request<{ sheet_code: string; removed: number }>(`/attendance/sheets/${encodeURIComponent(code)}/reopen`, { method: 'POST', body: JSON.stringify({ reason, confirm: true }) }),

  /** A workbook to download: the register as it stands, or a template with the case's people listed. */
  file: async (path: string) => {
    const res = await fetch(`${API}${path}`, { credentials: 'include' })
    if (!res.ok) throw new Error(await parseError(res))
    return res.blob()
  },

  exportUrl: (code: string) => `/attendance/sheets/${encodeURIComponent(code)}/export`,

  templateUrl: (caseCode: string, month: string) => `/attendance/template${queryString({ case_code: caseCode, month })}`,

  parse: async (caseCode: string, month: string, file: File) => {
    const body = new FormData()
    body.append('file', file)
    const res = await fetch(`${API}/attendance/parse${queryString({ case_code: caseCode, month })}`, { method: 'POST', credentials: 'include', body })
    if (!res.ok) throw new Error(await parseError(res))
    return (await res.json()) as { lines: AttendanceParsedLine[]; problems: { row: number; message: string }[] }
  },

  workers: (q = '', status = 'Active') => request<{ workers: AttendanceWorker[] }>(`/attendance/workers${queryString({ q, status })}`),

  createWorker: (body: Record<string, unknown>) => request<{ worker_code: string }>('/attendance/workers', { method: 'POST', body: JSON.stringify(body) }),

  updateWorker: (code: string, body: Record<string, unknown>) =>
    request<{ ok: boolean }>(`/attendance/workers/${encodeURIComponent(code)}`, { method: 'PUT', body: JSON.stringify(body) }),
}

/** The task workspace: projects, tasks, reviews, sprints, the inbox and each person's own to-do lists. */
export const tasksApi = {
  people: (project?: string) => request<{ people: TaskPersonRow[] }>(`/tasks/people${queryString({ project })}`),
  me: () => request<TaskMe>('/tasks/me'),

  projects: (archived = false) => request<{ projects: TaskProjectSummary[] }>(`/tasks/projects${queryString({ archived })}`),
  project: (key: string) => request<TaskProject>(`/tasks/projects/${encodeURIComponent(key)}`),
  createProject: (body: { key: string; name: string; description?: string; visibility?: string; require_review?: boolean; color?: string }) =>
    request<TaskProject>('/tasks/projects', { method: 'POST', body: JSON.stringify(body) }),
  updateProject: (key: string, body: Record<string, unknown>) =>
    request<TaskProject>(`/tasks/projects/${encodeURIComponent(key)}`, { method: 'PUT', body: JSON.stringify(body) }),
  archiveProject: (key: string, archived: boolean) =>
    request<TaskProject>(`/tasks/projects/${encodeURIComponent(key)}/archive`, { method: 'POST', body: JSON.stringify({ archived }) }),
  setMember: (key: string, userId: number, role: ProjectRole) =>
    request<{ members: TaskProject['members'] }>(`/tasks/projects/${encodeURIComponent(key)}/members/${userId}`, { method: 'PUT', body: JSON.stringify({ role }) }),
  removeMember: (key: string, userId: number) =>
    request<{ members: TaskProject['members'] }>(`/tasks/projects/${encodeURIComponent(key)}/members/${userId}`, { method: 'DELETE' }),
  addStatus: (key: string, name: string, category: StatusCategory) =>
    request<{ statuses: TaskStatus[] }>(`/tasks/projects/${encodeURIComponent(key)}/statuses`, { method: 'POST', body: JSON.stringify({ name, category }) }),
  updateStatus: (key: string, statusId: number, body: { name?: string; category?: StatusCategory; wip_limit?: number | null }) =>
    request<{ statuses: TaskStatus[] }>(`/tasks/projects/${encodeURIComponent(key)}/statuses/${statusId}`, { method: 'PUT', body: JSON.stringify(body) }),
  reorderStatuses: (key: string, ids: number[]) =>
    request<{ statuses: TaskStatus[] }>(`/tasks/projects/${encodeURIComponent(key)}/statuses/order`, { method: 'PUT', body: JSON.stringify({ ids }) }),
  deleteStatus: (key: string, statusId: number, moveTo?: number) =>
    request<{ statuses: TaskStatus[] }>(`/tasks/projects/${encodeURIComponent(key)}/statuses/${statusId}${queryString({ move_to: moveTo })}`, { method: 'DELETE' }),

  board: (key: string, filters: TaskFilters = {}) => request<TaskBoardData>(`/tasks/projects/${encodeURIComponent(key)}/board${queryString({ ...filters })}`),
  sprints: (key: string) => request<{ sprints: TaskSprint[] }>(`/tasks/projects/${encodeURIComponent(key)}/sprints`),
  createSprint: (key: string, body: { name: string; goal?: string; start_date?: string; end_date?: string }) =>
    request<{ sprints: TaskSprint[] }>(`/tasks/projects/${encodeURIComponent(key)}/sprints`, { method: 'POST', body: JSON.stringify(body) }),
  updateSprint: (key: string, id: number, body: Record<string, unknown>) =>
    request<{ sprints: TaskSprint[] }>(`/tasks/projects/${encodeURIComponent(key)}/sprints/${id}`, { method: 'PUT', body: JSON.stringify(body) }),
  startSprint: (key: string, id: number) =>
    request<{ sprints: TaskSprint[] }>(`/tasks/projects/${encodeURIComponent(key)}/sprints/${id}/start`, { method: 'POST' }),
  completeSprint: (key: string, id: number, moveTo?: number | null) =>
    request<{ sprints: TaskSprint[]; summary: { done: number; unfinished: number; points_done: number; moved_to: string } }>(
      `/tasks/projects/${encodeURIComponent(key)}/sprints/${id}/complete`,
      { method: 'POST', body: JSON.stringify({ move_to: moveTo ? String(moveTo) : null }) },
    ),
  burndown: (key: string, id: number) => request<TaskBurndown>(`/tasks/projects/${encodeURIComponent(key)}/sprints/${id}/burndown`),

  templates: (key: string) => request<{ templates: TaskTemplate[] }>(`/tasks/projects/${encodeURIComponent(key)}/templates`),
  saveTemplate: (key: string, body: Record<string, unknown>, id?: number) =>
    request<{ templates: TaskTemplate[] }>(`/tasks/projects/${encodeURIComponent(key)}/templates${id ? `/${id}` : ''}`, { method: id ? 'PUT' : 'POST', body: JSON.stringify(body) }),
  deleteTemplate: (key: string, id: number) =>
    request<{ templates: TaskTemplate[] }>(`/tasks/projects/${encodeURIComponent(key)}/templates/${id}`, { method: 'DELETE' }),
  makeFromTemplate: (key: string, id: number, body: { title?: string; due_date?: string; assignee_id?: number } = {}) =>
    request<TaskDetail>(`/tasks/projects/${encodeURIComponent(key)}/templates/${id}/make`, { method: 'POST', body: JSON.stringify(body) }),

  mine: () => request<TaskMine>('/tasks/mine'),
  calendar: (start: string, end: string, filters: TaskFilters = {}) => request<TaskCalendar>(`/tasks/calendar${queryString({ ...filters, start, end })}`),
  reports: (project?: string, days = 30) => request<TaskReports>(`/tasks/reports${queryString({ project, days })}`),
  search: (q: string) => request<TaskSearchResult>(`/tasks/search${queryString({ q })}`),
  filters: (project?: string) => request<{ filters: TaskSavedFilter[] }>(`/tasks/filters${queryString({ project })}`),
  saveFilter: (body: { name: string; definition: Record<string, unknown>; project?: string; shared?: boolean }) =>
    request<{ filters: TaskSavedFilter[] }>('/tasks/filters', { method: 'POST', body: JSON.stringify(body) }),
  deleteFilter: (id: number) => request<{ filters: TaskSavedFilter[] }>(`/tasks/filters/${id}`, { method: 'DELETE' }),

  inbox: (unread = false, before?: number) => request<TaskInbox>(`/tasks/notifications${queryString({ unread, before })}`),
  markRead: (ids?: number[]) => request<{ marked: number }>('/tasks/notifications/read', { method: 'POST', body: JSON.stringify({ ids: ids ?? null }) }),
  reminders: () => request<TaskReminders>('/tasks/reminders'),

  todo: () => request<TodoOverview>('/tasks/todo'),
  createTodoList: (name: string) => request<TodoOverview>('/tasks/todo/lists', { method: 'POST', body: JSON.stringify({ name }) }),
  renameTodoList: (id: number, name: string) => request<TodoOverview>(`/tasks/todo/lists/${id}`, { method: 'PUT', body: JSON.stringify({ name }) }),
  deleteTodoList: (id: number) => request<TodoOverview>(`/tasks/todo/lists/${id}`, { method: 'DELETE' }),
  addTodo: (body: { text: string; notes?: string; list_id?: number | null; due_date?: string | null; my_day?: string | null }, key?: string) =>
    request<TodoOverview>('/tasks/todo/items', { method: 'POST', body: JSON.stringify(body), headers: idempotencyHeader(key) }),
  updateTodo: (id: number, body: Record<string, unknown>) => request<TodoOverview>(`/tasks/todo/items/${id}`, { method: 'PUT', body: JSON.stringify(body) }),
  deleteTodo: (id: number) => request<TodoOverview>(`/tasks/todo/items/${id}`, { method: 'DELETE' }),
  clearTodo: (listId?: number | 'inbox') => request<TodoOverview>(`/tasks/todo/clear${queryString({ list_id: listId })}`, { method: 'POST' }),
  todoToTask: (id: number, body: { project: string; assignee_id?: number; priority?: TaskPriority; type?: TaskKind }) =>
    request<{ task: TaskDetail; todo: TodoOverview }>(`/tasks/todo/items/${id}/task`, { method: 'POST', body: JSON.stringify(body) }),

  list: (filters: TaskFilters = {}) => request<TaskListResult>(`/tasks${queryString({ ...filters })}`),
  create: (project: string, body: TaskInput, key?: string) =>
    request<TaskDetail>('/tasks', { method: 'POST', body: JSON.stringify({ ...body, project }), headers: idempotencyHeader(key) }),
  get: (key: string) => request<TaskDetail>(`/tasks/${encodeURIComponent(key)}`),
  update: (key: string, changes: TaskChanges, expectedUpdated?: string) =>
    request<TaskDetail>(`/tasks/${encodeURIComponent(key)}`, { method: 'PUT', body: JSON.stringify({ ...changes, expected_updated: expectedUpdated }) }),
  remove: (key: string) => request<{ ok: boolean }>(`/tasks/${encodeURIComponent(key)}`, { method: 'DELETE' }),
  restore: (key: string) => request<TaskDetail>(`/tasks/${encodeURIComponent(key)}/restore`, { method: 'POST' }),
  move: (key: string, body: TaskMoveInput) => request<TaskDetail>(`/tasks/${encodeURIComponent(key)}/move`, { method: 'POST', body: JSON.stringify(body) }),
  requestReview: (key: string, reviewerId: number, note?: string) =>
    request<TaskDetail>(`/tasks/${encodeURIComponent(key)}/review/request`, { method: 'POST', body: JSON.stringify({ reviewer_id: reviewerId, note }) }),
  decideReview: (key: string, decision: 'approve' | 'changes', note?: string) =>
    request<TaskDetail>(`/tasks/${encodeURIComponent(key)}/review/decide`, { method: 'POST', body: JSON.stringify({ decision, note }) }),
  withdrawReview: (key: string) => request<TaskDetail>(`/tasks/${encodeURIComponent(key)}/review/withdraw`, { method: 'POST' }),
  bulk: (keys: string[], changes: Record<string, unknown>) =>
    request<{ changed: string[]; failed: { key: string; reason: string }[] }>('/tasks/bulk', { method: 'POST', body: JSON.stringify({ keys, changes }) }),

  comments: (key: string) => request<{ comments: TaskComment[] }>(`/tasks/${encodeURIComponent(key)}/comments`),
  addComment: (key: string, body: string, idem?: string) =>
    request<TaskComment>(`/tasks/${encodeURIComponent(key)}/comments`, { method: 'POST', body: JSON.stringify({ body }), headers: idempotencyHeader(idem) }),
  editComment: (id: number, body: string) => request<{ ok: boolean }>(`/tasks/comments/${id}`, { method: 'PUT', body: JSON.stringify({ body }) }),
  deleteComment: (id: number) => request<{ ok: boolean }>(`/tasks/comments/${id}`, { method: 'DELETE' }),
  activity: (key: string, before?: number) => request<{ activity: TaskActivityLine[] }>(`/tasks/${encodeURIComponent(key)}/activity${queryString({ before })}`),
  watch: (key: string, watching: boolean, userId?: number) =>
    request<{ watchers: TaskPerson[] }>(`/tasks/${encodeURIComponent(key)}/watch`, { method: 'POST', body: JSON.stringify({ watching, user_id: userId }) }),

  addChecklist: (key: string, text: string) =>
    request<{ checklist: TaskChecklistItem[] }>(`/tasks/${encodeURIComponent(key)}/checklist`, { method: 'POST', body: JSON.stringify({ text }) }),
  updateChecklist: (id: number, body: { text?: string; done?: boolean; position?: number }) =>
    request<{ checklist: TaskChecklistItem[] }>(`/tasks/checklist/${id}`, { method: 'PUT', body: JSON.stringify(body) }),
  deleteChecklist: (id: number) => request<{ checklist: TaskChecklistItem[] }>(`/tasks/checklist/${id}`, { method: 'DELETE' }),

  addLink: (key: string, kind: TaskLinkKind, otherKey: string) =>
    request<{ links: TaskLink[] }>(`/tasks/${encodeURIComponent(key)}/links`, { method: 'POST', body: JSON.stringify({ kind, other_key: otherKey }) }),
  removeLink: (key: string, id: number) => request<{ links: TaskLink[] }>(`/tasks/${encodeURIComponent(key)}/links/${id}`, { method: 'DELETE' }),
  addRecord: (key: string, type: string, ref: string) =>
    request<{ records: TaskRecordLink[] }>(`/tasks/${encodeURIComponent(key)}/records`, { method: 'POST', body: JSON.stringify({ type, ref }) }),
  removeRecord: (key: string, id: number) => request<{ records: TaskRecordLink[] }>(`/tasks/${encodeURIComponent(key)}/records/${id}`, { method: 'DELETE' }),

  logTime: (key: string, minutes: number, date?: string, note?: string) =>
    request<TaskTime & { spent_minutes: number }>(`/tasks/${encodeURIComponent(key)}/time`, { method: 'POST', body: JSON.stringify({ minutes, date, note }) }),
  deleteTime: (key: string, id: number) => request<TaskTime & { spent_minutes: number }>(`/tasks/${encodeURIComponent(key)}/time/${id}`, { method: 'DELETE' }),

  attachments: (key: string) => request<{ attachments: TaskAttachment[] }>(`/tasks/${encodeURIComponent(key)}/attachments`),
  attach: (key: string, file: File, commentId?: number) => {
    const body = new FormData()
    body.append('file', file)
    if (commentId !== undefined) body.append('comment_id', String(commentId))
    return upload<{ attachments: TaskAttachment[] }>(`/tasks/${encodeURIComponent(key)}/attachments`, body)
  },
  deleteAttachment: (id: number) => request<{ attachments: TaskAttachment[] }>(`/tasks/attachments/${id}`, { method: 'DELETE' }),
  /** Where a file is fetched: the browser opens a picture or a PDF in place and downloads anything else. */
  attachmentUrl: (id: number, download = false) => `${API}/tasks/attachments/${id}/file${download ? '?download=true' : ''}`,
}
