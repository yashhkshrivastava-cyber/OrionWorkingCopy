import { useOutletContext } from 'react-router-dom'
import type { BankAccount, BankMeta } from '../../types'

export type BankAccountWithBalance = BankAccount & { balance: number }

/** What the Bank page gives the screens inside it: the lists they draw choices from, the accounts, and a way to say "money moved". */
export type BankContext = {
  meta: BankMeta
  /**
   * The account an action applies to (a statement, an opening balance, a new entry): the one chosen in the switcher, or, when "All accounts" is
   * chosen, the first bank account. `configured` is false until an account exists.
   */
  account: BankAccount
  /** Every account, with its balance today. */
  accounts: BankAccountWithBalance[]
  /** The account the figures are for, or null for all of them added together. */
  scope: number | null
  setScope: (id: number | null) => void
  /** May this person record, upload and match? Reading is all the page itself needs. */
  canWrite: boolean
  /** Goes up whenever something was saved, so a screen that shows figures knows to ask again. */
  version: number
  /** Call after anything was saved. */
  changed: () => void
  /** An account was set up or changed. */
  accountChanged: (account: BankAccount) => void
}

export function useBank(): BankContext {
  return useOutletContext<BankContext>()
}
