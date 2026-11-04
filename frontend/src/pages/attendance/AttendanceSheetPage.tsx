import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { useNavigate, useParams, useSearchParams } from 'react-router-dom'
import { ArrowLeft, Copy, Download, FileSpreadsheet, History, RotateCcw, Save, Search, Send, Trash2, Undo2, Upload, UserPlus, X } from 'lucide-react'
import { ApiError, attendanceApi } from '../../api/client'
import { daysInMonth, monthName, thisMonth } from '../../attendance/attendanceCalc'
import {
  applyUpload,
  copyPrevious,
  counted,
  figure,
  payloadOf,
  rowsFromRoster,
  rowsFromSheet,
  totalOf,
  withFigure,
  type Row,
} from '../../attendance/attendanceDraft'
import { money, day } from '../../bank/format'
import { AddPersonModal, PostModal, ReopenModal } from '../../components/attendance/AttendanceModals'
import { PersonCard, SheetBar } from '../../components/attendance/lumenAttendance'
import { StatTile } from '../../components/billing/StatTile'
import { Alert, Badge } from '../../components/ui/Alert'
import { Button } from '../../components/ui/Button'
import { LoadingState } from '../../components/ui/DataTable'
import { EmptyState } from '../../components/ui/EmptyState'
import { Field, Input } from '../../components/ui/Field'
import { MoneyInput } from '../../components/ui/MoneyInput'
import { SearchSelect } from '../../components/ui/SearchSelect'
import { TabLink } from '../../components/ui/TabLink'
import { useToast } from '../../components/ui/Toast'
import { Tooltip } from '../../components/ui/Tooltip'
import { useAuth } from '../../context/AuthContext'
import { useLumen } from '../../lumen/useLumen'
import { timeAgo } from '../../formatTime'
import type { AttendanceCase, AttendanceRoster, AttendanceSheet } from '../../types'

function saveFile(blob: Blob, name: string) {
  const url = URL.createObjectURL(blob)
  const link = document.createElement('a')
  link.href = url
  link.download = name
  link.click()
  window.setTimeout(() => URL.revokeObjectURL(url), 1000)
}

const cellBase = 'w-full rounded-md border border-[color:var(--color-border)] bg-surface px-2 py-1.5 text-sm tabular-nums focus:border-accent focus:outline-none focus:ring-2 focus:ring-[color:var(--orion-ring)] disabled:bg-muted disabled:opacity-70'
const cell = `${cellBase} text-right`

/**
 * One attendance register: a case, a month, and the people who worked. A new one opens with the case's employees listed (counted, with their day's pay from their
 * salary); leave a person out, change the days, the rate, an extra or a deduction, or type the amount that is to be paid. Add people who are not on the list,
 * including people who are not employees, who are saved for the next register. Posting enters the pay: a salary line for each employee, an expense for each
 * other person. A posted register is changed only by reopening it.
 */
export function AttendanceSheetPage() {
  const { code } = useParams()
  const [params] = useSearchParams()
  const navigate = useNavigate()
  const { user } = useAuth()
  const toast = useToast()
  const lumen = useLumen()
  const canWrite = Boolean(user?.can_attendance_write)

  // Choosing the case and month of a new register.
  const [cases, setCases] = useState<AttendanceCase[]>([])
  const [caseCode, setCaseCode] = useState(params.get('case') ?? '')
  const [month, setMonth] = useState(params.get('month') ?? thisMonth())
  const [opening, setOpening] = useState(false)

  // The register being edited.
  const [sheet, setSheet] = useState<AttendanceSheet | null>(null)
  const [roster, setRoster] = useState<AttendanceRoster | null>(null)
  const [rows, setRows] = useState<Row[]>([])
  const [expenseType, setExpenseType] = useState('')
  const [remarks, setRemarks] = useState('')
  const [expenseTypes, setExpenseTypes] = useState<{ code: string; name: string }[]>([])
  const [dirty, setDirty] = useState(false)
  const [loading, setLoading] = useState(Boolean(code))
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')
  const [problems, setProblems] = useState<{ row: number; message: string }[]>([])
  const [find, setFind] = useState('')
  const [saving, setSaving] = useState(false)
  const [adding, setAdding] = useState(false)
  const [posting, setPosting] = useState(false)
  const [reopening, setReopening] = useState(false)
  const [showHistory, setShowHistory] = useState(false)
  const upload = useRef<HTMLInputElement>(null)

  const posted = sheet?.status === 'Posted'
  const editable = canWrite && !posted
  const monthKey = sheet?.month_year ?? month
  const monthDays = sheet?.days_in_month ?? roster?.days_in_month ?? daysInMonth(monthKey)
  const started = Boolean(sheet || roster)

  useEffect(() => {
    attendanceApi.cases('').then((r) => setCases(r.cases)).catch(() => setCases([]))
    attendanceApi.expenseTypes().then((r) => setExpenseTypes(r.expense_types)).catch(() => setExpenseTypes([]))
  }, [])

  // An existing register: the register itself, and the case's roster so a person who was left out can be put back.
  const load = useCallback(async () => {
    if (!code) return
    setLoading(true)
    try {
      const found = await attendanceApi.sheet(code)
      const list = found.status === 'Draft' ? await attendanceApi.roster(found.case_code, found.month_year).catch(() => null) : null
      setSheet(found)
      setRoster(list)
      setRows(rowsFromSheet(found.lines, list))
      setExpenseType(found.expense_type_code ?? '')
      setRemarks(found.remarks ?? '')
      setDirty(false)
      setError('')
    } catch (e) {
      setError(e instanceof Error ? e.message : 'The register could not be opened.')
    } finally {
      setLoading(false)
    }
  }, [code])

  useEffect(() => {
    setSheet(null)
    setRoster(null)
    setRows([])
    void load()
  }, [load])

  // Leaving with changes that were not saved asks first.
  useEffect(() => {
    if (!dirty) return
    const warn = (event: BeforeUnloadEvent) => event.preventDefault()
    window.addEventListener('beforeunload', warn)
    return () => window.removeEventListener('beforeunload', warn)
  }, [dirty])

  const openRegister = async () => {
    if (!caseCode) return
    setOpening(true)
    setError('')
    try {
      const found = await attendanceApi.roster(caseCode, month)
      if (found.existing) {
        navigate(`/attendance/${found.existing.sheet_code}`, { replace: true })
        return
      }
      setRoster(found)
      setRows(rowsFromRoster(found))
      setDirty(false)
    } catch (e) {
      setError(e instanceof Error ? e.message : 'That register could not be opened.')
    } finally {
      setOpening(false)
    }
  }

  // A register opened from a link with the case and month in it opens at once.
  const autoOpened = useRef(false)
  useEffect(() => {
    if (!code && !autoOpened.current && params.get('case') && params.get('month')) {
      autoOpened.current = true
      void openRegister()
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps -- opened once, from the address
  }, [])

  const change = (key: string, patch: Partial<Row>) => {
    setRows((current) => current.map((r) => (r.key === key ? withFigure(r, patch) : r)))
    setDirty(true)
  }
  const mutate = (fn: (current: Row[]) => Row[]) => {
    setRows(fn)
    setDirty(true)
  }

  const shown = useMemo(() => {
    const needle = find.trim().toLowerCase()
    return needle ? rows.filter((r) => `${r.name} ${r.employee_code ?? ''} ${r.worker_code ?? ''} ${r.designation}`.toLowerCase().includes(needle)) : rows
  }, [rows, find])
  const on = counted(rows)
  const total = totalOf(rows)
  const employeeTotal = Math.round(on.filter((r) => r.employee_code).reduce((s, r) => s + Number(r.amount || 0) * 100, 0)) / 100
  const workerTotal = Math.round((total - employeeTotal) * 100) / 100
  const payable = on.filter((r) => Number(r.amount) > 0)
  const overDays = on.filter((r) => Number(r.days_present) > monthDays)
  const noDays = on.filter((r) => !Number(r.days_present))

  const body = () => ({
    case_code: sheet?.case_code ?? roster?.case.case_code ?? caseCode,
    month_year: monthKey,
    lines: counted(rows).map(payloadOf),
    remarks: remarks || null,
    expense_type_code: expenseType || null,
  })

  /** Saves the register as a draft. Returns its code, or null when it did not save. */
  const save = async (quiet = false): Promise<string | null> => {
    setSaving(true)
    setError('')
    try {
      if (sheet) {
        await attendanceApi.save(sheet.sheet_code, body())
        await load()
        if (!quiet) toast.show('Register saved')
        return sheet.sheet_code
      }
      const made = await attendanceApi.create(body())
      if (!quiet) toast.show('Register saved', { detail: `${made.sheet_code} is a draft until it is posted.` })
      setDirty(false)
      navigate(`/attendance/${made.sheet_code}`, { replace: true })
      return made.sheet_code
    } catch (e) {
      setError(e instanceof Error ? e.message : 'That did not save. Try again.')
      if (e instanceof ApiError && e.status === 409 && sheet) setNotice('The register was changed by someone else. Reload it to see where it stands.')
      return null
    } finally {
      setSaving(false)
    }
  }

  // Posting needs the register saved as it stands: a new or changed one is saved first, and the posting screen opens once it is back.
  const postAfterSave = useRef(false)
  const startPosting = async () => {
    setNotice('')
    if (sheet && !dirty) {
      setPosting(true)
      return
    }
    postAfterSave.current = true
    if (!(await save(true))) postAfterSave.current = false
  }
  useEffect(() => {
    if (sheet && postAfterSave.current) {
      postAfterSave.current = false
      setPosting(true)
    }
  }, [sheet])

  const confirmPost = async (key: string): Promise<string | null> => {
    if (!sheet) return 'The register is not open. Close this and try again.'
    // The expense type may have been chosen on the posting screen.
    if (dirty && !(await save(true))) return 'The register could not be saved first. Close this and try again.'
    try {
      const done = await attendanceApi.post(sheet.sheet_code, { seen_count: payable.length, seen_total: total.toFixed(2) }, key)
      setPosting(false)
      toast.show('Attendance posted', { detail: `${done.salary_lines} salary line${done.salary_lines === 1 ? '' : 's'} and ${done.expenses} expense${done.expenses === 1 ? '' : 's'} entered. Pay them in Bank.` })
      await load()
      return null
    } catch (e) {
      if (e instanceof ApiError && e.status === 409) {
        setPosting(false)
        setNotice(e.message)
        await load()
        return null
      }
      return e instanceof Error ? e.message : 'That did not post. Try again.'
    }
  }

  const readUpload = async (file: File) => {
    const target = sheet?.case_code ?? roster?.case.case_code ?? caseCode
    setError('')
    try {
      const parsed = await attendanceApi.parse(target, monthKey, file)
      mutate((current) => applyUpload(current, parsed.lines))
      setProblems(parsed.problems)
      toast.show(`${parsed.lines.length} ${parsed.lines.length === 1 ? 'person' : 'people'} read from the file`, {
        detail: parsed.problems.length ? `${parsed.problems.length} row${parsed.problems.length === 1 ? '' : 's'} could not be read.` : 'Check them, then save.',
      })
    } catch (e) {
      setError(e instanceof Error ? e.message : 'That file could not be read.')
    }
  }

  const download = async (path: string, name: string) => {
    try {
      saveFile(await attendanceApi.file(path), name)
    } catch (e) {
      setError(e instanceof Error ? e.message : 'That could not be downloaded.')
    }
  }

  const removeDraft = async () => {
    if (!sheet || !window.confirm(`Delete the draft register ${sheet.sheet_code}? Its lines are lost.`)) return
    try {
      await attendanceApi.remove(sheet.sheet_code)
      navigate('/attendance', { replace: true })
    } catch (e) {
      setError(e instanceof Error ? e.message : 'That could not be deleted.')
    }
  }

  // ---------------------------------------------------------------------------------------------------------------------------------- the screen

  const caseName = sheet?.case_name ?? roster?.case.case_name ?? ''
  const clientName = sheet?.client_name ?? roster?.case.client_name ?? null

  const totals = (
    <section className={`grid gap-3 sm:grid-cols-4 ${lumen ? 'grid-cols-2' : ''}`} aria-label="Totals">
            <Total label="People counted" value={String(posted ? (sheet?.totals.people ?? 0) : on.length)} note={`${posted ? sheet?.totals.employees : on.filter((r) => r.employee_code).length} employees, ${posted ? sheet?.totals.workers : on.filter((r) => !r.employee_code).length} others`} />
            <Total label="Employees: salary lines" value={money(posted ? Number(sheet?.totals.employee_amount) : employeeTotal)} note="Paid in Bank > Payroll" />
            <Total label="Others: expenses" value={money(posted ? Number(sheet?.totals.worker_amount) : workerTotal)} note="Paid in Bank > Payables" />
            <Total label="Total to pay" value={money(posted ? Number(sheet?.totals.amount) : total)} strong note={posted ? sheet?.posted_timestamp ? `Posted ${day(sheet.posted_timestamp)}` : undefined : dirty ? 'Not saved yet' : sheet ? 'Saved as a draft' : undefined} />
          </section>
  )

  if (loading) return <LoadingState message="Opening the register…" />

  return (
    <div className={`space-y-4 ${lumen && editable && started ? 'pb-28' : ''}`}>
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <button type="button" onClick={() => navigate('/attendance')} className="interactive mb-1 inline-flex items-center gap-1 text-sm text-[color:var(--color-text-muted)] hover:text-[color:var(--color-text)]">
            <ArrowLeft className="h-4 w-4" aria-hidden="true" /> Attendance
          </button>
          <p className="eyebrow">{sheet ? sheet.sheet_code : 'New register'}</p>
          <h1 className="t-h1 flex flex-wrap items-center gap-2">
            {started ? `${caseName} · ${monthName(monthKey)}` : 'Attendance register'}
            {sheet && <Badge variant={posted ? 'emerald' : 'amber'}>{posted ? 'Posted' : 'Draft'}</Badge>}
          </h1>
          {started && clientName && <p className="t-small text-[color:var(--color-text-muted)]">{clientName}</p>}
        </div>
        {started && (
          <div className="flex flex-wrap items-center gap-2">
            {sheet && (
              <Button variant="secondary" onClick={() => download(attendanceApi.exportUrl(sheet.sheet_code), `${sheet.sheet_code}.xlsx`)}>
                <Download className="h-4 w-4" /> Excel
              </Button>
            )}
            {sheet && sheet.events.length > 0 && (
              <Button variant="ghost" onClick={() => setShowHistory((v) => !v)} aria-pressed={showHistory}>
                <History className="h-4 w-4" /> History
              </Button>
            )}
            {canWrite && posted && (
              <Button variant="secondary" onClick={() => { setNotice(''); setReopening(true) }}>
                <Undo2 className="h-4 w-4" /> Reopen
              </Button>
            )}
            {editable && sheet && (
              <Button variant="ghost" onClick={removeDraft}>
                <Trash2 className="h-4 w-4" /> Delete draft
              </Button>
            )}
            {editable && !lumen && (
              <Button variant="secondary" onClick={() => void save()} loading={saving} disabled={!dirty && Boolean(sheet)}>
                <Save className="h-4 w-4" /> {dirty || !sheet ? 'Save draft' : 'Saved'}
              </Button>
            )}
            {editable && !lumen && (
              <Button onClick={() => void startPosting()} disabled={payable.length === 0 || saving}>
                <Send className="h-4 w-4" /> Post…
              </Button>
            )}
          </div>
        )}
      </div>

      {error && <Alert variant="error" onDismiss={() => setError('')}>{error}</Alert>}
      {notice && <Alert variant="error" onDismiss={() => setNotice('')}>{notice}</Alert>}

      {/* Choosing a case and a month */}
      {!started && (
        <section className="panel max-w-2xl space-y-4 p-5" aria-label="Choose the register">
          <p className="text-sm text-[color:var(--color-text-muted)]">
            Choose the case and the month. The case&apos;s employees are listed for you, and you can add anyone else, including people who are not employees.
          </p>
          <div className="grid gap-4 sm:grid-cols-2">
            <Field label="Case" required className="sm:col-span-2">
              <SearchSelect
                value={caseCode}
                options={cases.map((c) => ({ id: c.case_code, label: c.client_name ? `${c.case_name} — ${c.client_name}` : c.case_name }))}
                onChange={(next) => setCaseCode(next ?? '')}
                placeholder="— Choose the case —"
              />
            </Field>
            <Field label="Month" required>
              <Input type="month" value={month} max={thisMonth()} onChange={(e) => setMonth(e.target.value)} />
            </Field>
          </div>
          <Button onClick={openRegister} loading={opening} disabled={!caseCode || !month || !canWrite}>
            Open the register
          </Button>
          {!canWrite && <p className="t-caption">You can see registers, but you do not have permission to make one.</p>}
        </section>
      )}

      {started && (
        <>
          {posted && sheet && (
            <Alert variant="info">
              Posted {timeAgo(sheet.posted_timestamp)}
              {sheet.posted_by_name ? ` by ${sheet.posted_by_name}` : ''}. {sheet.totals.employees > 0 && <>Pay the salary in <TabLink to="/bank/payroll" className="font-medium underline">Bank &gt; Payroll</TabLink>. </>}
              {sheet.totals.workers > 0 && <>Pay the others in <TabLink to="/bank/payables" className="font-medium underline">Bank &gt; Payables</TabLink> (the expenses are under {sheet.expense_type_name ?? 'the chosen type'}). </>}
              The register is changed by reopening it, until any of it is paid.
            </Alert>
          )}

          {showHistory && sheet && (
            <section className="panel p-4" aria-label="History">
              <ol className="space-y-1.5 text-sm">
                {sheet.events.map((e, i) => (
                  <li key={i} className="flex flex-wrap gap-x-3">
                    <span className="w-40 shrink-0 text-xs text-[color:var(--color-text-muted)]">{timeAgo(e.at)}</span>
                    <span className="font-medium capitalize">{e.action}</span>
                    <span className="text-[color:var(--color-text-muted)]">{e.by_name ? `by ${e.by_name}` : ''}{e.note ? ` · ${e.note}` : ''}</span>
                  </li>
                ))}
              </ol>
            </section>
          )}

          {problems.length > 0 && (
            <Alert variant="error" onDismiss={() => setProblems([])}>
              <p className="font-medium">{problems.length} row{problems.length === 1 ? '' : 's'} of the file could not be used:</p>
              <ul className="mt-1 list-disc pl-5">
                {problems.slice(0, 8).map((p) => (
                  <li key={p.row}>Row {p.row}: {p.message}</li>
                ))}
              </ul>
            </Alert>
          )}

          {lumen && totals}

          {/* Tools */}
          {editable && (
            <div className="flex flex-wrap items-center gap-2">
              <div className="relative min-w-[14rem] flex-1 sm:max-w-xs">
                <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-[color:var(--color-text-faint)]" aria-hidden="true" />
                <Input className="pl-9" value={find} onChange={(e) => setFind(e.target.value)} placeholder="Find a person" aria-label="Find a person on this register" />
              </div>
              <Button variant="secondary" onClick={() => setAdding(true)}>
                <UserPlus className="h-4 w-4" /> Add people
              </Button>
              <Button variant="secondary" onClick={() => upload.current?.click()}>
                <Upload className="h-4 w-4" /> Upload Excel
              </Button>
              <input
                ref={upload}
                type="file"
                accept=".xlsx"
                className="sr-only"
                aria-label="Choose the attendance workbook"
                onChange={(e) => {
                  const file = e.target.files?.[0]
                  e.target.value = ''
                  if (file) void readUpload(file)
                }}
              />
              <Button variant="ghost" onClick={() => download(attendanceApi.templateUrl(sheet?.case_code ?? roster?.case.case_code ?? caseCode, monthKey), `attendance_${monthKey}.xlsx`)}>
                <FileSpreadsheet className="h-4 w-4" /> Template
              </Button>
              {roster?.previous && (
                <Tooltip label={`Use the days and rates of ${monthName(roster.previous.month_year)} (${roster.previous.sheet_code})`}>
                  <Button variant="ghost" onClick={() => roster.previous && mutate((current) => copyPrevious(current, roster.previous!, roster))}>
                    <Copy className="h-4 w-4" /> Copy last month
                  </Button>
                </Tooltip>
              )}
              <Button variant="ghost" onClick={() => mutate((current) => current.map((r) => (r.included ? withFigure(r, { days_present: String(monthDays) }) : r)))}>
                Full month for everyone counted
              </Button>
              <Button variant="ghost" onClick={() => mutate((current) => current.map((r) => (r.included ? withFigure(r, { days_present: '' }) : r)))}>
                <RotateCcw className="h-4 w-4" /> Clear days
              </Button>
            </div>
          )}

          {/* The register */}
          {rows.length === 0 ? (
            <EmptyState compact title="Nobody on this register yet">
              This case has no employees. Add people with “Add people”, or upload a filled workbook.
            </EmptyState>
          ) : lumen ? (
            <section aria-label="Register" className="space-y-3">
              {editable && (
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <p className="t-caption text-[color:var(--color-text-muted)]">
                    {on.length} of {rows.length} counted · tick the circle to count or leave out a person
                  </p>
                  <button
                    type="button"
                    className="interactive rounded-full border border-[color:var(--color-border)] px-3.5 py-1.5 text-xs font-semibold text-[color:var(--color-text-muted)] hover:bg-muted"
                    onClick={() => {
                      const all = shown.length > 0 && shown.every((r) => r.included)
                      mutate((current) => current.map((r) => (shown.some((s) => s.key === r.key) ? { ...r, included: !all } : r)))
                    }}
                  >
                    {shown.length > 0 && shown.every((r) => r.included) ? 'Leave everyone shown out' : 'Count everyone shown'}
                  </button>
                </div>
              )}
              <ul className="grid gap-3 xl:grid-cols-2">
                {shown.map((row) => (
                  <PersonCard
                    key={row.key}
                    row={row}
                    editable={editable}
                    posted={posted}
                    monthDays={monthDays}
                    monthLabel={monthName(monthKey)}
                    onChange={(patch) => change(row.key, patch)}
                    onRemove={editable && !row.from_roster ? () => mutate((current) => current.filter((r) => r.key !== row.key)) : undefined}
                  />
                ))}
              </ul>
            </section>
          ) : (
            <section className="panel overflow-x-auto" aria-label="Register">
              <table className="w-full min-w-[62rem] text-sm">
                <caption className="sr-only">Attendance for {caseName}, {monthName(monthKey)}</caption>
                <thead>
                  <tr className="border-b border-[color:var(--color-border)] text-left text-xs text-[color:var(--color-text-muted)]">
                    {editable && (
                      <th scope="col" className="w-10 px-3 py-2.5">
                        <input
                          type="checkbox"
                          aria-label="Count everyone shown"
                          checked={shown.length > 0 && shown.every((r) => r.included)}
                          onChange={(e) => mutate((current) => current.map((r) => (shown.some((s) => s.key === r.key) ? { ...r, included: e.target.checked } : r)))}
                        />
                      </th>
                    )}
                    <th scope="col" className="px-2 py-2.5 font-medium">Person</th>
                    <th scope="col" className="w-24 px-2 py-2.5 text-right font-medium">Days <span className="font-normal">(of {monthDays})</span></th>
                    <th scope="col" className="w-32 px-2 py-2.5 text-right font-medium">Pay for a day</th>
                    <th scope="col" className="w-28 px-2 py-2.5 text-right font-medium">Extra</th>
                    <th scope="col" className="w-28 px-2 py-2.5 text-right font-medium">Deduction</th>
                    <th scope="col" className="w-36 px-2 py-2.5 text-right font-medium">Amount</th>
                    <th scope="col" className="px-2 py-2.5 font-medium">Remarks</th>
                    {editable && <th scope="col" className="w-10 px-2 py-2.5"><span className="sr-only">Remove</span></th>}
                  </tr>
                </thead>
                <tbody>
                  {shown.map((row) => {
                    const off = editable && !row.included
                    const edited = row.amount_set && Number(row.amount) !== Number(figure(row))
                    const lock = !editable || off
                    return (
                      <tr key={row.key} className={`border-b border-[color:var(--color-border)]/60 align-top ${off ? 'opacity-55' : 'hover:bg-muted/40'}`}>
                        {editable && (
                          <td className="px-3 py-2.5">
                            <input type="checkbox" aria-label={`Count ${row.name}`} checked={row.included} onChange={(e) => change(row.key, { included: e.target.checked })} />
                          </td>
                        )}
                        <td className="px-2 py-2">
                          <p className="font-medium">{row.name}</p>
                          <p className="t-caption flex flex-wrap items-center gap-x-1.5">
                            {row.employee_code ? <Badge variant="cyan">Employee</Badge> : <Badge variant="amber">{row.new_worker ? 'New person' : 'Not an employee'}</Badge>}
                            {[row.employee_code ?? row.worker_code, row.designation].filter(Boolean).join(' · ')}
                          </p>
                          {row.warnings.map((w) => (
                            <p key={w} className="t-caption text-warning">{w}</p>
                          ))}
                          {Number(row.days_present) > monthDays && row.included && <p className="t-caption text-negative">More days than {monthName(monthKey)} has.</p>}
                          {posted && (row.salary_code || row.expense_code) && (
                            <p className="t-caption">
                              Entered as {row.salary_code ?? row.expense_code}
                              {row.paid ? ' · paid' : ' · not paid yet'}
                            </p>
                          )}
                        </td>
                        <td className="px-2 py-2">
                          <input
                            className={cell}
                            type="number"
                            inputMode="decimal"
                            min={0}
                            max={monthDays}
                            step={0.5}
                            disabled={lock}
                            aria-label={`Days present for ${row.name}`}
                            value={row.days_present}
                            onChange={(e) => change(row.key, { days_present: e.target.value })}
                          />
                        </td>
                        <td className="px-2 py-2">
                          <MoneyInput value={row.rate_per_day} decimals={4} words={false} disabled={lock} aria-label={`Pay for a day for ${row.name}`} className={cell} onChange={(v) => change(row.key, { rate_per_day: v })} />
                        </td>
                        <td className="px-2 py-2">
                          <MoneyInput value={row.extra_amount} words={false} disabled={lock} aria-label={`Extra for ${row.name}`} className={cell} onChange={(v) => change(row.key, { extra_amount: v })} />
                        </td>
                        <td className="px-2 py-2">
                          <MoneyInput value={row.deduction_amount} words={false} disabled={lock} aria-label={`Deduction for ${row.name}`} className={cell} onChange={(v) => change(row.key, { deduction_amount: v })} />
                        </td>
                        <td className="px-2 py-2">
                          <MoneyInput
                            value={row.amount}
                            words={false}
                            disabled={lock}
                            aria-label={`Amount for ${row.name}`}
                            className={`${cell} font-semibold`}
                            onChange={(v) => change(row.key, { amount: v, amount_set: true })}
                          />
                          {edited && !lock && (
                            <button type="button" className="mt-0.5 block w-full text-right text-[11px] text-accent hover:underline" onClick={() => change(row.key, { amount_set: false })}>
                              Typed, not worked out · use {money(Number(figure(row)))}
                            </button>
                          )}
                        </td>
                        <td className="px-2 py-2">
                          <input
                            className={cellBase}
                            disabled={lock}
                            maxLength={200}
                            aria-label={`Remarks for ${row.name}`}
                            value={row.remarks}
                            onChange={(e) => change(row.key, { remarks: e.target.value })}
                          />
                        </td>
                        {editable && (
                          <td className="px-2 py-2.5 text-center">
                            {!row.from_roster && (
                              <button type="button" aria-label={`Remove ${row.name}`} className="interactive rounded p-1 text-[color:var(--color-text-faint)] hover:text-negative" onClick={() => mutate((current) => current.filter((r) => r.key !== row.key))}>
                                <X className="h-4 w-4" />
                              </button>
                            )}
                          </td>
                        )}
                      </tr>
                    )
                  })}
                </tbody>
              </table>
            </section>
          )}

          {!lumen && totals}

          {editable && (noDays.length > 0 || overDays.length > 0) && (
            <p className="t-caption">
              {noDays.length > 0 && `${noDays.length} counted ${noDays.length === 1 ? 'person has' : 'people have'} no days yet and ${noDays.length === 1 ? 'is' : 'are'} paid nothing unless an amount is typed. `}
              {overDays.length > 0 && `${overDays.length} ${overDays.length === 1 ? 'has' : 'have'} more days than the month.`}
            </p>
          )}

          {editable && (
            <Field label="Note for this register">
              <Input value={remarks} maxLength={500} placeholder="Optional" onChange={(e) => { setRemarks(e.target.value); setDirty(true) }} />
            </Field>
          )}
        </>
      )}

      {lumen && editable && started && rows.length > 0 && (
        <SheetBar
          people={on.length}
          total={total}
          note={dirty ? 'not saved yet' : sheet ? 'saved as a draft' : 'new register'}
          saving={saving}
          canSave={dirty || !sheet}
          canPost={payable.length > 0}
          onSave={() => void save()}
          onPost={() => void startPosting()}
        />
      )}

      {adding && (
        <AddPersonModal
          month={monthKey}
          have={new Set(rows.map((r) => r.key))}
          onClose={() => setAdding(false)}
          onAdd={(row) => mutate((current) => (current.some((r) => r.key === row.key) ? current.map((r) => (r.key === row.key ? { ...r, included: true } : r)) : [...current, row]))}
        />
      )}
      {posting && (
        <PostModal
          monthYear={monthKey}
          caseName={caseName}
          employees={payable.filter((r) => r.employee_code).length}
          workers={payable.filter((r) => !r.employee_code).length}
          employeeAmount={Math.round(payable.filter((r) => r.employee_code).reduce((s, r) => s + Number(r.amount) * 100, 0)) / 100}
          workerAmount={Math.round(payable.filter((r) => !r.employee_code).reduce((s, r) => s + Number(r.amount) * 100, 0)) / 100}
          expenseTypes={expenseTypes}
          expenseType={expenseType}
          onExpenseType={(next) => { setExpenseType(next); setDirty(true) }}
          onClose={() => setPosting(false)}
          onConfirm={confirmPost}
        />
      )}
      {reopening && sheet && (
        <ReopenModal
          code={sheet.sheet_code}
          onClose={() => setReopening(false)}
          onDone={() => { setReopening(false); toast.show('Register reopened', { detail: 'Its salary lines and expenses were taken back.' }); void load() }}
          onConflict={(message) => { setReopening(false); setNotice(message); void load() }}
        />
      )}
    </div>
  )
}

function Total({ label, value, note, strong }: { label: string; value: string; note?: string; strong?: boolean }) {
  const lumen = useLumen()
  if (lumen) return <StatTile label={label} text={value} hint={note} tone={strong ? 'text-positive' : ''} />
  return (
    <div className="panel p-4">
      <p className="t-caption">{label}</p>
      <p className={`mt-1 tabular-nums ${strong ? 'text-2xl font-bold' : 'text-xl font-semibold'}`}>{value}</p>
      {note && <p className="t-caption mt-0.5">{note}</p>}
    </div>
  )
}
