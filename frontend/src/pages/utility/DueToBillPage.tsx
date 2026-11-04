import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { Copy } from 'lucide-react'
import { api } from '../../api/client'
import { money } from '../../billing/billCalc'
import { formatMonth } from '../../components/billing/BillDocument'
import { Alert } from '../../components/ui/Alert'
import { Button } from '../../components/ui/Button'
import { Field, Input } from '../../components/ui/Field'
import { useAuth } from '../../context/AuthContext'
import { useDataRefresh } from '../../context/DataRefreshContext'
import { BillNumber } from '../../components/billing/BillNumber'
import { LumenDue } from '../../components/billing/LumenDue'
import { useLumen } from '../../lumen/useLumen'
import type { DueCase } from '../../types'

/**
 * Cases that were billed before but have no bill yet for the month being billed. Each one opens
 * the bill editor filled in from the case's last bill, so a month's billing is a matter of
 * checking quantities rather than typing every bill again. Nothing is issued from here.
 */
export function DueToBillPage() {
  const { user } = useAuth()
  const { generation } = useDataRefresh()
  const navigate = useNavigate()
  const lumen = useLumen()
  const canWrite = Boolean(user?.can_billing_write)
  const [month, setMonth] = useState('')
  const [cases, setCases] = useState<DueCase[] | null>(null)
  const [billed, setBilled] = useState<{ cases: number; total: number } | null>(null)
  const [error, setError] = useState('')

  useEffect(() => {
    setCases(null)
    api
      .billsDueFor(month || undefined)
      .then((r) => {
        setCases(r.cases)
        setBilled(r.billed ?? null)
        setMonth((current) => current || r.month)
      })
      .catch((e: Error) => setError(e.message))
  }, [month, generation])

  if (lumen) {
    return (
      <div className="space-y-4">
        {error && <Alert variant="error">{error}</Alert>}
        <LumenDue
          month={month}
          onMonth={setMonth}
          cases={cases}
          billed={billed}
          canWrite={canWrite}
          onCopy={(row) => navigate(`/utility/billing/new?from=${encodeURIComponent(row.id)}&month=${month}`)}
        />
      </div>
    )
  }

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h2 className="t-h2 text-[color:var(--color-text)]">Monthly billing</h2>
          <p className="max-w-2xl text-sm text-[color:var(--color-text-muted)]">
            Cases billed before that have no bill yet for the month below. Copy a case&apos;s last bill, change what
            moved this month, and issue it. Cases not billed in the last six months, and inactive cases, are not listed.
          </p>
        </div>
        <Field label="Bills for the month">
          <Input type="month" value={month} onChange={(e) => setMonth(e.target.value)} className="w-44" />
        </Field>
      </div>

      {error && <Alert variant="error">{error}</Alert>}

      <section className="rounded-xl border border-[color:var(--color-border)] bg-surface">
        <header className="border-b border-[color:var(--color-border)] px-4 py-3">
          <h3 className="t-h3 text-[color:var(--color-text)]">
            {cases === null ? 'Looking…' : `${cases.length} to bill for ${month ? formatMonth(`${month}-01`) : 'this month'}`}
          </h3>
        </header>
        {cases === null ? (
          <div className="shimmer m-4 h-32 rounded-lg bg-muted" aria-busy="true" />
        ) : cases.length === 0 ? (
          <div className="px-6 py-12 text-center">
            <p className="text-sm font-medium text-[color:var(--color-text)]">Everything is billed for this month</p>
            <p className="mt-1 text-sm text-[color:var(--color-text-muted)]">
              Every case that was billed recently already has a bill for {month ? formatMonth(`${month}-01`) : 'it'}.
            </p>
          </div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="text-left text-xs text-[color:var(--color-text-muted)]">
                  <th className="px-4 py-2 font-medium">Case</th>
                  <th className="px-4 py-2 font-medium">Client</th>
                  <th className="px-4 py-2 font-medium">Last billed for</th>
                  <th className="px-4 py-2 text-right font-medium">Last bill total</th>
                  <th className="px-4 py-2 font-medium">Behind</th>
                  <th className="px-4 py-2" />
                </tr>
              </thead>
              <tbody>
                {cases.map((row) => (
                  <tr key={row.case_code} className="border-t border-[color:var(--color-border)] hover:bg-muted/50">
                    <td className="px-4 py-2 font-medium text-[color:var(--color-text)]">
                      {row.case_name}
                      {row.location && row.location !== row.case_name && (
                        <span className="block text-xs font-normal text-[color:var(--color-text-muted)]">{row.location}</span>
                      )}
                    </td>
                    <td className="px-4 py-2 text-[color:var(--color-text)]">{row.client_name ?? ''}</td>
                    <td className="px-4 py-2 text-[color:var(--color-text)]">
                      {formatMonth(row.service_month)}
                      <span className="block text-xs font-medium">
                        Bill <BillNumber number={row.bill_number} code={String(row.id)} />
                      </span>
                    </td>
                    <td className="px-4 py-2 text-right tabular-nums text-[color:var(--color-text)]">₹ {money(row.grand_total)}</td>
                    <td className={`px-4 py-2 ${row.months_behind > 1 ? 'text-warning' : 'text-[color:var(--color-text-muted)]'}`}>
                      {row.months_behind === 1 ? 'This month only' : `${row.months_behind} months`}
                    </td>
                    <td className="px-4 py-2 text-right">
                      {canWrite && (
                        <Button
                          size="sm"
                          onClick={() => navigate(`/utility/billing/new?from=${encodeURIComponent(row.id)}&month=${month}`)}
                        >
                          <Copy className="h-4 w-4" /> Copy last bill
                        </Button>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>
    </div>
  )
}
