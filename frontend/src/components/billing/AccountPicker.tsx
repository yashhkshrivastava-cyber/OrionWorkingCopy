import { useEffect, useState } from 'react'
import { api } from '../../api/client'
import type { MoneyAccount } from '../../types'
import { Field, Select } from '../ui/Field'

const REMEMBER = 'orion.payment.account'

let cached: Promise<MoneyAccount[]> | null = null
/** The accounts, fetched once for the whole page: every payment form on it shares the answer. */
function accountsOnce(): Promise<MoneyAccount[]> {
  cached ??= api
    .moneyAccounts()
    .then((r) => r.accounts)
    .catch(() => {
      cached = null
      return []
    })
  return cached
}

/** The account used last time, as a convenience: a stale or missing one means "the default account". */
export function lastAccount(accounts: MoneyAccount[]): number | undefined {
  try {
    const id = Number(window.localStorage.getItem(REMEMBER))
    return accounts.some((a) => a.account_id === id) ? id : undefined
  } catch {
    return undefined // blocked storage: no memory, which only costs a click
  }
}

export function rememberAccount(id: number | undefined) {
  try {
    if (id) window.localStorage.setItem(REMEMBER, String(id))
  } catch {
    /* remembering the choice is a convenience */
  }
}

/**
 * Which account a payment moved in. With one account there is nothing to choose and nothing is shown; with several the person chooses (the one used last
 * is offered first), and the payment lands in that account's balance on the Bank pages.
 */
export function AccountPicker({ value, onChange, label }: { value: number | undefined; onChange: (id: number) => void; label: string }) {
  const [accounts, setAccounts] = useState<MoneyAccount[]>([])
  useEffect(() => {
    let live = true
    accountsOnce().then((found) => {
      if (!live) return
      setAccounts(found)
      if (value === undefined && found.length > 1) onChange(lastAccount(found) ?? found[0].account_id)
    })
    return () => {
      live = false
    }
  }, [value, onChange])
  if (accounts.length < 2) return null
  return (
    <Field label={label}>
      <Select value={value ?? accounts[0].account_id} onChange={(e) => onChange(Number(e.target.value))} aria-label={label}>
        {accounts.map((a) => (
          <option key={a.account_id} value={a.account_id}>
            {a.account_name} ({a.account_kind === 'cash' ? 'cash' : 'bank'})
          </option>
        ))}
      </Select>
    </Field>
  )
}
