import { useCallback, useEffect, useMemo, useState } from 'react'
import { NavLink, Outlet } from 'react-router-dom'
import { ArrowLeftRight, CalendarClock, LayoutDashboard, ListOrdered, Settings2, Users } from 'lucide-react'
import { bankApi } from '../../api/client'
import { money } from '../../bank/format'
import { LoadingState } from '../../components/ui/DataTable'
import { Alert } from '../../components/ui/Alert'
import { Select } from '../../components/ui/Field'
import { useAuth } from '../../context/AuthContext'
import { useDataRefresh } from '../../context/DataRefreshContext'
import type { BankAccount, BankMeta } from '../../types'
import type { BankAccountWithBalance, BankContext } from './bankContext'

const TABS = [
  { to: '/bank', label: 'Overview', icon: LayoutDashboard, end: true },
  { to: '/bank/ledger', label: 'Ledger', icon: ListOrdered, end: false },
  { to: '/bank/payables', label: 'Payables', icon: CalendarClock, end: false },
  { to: '/bank/payroll', label: 'Payroll', icon: Users, end: false },
  { to: '/bank/reconcile', label: 'Reconcile', icon: ArrowLeftRight, end: false },
  { to: '/bank/account', label: 'Accounts', icon: Settings2, end: false },
]

const REMEMBER = 'orion.bank.scope'
const remembered = (): number | null => {
  try {
    const value = window.localStorage.getItem(REMEMBER)
    return value ? Number(value) : null
  } catch {
    return null // a private window or blocked storage: the switcher simply starts on all accounts
  }
}

/**
 * The firm's money accounts (bank accounts, and cash): what each holds, every movement behind that figure, whether the book agrees with the bank, and
 * the opening balance each starts from. A balance is worked out, never typed: the opening balance, plus clients' payments, minus expenses and GST paid
 * (all of which Orion already holds), plus and minus what is entered here (interest, charges and the like). With several accounts a switcher chooses
 * one, or all of them added together.
 */
export function BankPage() {
  const { user } = useAuth()
  const { generation } = useDataRefresh()
  const [meta, setMeta] = useState<BankMeta | null>(null)
  const [accounts, setAccounts] = useState<BankAccountWithBalance[] | null>(null)
  const [error, setError] = useState('')
  const [version, setVersion] = useState(0)
  const [chosen, setChosen] = useState<number | null>(remembered)

  useEffect(() => {
    let live = true
    bankApi
      .meta()
      .then((m) => live && setMeta(m))
      .catch((err: Error) => live && setError(err.message))
    return () => {
      live = false
    }
  }, [])

  useEffect(() => {
    let live = true
    bankApi
      .accounts()
      .then((a) => live && setAccounts(a.accounts as BankAccountWithBalance[]))
      .catch((err: Error) => live && setError(err.message))
    return () => {
      live = false
    }
  }, [version, generation])

  const changed = useCallback(() => setVersion((n) => n + 1), [])
  const accountChanged = useCallback((next: BankAccount) => {
    setVersion((n) => n + 1)
    if (next.account_id) {
      setChosen(next.account_id)
      try {
        window.localStorage.setItem(REMEMBER, String(next.account_id))
      } catch {
        /* remembering the choice is a convenience */
      }
    }
  }, [])
  const setScope = useCallback((id: number | null) => {
    setChosen(id)
    try {
      if (id === null) window.localStorage.removeItem(REMEMBER)
      else window.localStorage.setItem(REMEMBER, String(id))
    } catch {
      /* remembering the choice is a convenience */
    }
  }, [])

  // A remembered account that no longer exists falls back to all of them.
  const scope = accounts && chosen !== null && accounts.some((a) => a.account_id === chosen) ? chosen : null
  const acting = useMemo<BankAccount>(() => {
    if (!accounts || accounts.length === 0) return { configured: false }
    const found = accounts.find((a) => a.account_id === scope) ?? accounts.find((a) => a.account_kind === 'bank') ?? accounts[0]
    return { ...found, configured: true }
  }, [accounts, scope])

  if (error) return <Alert variant="error">{error}</Alert>
  if (!meta || !accounts) return <LoadingState message="Opening the bank…" />

  const total = accounts.reduce((sum, a) => sum + a.balance, 0)
  const context: BankContext = { meta, account: acting, accounts, scope, setScope, canWrite: Boolean(user?.can_bank_write), version: version + generation, changed, accountChanged }

  return (
    <div className="mx-auto w-full max-w-[1500px] space-y-4">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <nav aria-label="Bank">
          <div className="scroll-quiet -mx-4 overflow-x-auto px-4 pb-1 sm:mx-0 sm:px-0">
            <div className="flex w-max gap-1 rounded-xl bg-muted p-1">
              {TABS.map((tab) => {
                const Icon = tab.icon
                return (
                  <NavLink
                    key={tab.to}
                    to={tab.to}
                    end={tab.end}
                    className={({ isActive }) =>
                      `flex items-center gap-1.5 rounded-lg px-3 py-2 text-sm font-medium transition-colors focus-visible:ring-2 focus-visible:ring-accent ${
                        isActive
                          ? 'bg-surface text-[color:var(--color-text)] shadow-sm'
                          : 'text-[color:var(--color-text-muted)] hover:bg-surface/60 hover:text-[color:var(--color-text)]'
                      }`
                    }
                  >
                    <Icon className="h-4 w-4 text-accent" aria-hidden="true" />
                    {tab.label}
                  </NavLink>
                )
              })}
            </div>
          </div>
        </nav>
        {accounts.length > 1 && (
          <label className="block w-full min-w-[14rem] text-xs sm:w-72">
            <span className="sr-only">Account</span>
            <Select value={scope === null ? 'all' : String(scope)} onChange={(e) => setScope(e.target.value === 'all' ? null : Number(e.target.value))} aria-label="Account">
              <option value="all">All accounts · {money(total)}</option>
              {accounts.map((a) => (
                <option key={a.account_id} value={a.account_id}>
                  {a.account_name} ({a.account_kind === 'cash' ? 'cash' : 'bank'}) · {money(a.balance)}
                </option>
              ))}
            </Select>
          </label>
        )}
      </div>
      <Outlet context={context} />
    </div>
  )
}
