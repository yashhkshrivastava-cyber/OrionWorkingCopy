import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { ArrowRight, Wallet } from 'lucide-react'
import { bankApi } from '../../api/client'
import { money } from '../../bank/format'
import { useAuth } from '../../context/AuthContext'
import type { BankSummary } from '../../types'

/** The bank on the Overview dashboard: the balance and this year’s interest and other income, with a way into the Cash tab. Only for people with Bank access, and nothing at all until the account is set up. */
export function BankGlance({ search = '' }: { search?: string }) {
  const { user } = useAuth()
  const allowed = Boolean(user?.can_bank)
  const [summary, setSummary] = useState<BankSummary | null>(null)

  useEffect(() => {
    if (!allowed) return
    let live = true
    bankApi
      .summary()
      .then((s) => live && setSummary(s))
      .catch(() => live && setSummary(null))
    return () => {
      live = false
    }
  }, [allowed])

  if (!allowed || !summary?.configured || !summary.financial_year) return null
  const fy = summary.financial_year
  return (
    <Link
      to={{ pathname: '/dashboard/orion/cash', search }}
      className="panel interactive group flex flex-wrap items-center justify-between gap-x-8 gap-y-2 px-5 py-4 hover:shadow-raised"
    >
      <span className="flex items-center gap-3">
        <span className="rounded-full bg-accent-dim p-2.5 text-accent">
          <Wallet className="h-5 w-5" aria-hidden="true" />
        </span>
        <span>
          <span className="t-label block text-[color:var(--color-text-muted)]">Bank balance today</span>
          <span className={`text-xl font-semibold tabular-nums ${(summary.balance ?? 0) < 0 ? 'text-negative' : ''}`}>{money(summary.balance)}</span>
        </span>
      </span>
      <span className="text-sm">
        <span className="t-label block text-[color:var(--color-text-muted)]">Interest and other income this year</span>
        <span className="font-semibold tabular-nums">{money(fy.interest_and_other_income)}</span>
      </span>
      <span className="inline-flex items-center gap-1.5 text-sm font-medium text-accent">
        Open the Cash tab
        <ArrowRight className="h-4 w-4 transition-transform group-hover:translate-x-0.5" aria-hidden="true" />
      </span>
    </Link>
  )
}
