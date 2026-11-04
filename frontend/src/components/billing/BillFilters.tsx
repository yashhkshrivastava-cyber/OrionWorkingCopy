import { useMemo } from 'react'
import { X } from 'lucide-react'
import type { BillCase } from '../../types'
import { SearchSelect } from '../ui/SearchSelect'

export type BillFilter = { client: string; caseCode: string; month: string }
export const NO_FILTER: BillFilter = { client: '', caseCode: '', month: '' }

const monthValue = (offset: number) => {
  const now = new Date()
  const at = new Date(now.getFullYear(), now.getMonth() + offset, 1)
  return `${at.getFullYear()}-${String(at.getMonth() + 1).padStart(2, '0')}`
}

/**
 * Finding bills by who they are for and when: a client, a case, and the month a bill is for. Choosing a client narrows the cases to its own; a case also
 * sets its client. These ask the server (every year, not only the one on screen), the search box beside them filters what came back.
 */
export function BillFilters({ cases, value, onChange }: { cases: BillCase[]; value: BillFilter; onChange: (next: BillFilter) => void }) {
  const clients = useMemo(() => {
    const seen = new Map<string, string>()
    for (const c of cases) if (c.client_code && !seen.has(c.client_code)) seen.set(c.client_code, c.client_name ?? c.client_code)
    return [...seen].map(([id, label]) => ({ id, label })).sort((a, b) => a.label.localeCompare(b.label))
  }, [cases])
  const caseOptions = useMemo(
    () =>
      cases
        .filter((c) => !value.client || c.client_code === value.client)
        .map((c) => ({ id: c.case_code, label: c.case_name }))
        .sort((a, b) => a.label.localeCompare(b.label)),
    [cases, value.client],
  )
  const any = Boolean(value.client || value.caseCode || value.month)

  const pickCase = (code: string | null) => {
    const found = cases.find((c) => c.case_code === code)
    onChange({ ...value, caseCode: code ?? '', client: found?.client_code ?? value.client })
  }
  const pickClient = (code: string | null) => {
    // A case that belongs to another client no longer fits.
    const keep = value.caseCode && cases.find((c) => c.case_code === value.caseCode)?.client_code === (code ?? '') ? value.caseCode : ''
    onChange({ ...value, client: code ?? '', caseCode: keep })
  }

  return (
    <div className="flex flex-wrap items-end gap-3" role="group" aria-label="Find bills by client, case or month">
      <label className="block min-w-[13rem] flex-1 sm:max-w-xs">
        <span className="eyebrow mb-1 block">Client</span>
        <SearchSelect value={value.client} options={clients} onChange={pickClient} placeholder="Any client" emptyLabel="Any client" />
      </label>
      <label className="block min-w-[13rem] flex-1 sm:max-w-sm">
        <span className="eyebrow mb-1 block">Case</span>
        <SearchSelect value={value.caseCode} options={caseOptions} onChange={pickCase} placeholder="Any case" emptyLabel="Any case" />
      </label>
      <div>
        <span className="eyebrow mb-1 block">Bill is for the month</span>
        <div className="flex items-center gap-1.5">
          <input
            type="month"
            aria-label="Month the bill is for"
            value={value.month}
            onChange={(event) => onChange({ ...value, month: event.target.value })}
            className="h-10 rounded-lg border border-[color:var(--color-border-strong)] bg-surface px-3 text-sm"
          />
          {[
            ['This month', 0],
            ['Last month', -1],
          ].map(([label, offset]) => (
            <button
              key={label}
              type="button"
              onClick={() => onChange({ ...value, month: monthValue(Number(offset)) })}
              aria-pressed={value.month === monthValue(Number(offset))}
              className={`interactive rounded-full border px-3 py-1.5 text-xs font-semibold ${value.month === monthValue(Number(offset)) ? 'border-transparent bg-primary text-on-primary' : 'border-[color:var(--color-border)] text-[color:var(--color-text-muted)] hover:bg-muted'}`}
            >
              {label}
            </button>
          ))}
        </div>
      </div>
      {any && (
        <button type="button" onClick={() => onChange(NO_FILTER)} className="interactive mb-0.5 inline-flex items-center gap-1.5 rounded-full px-3 py-2 text-sm font-semibold text-accent hover:bg-accent-dim">
          <X className="h-4 w-4" aria-hidden="true" /> Clear
        </button>
      )}
    </div>
  )
}
