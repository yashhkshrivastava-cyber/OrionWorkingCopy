import { useEffect, useMemo, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { CalendarCheck, Pencil, Plus, Search } from 'lucide-react'
import { attendanceApi } from '../../api/client'
import { monthName } from '../../attendance/attendanceCalc'
import { money } from '../../bank/format'
import { WorkerModal } from '../../components/attendance/AttendanceModals'
import { MonthHeading, RegisterCard, WorkerCard } from '../../components/attendance/lumenAttendance'
import { StatTile } from '../../components/billing/StatTile'
import { Alert, Badge } from '../../components/ui/Alert'
import { Button } from '../../components/ui/Button'
import { LoadingState } from '../../components/ui/DataTable'
import { EmptyState } from '../../components/ui/EmptyState'
import { Input, Select } from '../../components/ui/Field'
import { Tabs } from '../../components/ui/Tabs'
import { useAuth } from '../../context/AuthContext'
import { useLumen } from '../../lumen/useLumen'
import { timeAgo } from '../../formatTime'
import type { AttendanceSheetSummary, AttendanceWorker } from '../../types'

type Tab = 'registers' | 'people'

/**
 * Attendance: a register for each case and month, the people who worked, and the pay that follows. The registers are listed here; each is opened to fill in or to see what
 * it entered. People who work at a case but are not employees are kept on the People tab, so the next register finds them.
 */
export function AttendancePage() {
  const navigate = useNavigate()
  const { user } = useAuth()
  const canWrite = Boolean(user?.can_attendance_write)
  const [tab, setTab] = useState<Tab>('registers')

  return (
    <div className="space-y-5">
      <header className="flex flex-wrap items-end justify-between gap-3">
        <div className="min-w-0">
          <p className="eyebrow mb-1">Utilities</p>
          <h1 className="t-h1">Attendance</h1>
          <p className="t-small mt-1 max-w-2xl text-[color:var(--color-text-muted)]">
            Who worked at each case in a month. Posting a register enters the pay: a salary line for each employee, an expense for everyone else. Paying stays in Bank.
          </p>
        </div>
        {canWrite && (
          <Button onClick={() => navigate('/attendance/new')}>
            <Plus className="h-4 w-4" /> New register
          </Button>
        )}
      </header>

      <Tabs<Tab>
        label="Attendance"
        tabs={[
          { id: 'registers', label: 'Registers' },
          { id: 'people', label: 'People who are not employees' },
        ]}
        active={tab}
        onChange={setTab}
      />

      {tab === 'registers' ? <Registers /> : <People canWrite={canWrite} />}
    </div>
  )
}

function Registers() {
  const navigate = useNavigate()
  const lumen = useLumen()
  const [month, setMonth] = useState('')
  const [state, setState] = useState('')
  const [typed, setTyped] = useState('')
  const [q, setQ] = useState('')
  const [sheets, setSheets] = useState<AttendanceSheetSummary[] | null>(null)
  const [error, setError] = useState('')

  useEffect(() => {
    const timer = window.setTimeout(() => setQ(typed.trim()), 250)
    return () => window.clearTimeout(timer)
  }, [typed])

  useEffect(() => {
    let live = true
    attendanceApi
      .sheets({ month, status: state, q })
      .then((r) => live && (setSheets(r.sheets), setError('')))
      .catch((e: Error) => live && setError(e.message))
    return () => {
      live = false
    }
  }, [month, state, q])

  const owed = useMemo(() => sheets?.reduce((sum, s) => sum + Number(s.amount), 0) ?? 0, [sheets])
  const drafts = useMemo(() => sheets?.filter((s) => s.status === 'Draft') ?? [], [sheets])
  // Lumen groups the registers under their month, newest first.
  const months = useMemo(() => {
    const groups = new Map<string, AttendanceSheetSummary[]>()
    for (const sheet of sheets ?? []) groups.set(sheet.month_year, [...(groups.get(sheet.month_year) ?? []), sheet])
    return [...groups.entries()].sort((a, b) => b[0].localeCompare(a[0]))
  }, [sheets])

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-2">
        <div className="relative min-w-[14rem] flex-1 sm:max-w-xs">
          <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-[color:var(--color-text-faint)]" aria-hidden="true" />
          <Input className="pl-9" value={typed} onChange={(e) => setTyped(e.target.value)} placeholder="Find a case, client or register" aria-label="Find a register" />
        </div>
        <div className="w-44">
          <Input type="month" value={month} onChange={(e) => setMonth(e.target.value)} aria-label="Month" />
        </div>
        <div className="w-40">
          <Select value={state} onChange={(e) => setState(e.target.value)} aria-label="Status">
            <option value="">Any status</option>
            <option>Draft</option>
            <option>Posted</option>
          </Select>
        </div>
        {(month || state || typed) && (
          <Button variant="ghost" onClick={() => { setMonth(''); setState(''); setTyped('') }}>
            Clear
          </Button>
        )}
      </div>

      {error && <Alert variant="error">{error}</Alert>}
      {!sheets && !error && <LoadingState message="Reading the registers…" />}

      {sheets && sheets.length === 0 && (
        <EmptyState compact title="No registers yet">
          Make one with “New register”: choose a case and a month, and its employees are listed for you.
        </EmptyState>
      )}

      {lumen && sheets && sheets.length > 0 && (
        <>
          <div className="grid grid-cols-2 gap-3 xl:grid-cols-4">
            <StatTile label="Registers" text={String(sheets.length)} hint={`${new Set(sheets.map((s) => s.case_code)).size} cases`} />
            <StatTile label="Still drafts" text={String(drafts.length)} hint={drafts.length ? 'Nothing entered until posted' : 'Everything is posted'} tone={drafts.length ? 'text-warning' : 'text-positive'} />
            <StatTile label="Posted" text={String(sheets.length - drafts.length)} hint="Pay entered in Bank" tone="text-positive" />
            <StatTile label="Comes to" text={money(owed)} hint="All registers shown" />
          </div>
          <div className="space-y-5">
            {months.map(([month, group]) => (
              <section key={month} aria-label={monthName(month)}>
                <MonthHeading month={month} count={group.length} amount={group.reduce((sum, s) => sum + Number(s.amount), 0)} />
                <ul className="space-y-2">
                  {group.map((s) => (
                    <RegisterCard key={s.sheet_code} sheet={s} onOpen={() => navigate(`/attendance/${s.sheet_code}`)} />
                  ))}
                </ul>
              </section>
            ))}
          </div>
        </>
      )}

      {!lumen && sheets && sheets.length > 0 && (
        <section className="panel overflow-x-auto" aria-label="Registers">
          <table className="w-full min-w-[44rem] text-sm">
            <caption className="sr-only">Attendance registers</caption>
            <thead>
              <tr className="border-b border-[color:var(--color-border)] text-left text-xs text-[color:var(--color-text-muted)]">
                <th scope="col" className="px-4 py-2.5 font-medium">Month</th>
                <th scope="col" className="px-2 py-2.5 font-medium">Case</th>
                <th scope="col" className="px-2 py-2.5 text-right font-medium">People</th>
                <th scope="col" className="px-2 py-2.5 text-right font-medium">Amount</th>
                <th scope="col" className="px-2 py-2.5 font-medium">Status</th>
                <th scope="col" className="px-4 py-2.5 font-medium">Changed</th>
              </tr>
            </thead>
            <tbody>
              {sheets.map((s) => (
                <tr
                  key={s.sheet_code}
                  tabIndex={0}
                  onClick={() => navigate(`/attendance/${s.sheet_code}`)}
                  onKeyDown={(e) => e.key === 'Enter' && navigate(`/attendance/${s.sheet_code}`)}
                  className="cursor-pointer border-b border-[color:var(--color-border)]/60 hover:bg-muted/50 focus-visible:bg-muted/50 focus-visible:outline-none"
                >
                  <td className="whitespace-nowrap px-4 py-2.5 font-medium">
                    {monthName(s.month_year)}
                    <span className="t-caption block">{s.sheet_code}</span>
                  </td>
                  <td className="px-2 py-2.5">
                    {s.case_name}
                    {s.client_name && <span className="t-caption block">{s.client_name}</span>}
                  </td>
                  <td className="whitespace-nowrap px-2 py-2.5 text-right tabular-nums">
                    {s.people}
                    <span className="t-caption block">{s.employees} employees, {s.workers} others</span>
                  </td>
                  <td className="whitespace-nowrap px-2 py-2.5 text-right font-medium tabular-nums">{money(Number(s.amount))}</td>
                  <td className="px-2 py-2.5">
                    <Badge variant={s.status === 'Posted' ? 'emerald' : 'amber'}>{s.status}</Badge>
                  </td>
                  <td className="whitespace-nowrap px-4 py-2.5 text-xs text-[color:var(--color-text-muted)]">{timeAgo(s.posted_timestamp ?? s.last_updated_timestamp)}</td>
                </tr>
              ))}
            </tbody>
            <tfoot>
              <tr>
                <td className="px-4 py-2.5 text-xs text-[color:var(--color-text-muted)]" colSpan={3}>
                  <CalendarCheck className="mr-1 inline h-3.5 w-3.5" aria-hidden="true" />
                  {sheets.length} register{sheets.length === 1 ? '' : 's'} shown
                </td>
                <td className="whitespace-nowrap px-2 py-2.5 text-right text-xs font-semibold tabular-nums">{money(owed)}</td>
                <td colSpan={2} />
              </tr>
            </tfoot>
          </table>
        </section>
      )}
    </div>
  )
}

function People({ canWrite }: { canWrite: boolean }) {
  const lumen = useLumen()
  const [typed, setTyped] = useState('')
  const [q, setQ] = useState('')
  const [status, setStatus] = useState('Active')
  const [people, setPeople] = useState<AttendanceWorker[] | null>(null)
  const [error, setError] = useState('')
  const [editing, setEditing] = useState<AttendanceWorker | 'new' | null>(null)
  const [reload, setReload] = useState(0)

  useEffect(() => {
    const timer = window.setTimeout(() => setQ(typed.trim()), 250)
    return () => window.clearTimeout(timer)
  }, [typed])

  useEffect(() => {
    let live = true
    attendanceApi
      .workers(q, status)
      .then((r) => live && (setPeople(r.workers), setError('')))
      .catch((e: Error) => live && setError(e.message))
    return () => {
      live = false
    }
  }, [q, status, reload])

  return (
    <div className="space-y-4">
      <p className="text-sm text-[color:var(--color-text-muted)]">
        People who work at a case but are not employees. They are not in the employee list; they are saved here so the next register finds them, and their pay is entered as an expense.
      </p>
      <div className="flex flex-wrap items-center gap-2">
        <div className="relative min-w-[14rem] flex-1 sm:max-w-xs">
          <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-[color:var(--color-text-faint)]" aria-hidden="true" />
          <Input className="pl-9" value={typed} onChange={(e) => setTyped(e.target.value)} placeholder="Find by name or phone" aria-label="Find a person" />
        </div>
        <div className="w-40">
          <Select value={status} onChange={(e) => setStatus(e.target.value)} aria-label="Status">
            <option>Active</option>
            <option>Inactive</option>
            <option value="">Everyone</option>
          </Select>
        </div>
        {canWrite && (
          <Button variant="secondary" onClick={() => setEditing('new')}>
            <Plus className="h-4 w-4" /> Add a person
          </Button>
        )}
      </div>
      {error && <Alert variant="error">{error}</Alert>}
      {!people && !error && <LoadingState message="Reading the people…" />}
      {people && people.length === 0 && (
        <EmptyState compact title="Nobody saved yet">
          People you add to a register who are not employees are kept here. You can also add one now.
        </EmptyState>
      )}
      {lumen && people && people.length > 0 && (
        <ul className="grid gap-3 md:grid-cols-2 2xl:grid-cols-3" aria-label="People">
          {people.map((p) => (
            <WorkerCard key={p.worker_code} person={p} canWrite={canWrite} onChange={() => setEditing(p)} />
          ))}
        </ul>
      )}
      {!lumen && people && people.length > 0 && (
        <section className="panel overflow-x-auto" aria-label="People">
          <table className="w-full min-w-[40rem] text-sm">
            <caption className="sr-only">People who are not employees</caption>
            <thead>
              <tr className="border-b border-[color:var(--color-border)] text-left text-xs text-[color:var(--color-text-muted)]">
                <th scope="col" className="px-4 py-2.5 font-medium">Name</th>
                <th scope="col" className="px-2 py-2.5 font-medium">Phone</th>
                <th scope="col" className="px-2 py-2.5 font-medium">Work</th>
                <th scope="col" className="px-2 py-2.5 text-right font-medium">Pay for a day</th>
                <th scope="col" className="px-2 py-2.5 font-medium">Usually at</th>
                <th scope="col" className="px-2 py-2.5 text-right font-medium">Registers</th>
                <th scope="col" className="px-4 py-2.5"><span className="sr-only">Actions</span></th>
              </tr>
            </thead>
            <tbody>
              {people.map((p) => (
                <tr key={p.worker_code} className="border-b border-[color:var(--color-border)]/60 hover:bg-muted/40">
                  <td className="px-4 py-2.5 font-medium">
                    {p.name}
                    <span className="t-caption ml-2">{p.worker_code}</span>
                    {p.status === 'Inactive' && <span className="ml-2"><Badge>Inactive</Badge></span>}
                  </td>
                  <td className="whitespace-nowrap px-2 py-2.5">{p.phone ?? '—'}</td>
                  <td className="px-2 py-2.5">{p.designation ?? '—'}</td>
                  <td className="whitespace-nowrap px-2 py-2.5 text-right tabular-nums">{p.rate_per_day ? money(Number(p.rate_per_day)) : '—'}</td>
                  <td className="px-2 py-2.5">{p.case_name ?? '—'}</td>
                  <td className="whitespace-nowrap px-2 py-2.5 text-right tabular-nums">{p.registers}</td>
                  <td className="whitespace-nowrap px-4 py-2.5 text-right">
                    {canWrite && (
                      <Button size="sm" variant="ghost" onClick={() => setEditing(p)}>
                        <Pencil className="h-3.5 w-3.5" /> Change
                      </Button>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </section>
      )}
      {editing && (
        <WorkerModal
          worker={editing === 'new' ? null : editing}
          onClose={() => setEditing(null)}
          onSaved={() => {
            setEditing(null)
            setReload((n) => n + 1)
          }}
        />
      )}
    </div>
  )
}
