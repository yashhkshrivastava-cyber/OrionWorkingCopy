import type { AttendanceLine, AttendanceParsedLine, AttendanceRoster, AttendanceRosterPerson } from '../types'
import { calculatedAmount } from './attendanceCalc'

/** A row of the register as the screen edits it. Numbers are kept as the text typed, so nothing is rounded under the person's fingers. */
export interface Row {
  key: string
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
  /** The amount was typed, not worked out from the figures. */
  amount_set: boolean
  remarks: string
  warnings: string[]
  /** Counted in the register. An employee of the case starts counted; leaving one out is not deleting them. */
  included: boolean
  /** Listed because the person belongs to the case (an employee of it, or a saved person who has worked there), so they are left out, not removed. */
  from_roster: boolean
  salary_code?: string | null
  expense_code?: string | null
  paid?: boolean
}

/** "500.0000" -> "500", "596.7742" -> "596.7742": what the server keeps to four decimals, without the zeros it pads with. */
export const tidy = (value: string | number | null | undefined): string => {
  if (value === null || value === undefined || value === '') return ''
  const number = Number(value)
  return Number.isFinite(number) ? String(number) : String(value)
}

export const figure = (row: Row): string => calculatedAmount(row.rate_per_day, row.days_present, row.extra_amount, row.deduction_amount)

/** A row after one of its figures changed: the amount follows the figures unless the person typed an amount of their own. */
export function withFigure(row: Row, change: Partial<Row>): Row {
  const next = { ...row, ...change }
  return next.amount_set ? next : { ...next, amount: figure(next) }
}

export function rowFromEmployee(person: AttendanceRosterPerson, fromRoster: boolean): Row {
  return withFigure(
    {
      key: `e:${person.employee_code}`, employee_code: person.employee_code ?? null, worker_code: null, new_worker: null, name: person.name, designation: person.designation ?? '',
      days_present: '', rate_per_day: Number(person.rate_per_day) > 0 ? tidy(person.rate_per_day) : '', extra_amount: '', deduction_amount: '', amount: '0.00', amount_set: false,
      remarks: '', warnings: [], included: true, from_roster: fromRoster,
    },
    {},
  )
}

export function rowFromWorker(person: AttendanceRosterPerson, fromRoster: boolean): Row {
  return withFigure(
    {
      key: `w:${person.worker_code}`, employee_code: null, worker_code: person.worker_code ?? null, new_worker: null, name: person.name, designation: person.designation ?? '',
      days_present: '', rate_per_day: Number(person.rate_per_day) > 0 ? tidy(person.rate_per_day) : '', extra_amount: '', deduction_amount: '', amount: '0.00', amount_set: false,
      remarks: '', warnings: [], included: true, from_roster: fromRoster,
    },
    {},
  )
}

export function rowFromNewPerson(input: { name: string; phone: string; designation: string; rate: string }): Row {
  return withFigure(
    {
      key: `n:${input.name.toLowerCase()}|${input.phone}`, employee_code: null, worker_code: null,
      new_worker: { name: input.name, phone: input.phone || null, designation: input.designation || null }, name: input.name, designation: input.designation,
      days_present: '', rate_per_day: tidy(input.rate), extra_amount: '', deduction_amount: '', amount: '0.00', amount_set: false, remarks: '', warnings: [], included: true,
      from_roster: false,
    },
    {},
  )
}

/** The rows of a new register: everyone the case has (its employees, and the saved people who have worked there). */
export function rowsFromRoster(roster: AttendanceRoster): Row[] {
  return [...roster.employees.map((p) => rowFromEmployee(p, true)), ...roster.workers.map((p) => ({ ...rowFromWorker(p, true), included: false }))]
}

/** A saved register's lines as rows. Its employees who were left out show again, not counted, so they can be put back. */
export function rowsFromSheet(lines: AttendanceLine[], roster: AttendanceRoster | null): Row[] {
  const rows: Row[] = lines.map((l) => ({
    key: l.employee_code ? `e:${l.employee_code}` : `w:${l.worker_code}`, employee_code: l.employee_code, worker_code: l.worker_code, new_worker: null, name: l.name,
    designation: l.designation ?? '', days_present: tidy(l.days_present), rate_per_day: tidy(l.rate_per_day), extra_amount: tidy(l.extra_amount) === '0' ? '' : tidy(l.extra_amount),
    deduction_amount: tidy(l.deduction_amount) === '0' ? '' : tidy(l.deduction_amount), amount: l.amount, amount_set: Number(l.amount) !== Number(l.calculated), remarks: l.remarks ?? '',
    warnings: l.warnings, included: true, from_roster: false, salary_code: l.salary_code, expense_code: l.expense_code, paid: l.paid,
  }))
  if (roster) {
    const have = new Set(rows.map((r) => r.key))
    for (const p of roster.employees) if (!have.has(`e:${p.employee_code}`)) rows.push({ ...rowFromEmployee(p, true), included: false })
    for (const p of roster.workers) if (!have.has(`w:${p.worker_code}`)) rows.push({ ...rowFromWorker(p, true), included: false })
    for (const row of rows) row.from_roster = row.from_roster || Boolean(roster.employees.some((p) => `e:${p.employee_code}` === row.key) || roster.workers.some((p) => `w:${p.worker_code}` === row.key))
  }
  return rows
}

/** The line as the server takes it. The amount is sent only when the person typed one; otherwise the server works it out. */
export function payloadOf(row: Row): Record<string, unknown> {
  return {
    employee_code: row.employee_code, worker_code: row.worker_code, new_worker: row.new_worker, days_present: row.days_present || '0', rate_per_day: row.rate_per_day || '0',
    extra_amount: row.extra_amount || '0', deduction_amount: row.deduction_amount || '0', amount: row.amount_set ? row.amount || '0' : null, remarks: row.remarks || null,
  }
}

/** Last month's days, rate, extra and deduction put on this month's rows (and the people who were there last month and are not here yet added). */
export function copyPrevious(rows: Row[], previous: NonNullable<AttendanceRoster['previous']>, roster: AttendanceRoster): Row[] {
  const out = rows.map((r) => ({ ...r }))
  for (const line of previous.lines) {
    const key = line.employee_code ? `e:${line.employee_code}` : `w:${line.worker_code}`
    let row = out.find((r) => r.key === key)
    if (!row) {
      const person = line.employee_code ? roster.employees.find((p) => p.employee_code === line.employee_code) : roster.workers.find((p) => p.worker_code === line.worker_code)
      if (!person) continue
      row = line.employee_code ? rowFromEmployee(person, true) : rowFromWorker(person, true)
      out.push(row)
    }
    const index = out.indexOf(row)
    out[index] = withFigure(
      { ...row, included: true },
      {
        days_present: tidy(line.days_present),
        // An employee's day's pay follows this month's length, so it is the salary's, not last month's; a saved person's rate is as it was.
        rate_per_day: row.employee_code && Number(row.rate_per_day) > 0 ? row.rate_per_day : tidy(line.rate_per_day),
        extra_amount: Number(line.extra_amount) ? tidy(line.extra_amount) : '',
        deduction_amount: Number(line.deduction_amount) ? tidy(line.deduction_amount) : '',
      },
    )
  }
  return out
}

/** Lines read from an uploaded workbook put on the register: the person already on it is updated and counted, a new one is added. */
export function applyUpload(rows: Row[], parsed: AttendanceParsedLine[]): Row[] {
  const out = rows.map((r) => ({ ...r }))
  for (const line of parsed) {
    const key = line.employee_code ? `e:${line.employee_code}` : line.worker_code ? `w:${line.worker_code}` : `n:${line.name.toLowerCase()}|${line.new_worker?.phone ?? ''}`
    const typed = Number(line.amount) !== Number(line.calculated)
    const values = {
      days_present: tidy(line.days_present), rate_per_day: tidy(line.rate_per_day), extra_amount: Number(line.extra_amount) ? tidy(line.extra_amount) : '',
      deduction_amount: Number(line.deduction_amount) ? tidy(line.deduction_amount) : '', amount: line.amount, amount_set: typed, remarks: line.remarks, included: true,
    }
    const at = out.findIndex((r) => r.key === key)
    if (at >= 0) {
      out[at] = withFigure({ ...out[at], ...values }, {})
    } else {
      out.push(
        withFigure(
          {
            key, employee_code: line.employee_code, worker_code: line.worker_code, new_worker: line.new_worker, name: line.name, designation: line.designation, warnings: [],
            from_roster: false, ...values,
          },
          {},
        ),
      )
    }
  }
  return out
}

export const counted = (rows: Row[]): Row[] => rows.filter((r) => r.included)

export const totalOf = (rows: Row[]): number => Math.round(counted(rows).reduce((sum, r) => sum + Number(r.amount || 0) * 100, 0)) / 100
