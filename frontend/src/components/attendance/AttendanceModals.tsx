import { useEffect, useRef, useState } from 'react'
import { Check, Search } from 'lucide-react'
import { ApiError, attendanceApi } from '../../api/client'
import { newIdempotencyKey } from '../../api/idempotency'
import { monthName } from '../../attendance/attendanceCalc'
import { rowFromEmployee, rowFromNewPerson, rowFromWorker, type Row } from '../../attendance/attendanceDraft'
import { money } from '../../bank/format'
import type { AttendanceCase, AttendanceRosterPerson, AttendanceWorker } from '../../types'
import { Alert } from '../ui/Alert'
import { Button } from '../ui/Button'
import { Checkbox, Field, Input, Select, Textarea } from '../ui/Field'
import { Modal } from '../ui/Modal'
import { MoneyInput } from '../ui/MoneyInput'
import { SearchSelect } from '../ui/SearchSelect'
import { Segmented } from '../ui/Segmented'

/** Adds people to a register: an employee (any, not only the case's), someone saved before, or a new person who is saved with the register. */
export function AddPersonModal({
  month,
  have,
  onAdd,
  onClose,
}: {
  month: string
  /** The keys of the rows already on the register. */
  have: Set<string>
  onAdd: (row: Row) => void
  onClose: () => void
}) {
  const [mode, setMode] = useState<'employee' | 'worker' | 'new'>('employee')
  const [typed, setTyped] = useState('')
  const [found, setFound] = useState<{ employees: AttendanceRosterPerson[]; workers: AttendanceRosterPerson[] } | null>(null)
  const [error, setError] = useState('')
  const [added, setAdded] = useState<Set<string>>(new Set())
  const [person, setPerson] = useState({ name: '', phone: '', designation: '', rate: '' })

  useEffect(() => {
    if (mode === 'new') return
    if (typed.trim().length < 2) {
      setFound(null)
      return
    }
    let live = true
    const timer = window.setTimeout(() => {
      attendanceApi
        .people(typed.trim(), month)
        .then((r) => live && (setFound(r), setError('')))
        .catch((e: Error) => live && setError(e.message))
    }, 250)
    return () => {
      live = false
      window.clearTimeout(timer)
    }
  }, [typed, mode, month])

  const list = mode === 'employee' ? (found?.employees ?? []) : (found?.workers ?? [])
  const keyOf = (p: AttendanceRosterPerson) => (mode === 'employee' ? `e:${p.employee_code}` : `w:${p.worker_code}`)
  const add = (p: AttendanceRosterPerson) => {
    onAdd(mode === 'employee' ? rowFromEmployee(p, false) : rowFromWorker(p, false))
    setAdded((current) => new Set(current).add(keyOf(p)))
  }
  const newKey = `n:${person.name.trim().toLowerCase()}|${person.phone.trim()}`
  const canAddNew = person.name.trim().length > 1 && !have.has(newKey) && !added.has(newKey)

  return (
    <Modal
      open
      title="Add people"
      onClose={onClose}
      footer={
        <Button variant="secondary" onClick={onClose}>
          Done
        </Button>
      }
    >
      <div className="space-y-4">
        <Segmented
          label="Who to add"
          value={mode}
          onChange={(next) => {
            setMode(next)
            setTyped('')
            setFound(null)
          }}
          options={[
            { id: 'employee', label: 'An employee' },
            { id: 'worker', label: 'A saved person' },
            { id: 'new', label: 'A new person' },
          ]}
        />
        {error && <Alert variant="error">{error}</Alert>}

        {mode !== 'new' && (
          <>
            <div className="relative">
              <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-[color:var(--color-text-faint)]" aria-hidden="true" />
              <Input
                autoFocus
                className="pl-9"
                placeholder={mode === 'employee' ? 'Type a name or code (two letters or more)' : 'Type a name or phone number'}
                value={typed}
                onChange={(e) => setTyped(e.target.value)}
                aria-label="Search people"
              />
            </div>
            <ul className="max-h-72 divide-y divide-[color:var(--color-border)] overflow-y-auto rounded-lg border border-[color:var(--color-border)]">
              {typed.trim().length < 2 && <li className="px-3 py-4 text-sm text-[color:var(--color-text-muted)]">{mode === 'employee' ? 'Any active employee can be added, whichever case they belong to.' : 'People saved from earlier registers, who are not employees.'}</li>}
              {typed.trim().length >= 2 && found && list.length === 0 && <li className="px-3 py-4 text-sm text-[color:var(--color-text-muted)]">Nobody found.{mode === 'worker' ? ' Add them as a new person.' : ''}</li>}
              {list.map((p) => {
                const key = keyOf(p)
                const there = have.has(key) || added.has(key)
                return (
                  <li key={key} className="flex items-center gap-3 px-3 py-2">
                    <div className="min-w-0 flex-1">
                      <p className="truncate text-sm font-medium">{p.name}</p>
                      <p className="t-caption truncate">
                        {[p.employee_code ?? p.worker_code, p.designation, p.case_name, p.phone].filter(Boolean).join(' · ')}
                      </p>
                    </div>
                    {there ? (
                      <span className="inline-flex items-center gap-1 text-xs text-positive">
                        <Check className="h-3.5 w-3.5" aria-hidden="true" /> On the register
                      </span>
                    ) : (
                      <Button size="sm" variant="secondary" onClick={() => add(p)}>
                        Add
                      </Button>
                    )}
                  </li>
                )
              })}
            </ul>
          </>
        )}

        {mode === 'new' && (
          <div className="space-y-4">
            <p className="text-sm text-[color:var(--color-text-muted)]">
              For someone who works here but is not an employee. They are saved with the register so the next one finds them, and are paid as an expense.
            </p>
            <div className="grid gap-4 sm:grid-cols-2">
              <Field label="Name" required className="sm:col-span-2">
                <Input autoFocus value={person.name} maxLength={100} onChange={(e) => setPerson({ ...person, name: e.target.value })} />
              </Field>
              <Field label="Phone">
                <Input value={person.phone} maxLength={20} inputMode="tel" onChange={(e) => setPerson({ ...person, phone: e.target.value })} />
              </Field>
              <Field label="Work they do">
                <Input value={person.designation} maxLength={60} placeholder="For example Helper" onChange={(e) => setPerson({ ...person, designation: e.target.value })} />
              </Field>
              <Field label="Pay for a day">
                <MoneyInput value={person.rate} decimals={4} words={false} onChange={(rate) => setPerson({ ...person, rate })} />
              </Field>
            </div>
            <Button
              disabled={!canAddNew}
              onClick={() => {
                onAdd(rowFromNewPerson(person))
                setAdded((current) => new Set(current).add(newKey))
                setPerson({ name: '', phone: '', designation: '', rate: '' })
              }}
            >
              Add to the register
            </Button>
          </div>
        )}
      </div>
    </Modal>
  )
}

/** What posting will enter, shown before it is entered: salary lines for employees (paid in Bank > Payroll), expenses for the others (paid in Bank > Payables). */
export function PostModal({
  monthYear,
  caseName,
  employees,
  workers,
  employeeAmount,
  workerAmount,
  expenseTypes,
  expenseType,
  onExpenseType,
  onClose,
  onConfirm,
}: {
  monthYear: string
  caseName: string
  employees: number
  workers: number
  employeeAmount: number
  workerAmount: number
  expenseTypes: { code: string; name: string }[]
  expenseType: string
  onExpenseType: (code: string) => void
  onClose: () => void
  /** Saves and posts. Resolves with a message to show when it did not work. */
  onConfirm: (key: string) => Promise<string | null>
}) {
  const [sure, setSure] = useState(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const key = useRef(newIdempotencyKey())
  const working = useRef(false)
  const needsType = workers > 0 && !expenseType
  const ready = sure && !needsType

  const confirm = async () => {
    if (working.current || !ready) return
    working.current = true
    setBusy(true)
    setError('')
    const problem = await onConfirm(key.current)
    if (problem) {
      setError(problem)
      working.current = false
      setBusy(false)
    }
  }

  return (
    <Modal
      open
      title={`Post attendance for ${monthName(monthYear)}`}
      onClose={onClose}
      footer={
        <>
          <Button variant="ghost" onClick={onClose} disabled={busy}>
            Cancel
          </Button>
          <Button onClick={confirm} loading={busy} disabled={!ready}>
            Post {money(employeeAmount + workerAmount)}
          </Button>
        </>
      }
    >
      <div className="space-y-4">
        <p className="text-sm">
          This enters the pay for <span className="font-semibold">{caseName}</span>. Nothing is paid yet: paying stays in Bank.
        </p>
        <dl className="grid gap-3 sm:grid-cols-2">
          <div className="panel p-3">
            <dt className="t-caption">Employees</dt>
            <dd className="mt-0.5 text-lg font-semibold tabular-nums">{money(employeeAmount)}</dd>
            <dd className="t-caption">
              {employees} salary line{employees === 1 ? '' : 's'}, paid in Bank &gt; Payroll
            </dd>
          </div>
          <div className="panel p-3">
            <dt className="t-caption">Other people</dt>
            <dd className="mt-0.5 text-lg font-semibold tabular-nums">{money(workerAmount)}</dd>
            <dd className="t-caption">
              {workers} expense{workers === 1 ? '' : 's'}, paid in Bank &gt; Payables
            </dd>
          </div>
        </dl>
        {workers > 0 && (
          <Field label="Enter the other people's pay as" required hint={expenseTypes.length ? 'The expense type their pay is entered under, for example Casual wages.' : 'There are no expense types yet. Add one in Operational Data, Expense Type, then come back.'}>
            <Select value={expenseType} onChange={(e) => onExpenseType(e.target.value)}>
              <option value="">Choose…</option>
              {expenseTypes.map((t) => (
                <option key={t.code} value={t.code}>
                  {t.name}
                </option>
              ))}
            </Select>
          </Field>
        )}
        <p className="text-sm text-[color:var(--color-text-muted)]">
          Once posted the register cannot be changed. It can be reopened until any of it has been paid, which takes these entries back.
        </p>
        <Checkbox label="I have checked the days and amounts, and want to post this register" checked={sure} onChange={setSure} />
        {error && <Alert variant="error">{error}</Alert>}
      </div>
    </Modal>
  )
}

export function ReopenModal({ code, onClose, onDone, onConflict }: { code: string; onClose: () => void; onDone: () => void; onConflict: (message: string) => void }) {
  const [reason, setReason] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')

  const go = async () => {
    setBusy(true)
    setError('')
    try {
      await attendanceApi.reopen(code, reason)
      onDone()
    } catch (e) {
      if (e instanceof ApiError && e.status === 409) {
        onConflict(e.message)
        return
      }
      setError(e instanceof Error ? e.message : 'That did not work. Try again.')
      setBusy(false)
    }
  }

  return (
    <Modal
      open
      title="Reopen this register"
      onClose={onClose}
      footer={
        <>
          <Button variant="ghost" onClick={onClose} disabled={busy}>
            Cancel
          </Button>
          <Button variant="danger" onClick={go} loading={busy} disabled={reason.trim().length < 5}>
            Reopen
          </Button>
        </>
      }
    >
      <div className="space-y-4">
        <p className="text-sm">
          The salary lines and expenses this register entered are taken back, and the register can be changed and posted again. This is possible only while none of it has been paid.
        </p>
        <Field label="Why is it being reopened?" required>
          <Textarea rows={3} maxLength={300} value={reason} onChange={(e) => setReason(e.target.value)} placeholder="For example, two people's days were wrong" />
        </Field>
        {error && <Alert variant="error">{error}</Alert>}
      </div>
    </Modal>
  )
}

/** Adds or changes a person who is not an employee (the People tab). */
export function WorkerModal({ worker, onClose, onSaved }: { worker: AttendanceWorker | null; onClose: () => void; onSaved: () => void }) {
  const [cases, setCases] = useState<AttendanceCase[]>([])
  const [form, setForm] = useState({
    name: worker?.name ?? '',
    phone: worker?.phone ?? '',
    designation: worker?.designation ?? '',
    rate: worker?.rate_per_day ? String(Number(worker.rate_per_day)) : '',
    case_code: worker?.case_code ?? '',
    status: worker?.status ?? 'Active',
  })
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')

  useEffect(() => {
    attendanceApi.cases('').then((r) => setCases(r.cases)).catch(() => setCases([]))
  }, [])

  const save = async () => {
    setBusy(true)
    setError('')
    const body = { name: form.name, phone: form.phone || null, designation: form.designation || null, rate_per_day: form.rate || null, case_code: form.case_code || null, status: form.status }
    try {
      if (worker) await attendanceApi.updateWorker(worker.worker_code, body)
      else await attendanceApi.createWorker(body)
      onSaved()
    } catch (e) {
      setError(e instanceof Error ? e.message : 'That did not save. Try again.')
      setBusy(false)
    }
  }

  return (
    <Modal
      open
      title={worker ? `Change ${worker.name}` : 'Add a person'}
      onClose={onClose}
      footer={
        <>
          <Button variant="ghost" onClick={onClose} disabled={busy}>
            Cancel
          </Button>
          <Button onClick={save} loading={busy} disabled={form.name.trim().length < 2}>
            Save
          </Button>
        </>
      }
    >
      <div className="grid gap-4 sm:grid-cols-2">
        <Field label="Name" required className="sm:col-span-2">
          <Input autoFocus value={form.name} maxLength={100} onChange={(e) => setForm({ ...form, name: e.target.value })} />
        </Field>
        <Field label="Phone">
          <Input value={form.phone} maxLength={20} inputMode="tel" onChange={(e) => setForm({ ...form, phone: e.target.value })} />
        </Field>
        <Field label="Work they do">
          <Input value={form.designation} maxLength={60} onChange={(e) => setForm({ ...form, designation: e.target.value })} />
        </Field>
        <Field label="Pay for a day">
          <MoneyInput value={form.rate} decimals={4} words={false} onChange={(rate) => setForm({ ...form, rate })} />
        </Field>
        <Field label="Usually works at">
          <SearchSelect
            value={form.case_code}
            options={cases.map((c) => ({ id: c.case_code, label: c.client_name ? `${c.case_name} — ${c.client_name}` : c.case_name }))}
            onChange={(next) => setForm({ ...form, case_code: next ?? '' })}
            placeholder="— No case in particular —"
          />
        </Field>
        {worker && (
          <Field label="Status" hint="An inactive person is not offered on new registers; earlier ones keep them.">
            <Select value={form.status} onChange={(e) => setForm({ ...form, status: e.target.value as 'Active' | 'Inactive' })}>
              <option>Active</option>
              <option>Inactive</option>
            </Select>
          </Field>
        )}
        {error && (
          <div className="sm:col-span-2">
            <Alert variant="error">{error}</Alert>
          </div>
        )}
      </div>
    </Modal>
  )
}
