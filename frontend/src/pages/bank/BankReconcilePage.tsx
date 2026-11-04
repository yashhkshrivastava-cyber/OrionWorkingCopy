import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { CircleAlert, CircleCheck, Landmark, Trash2 } from 'lucide-react'
import { bankApi } from '../../api/client'
import { day, money } from '../../bank/format'
import { LineQueue } from '../../components/bank/LineQueue'
import { BalanceScale } from '../../components/bank/lumenBank'
import { StatementUpload } from '../../components/bank/StatementUpload'
import { Alert } from '../../components/ui/Alert'
import { Button } from '../../components/ui/Button'
import { EmptyState } from '../../components/ui/EmptyState'
import { useToast } from '../../components/ui/Toast'
import { useLumen } from '../../lumen/useLumen'
import type { BankException, BankImportResult, BankImportRow, BankReconciliation } from '../../types'
import { useBank } from './bankContext'

function Row({ label, value, strong }: { label: string; value: string; strong?: boolean }) {
  return (
    <div className="flex items-baseline justify-between gap-4 py-1.5">
      <dt className="text-sm text-[color:var(--color-text-muted)]">{label}</dt>
      <dd className={`text-sm tabular-nums ${strong ? 'font-semibold' : ''}`}>{value}</dd>
    </div>
  )
}

/** Does the book agree with the bank? The latest statement’s balance against the book’s balance on the same day, and everything that explains the gap. */
function Standing({ state }: { state: BankReconciliation | null }) {
  const lumen = useLumen()
  if (!state) return null
  if (state.state === 'no_statement') {
    return (
      <section className="panel p-5">
        <h2 className="t-h3">Does the book agree with the bank?</h2>
        <p className="t-small mt-1 text-[color:var(--color-text-muted)]">
          {state.has_lines ? 'The statements uploaded so far have no balance column or are all before the opening date, so there is nothing to compare yet.' : 'Upload a statement below and Orion will compare it with the book, line by line.'}
        </p>
      </section>
    )
  }
  const clean = state.state === 'reconciled'
  const bad = state.state === 'unexplained'
  const Icon = clean ? CircleCheck : CircleAlert
  const bookOnly = state.book_only
  const bankOnly = state.statement_only
  return (
    <section aria-label="Reconciliation" className="panel p-5">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h2 className="t-h3">Does the book agree with the bank?</h2>
          <p className="t-caption mt-0.5">The latest statement, as of {day(state.as_of)}.</p>
        </div>
        <span className={`inline-flex items-center gap-1.5 rounded-full px-3 py-1 text-xs font-semibold ${clean ? 'bg-positive-dim text-positive' : bad ? 'bg-negative-dim text-negative' : 'bg-warning-dim text-warning'}`}>
          <Icon className="h-3.5 w-3.5" aria-hidden="true" />
          {clean ? 'Reconciled' : bad ? 'Does not add up' : 'Differences explained below'}
        </span>
      </div>
      {lumen && <BalanceScale statement={state.statement_balance} book={state.book_balance} difference={state.difference} clean={clean} />}
      <dl className="mt-3 divide-y divide-[color:var(--color-border)]/60">
        {!lumen && (
          <>
            <Row label="Balance on the statement" value={money(state.statement_balance)} strong />
            <Row label="Balance in Orion’s book on that day" value={money(state.book_balance)} strong />
            <Row label="Difference" value={money(state.difference)} />
          </>
        )}
        {bookOnly && bookOnly.count > 0 && (
          <Row label={`${bookOnly.count} movement${bookOnly.count === 1 ? '' : 's'} in the book that the bank does not show (net)`} value={money(bookOnly.net)} />
        )}
        {bankOnly && bankOnly.count > 0 && (
          <Row label={`${bankOnly.count} statement line${bankOnly.count === 1 ? '' : 's'} the book does not hold (net)`} value={money(bankOnly.net)} />
        )}
        {(state.changed_after_matching ?? 0) > 0 && <Row label="Matched lines whose match no longer holds (see below)" value={String(state.changed_after_matching)} />}
        <Row label="Still unexplained" value={money(state.unexplained)} strong />
      </dl>
      {bad && (
        <p className="t-small mt-3 text-negative">
          Something is missing that is neither a loose movement nor a loose line: most often the opening balance is not what the bank held on that day, or a stretch of the statement has not been
          uploaded. Check the opening balance on the Account tab.{' '}
          <Link to="/bank/account" className="underline">Open Account</Link>
        </p>
      )}
      {!clean && !bad && (
        <p className="t-small mt-3 text-[color:var(--color-text-muted)]">
          Nothing is wrong: the balances differ only by items that are on one side and not the other. Match or record the lines below and the difference closes.
        </p>
      )}
    </section>
  )
}

/**
 * Lines that were matched, and then the book changed under the match: a payment reversed on its bill, an expense cancelled, a GST payment taken back, an amount
 * edited. They would otherwise look reconciled when they are not. Returning one to unmatched writes why to the history and matches again whatever is certain.
 */
function Changed({ items, canWrite, onChanged }: { items: BankException[]; canWrite: boolean; onChanged: () => void }) {
  const toast = useToast()
  const [busy, setBusy] = useState<number | null>(null)
  const [error, setError] = useState('')
  if (!items.length) return null
  const clear = async (item: BankException) => {
    setBusy(item.line_id)
    setError('')
    try {
      const result = await bankApi.clearException(item.line_id)
      toast.show('Returned to unmatched', { detail: result.rematched ? `${result.rematched} line${result.rematched === 1 ? '' : 's'} matched again on its own.` : undefined })
      onChanged()
    } catch (err) {
      setError(err instanceof Error ? err.message : 'That did not work.')
      onChanged()
    } finally {
      setBusy(null)
    }
  }
  return (
    <section aria-label="Matched, then changed" className="panel border-warning/40 p-5">
      <h2 className="t-h3">Matched, then changed in the book</h2>
      <p className="t-caption mt-0.5">
        These statement lines were matched, but what they were matched to has since been reversed, cancelled or edited. They are not reconciled until you look at them again.
      </p>
      {error && <div className="mt-3"><Alert variant="error" onDismiss={() => setError('')}>{error}</Alert></div>}
      <ul className="mt-3 divide-y divide-[color:var(--color-border)]/60">
        {items.map((item) => (
          <li key={item.line_id} className="flex flex-wrap items-center justify-between gap-3 py-2.5 text-sm">
            <div className="min-w-0 flex-1">
              <p>
                <span className="tabular-nums text-[color:var(--color-text-muted)]">{day(item.line_date)}</span> <span className="font-medium">{item.description || 'No narration'}</span>{' '}
                <span className={`tabular-nums font-semibold ${item.direction === 'in' ? 'text-positive' : 'text-negative'}`}>{item.direction === 'in' ? '+' : '−'}{money(item.line_amount)}</span>
              </p>
              <p className="t-caption mt-0.5">Because {item.reason}.</p>
            </div>
            {canWrite && (
              <Button size="sm" variant="secondary" loading={busy === item.line_id} onClick={() => clear(item)}>
                Return to unmatched
              </Button>
            )}
          </li>
        ))}
      </ul>
    </section>
  )
}

function Uploads({ imports, canWrite, onChanged }: { imports: BankImportRow[]; canWrite: boolean; onChanged: () => void }) {
  const toast = useToast()
  const [error, setError] = useState('')
  const [busy, setBusy] = useState<number | null>(null)
  if (!imports.length) return null
  const remove = async (row: BankImportRow) => {
    setBusy(row.import_id)
    setError('')
    try {
      await bankApi.removeStatement(row.import_id)
      toast.show('Upload taken back')
      onChanged()
    } catch (err) {
      setError(err instanceof Error ? err.message : 'That did not work.')
    } finally {
      setBusy(null)
    }
  }
  return (
    <section aria-label="Uploads" className="panel p-5">
      <h2 className="t-h3">Statements uploaded</h2>
      <p className="t-caption mt-0.5">The files themselves are not kept, only their lines.</p>
      {error && <div className="mt-3"><Alert variant="error" onDismiss={() => setError('')}>{error}</Alert></div>}
      <ul className="mt-3 divide-y divide-[color:var(--color-border)]/60">
        {imports.map((row) => (
          <li key={row.import_id} className="flex flex-wrap items-center justify-between gap-3 py-2.5 text-sm">
            <div className="min-w-0">
              <p className="truncate font-medium">{row.filename}</p>
              <p className="t-caption">
                {day(row.period_from)} – {day(row.period_to)} · {row.new_count} new, {row.duplicate_count} already held · {row.matched} matched · uploaded {day(row.uploaded_timestamp)}
                {row.uploaded_by ? ` by ${row.uploaded_by}` : ''}
              </p>
            </div>
            {canWrite && (
              <Button variant="ghost" size="sm" disabled={busy === row.import_id || row.matched > 0} title={row.matched > 0 ? 'Unmatch its lines first' : 'Take this upload back'} onClick={() => remove(row)}>
                <Trash2 className="h-3.5 w-3.5" aria-hidden="true" />
                Take back
              </Button>
            )}
          </li>
        ))}
      </ul>
    </section>
  )
}

/** Check the book against the bank: upload a statement, let Orion match what is certain, and work through the rest. */
export function BankReconcilePage() {
  const { meta, account, accounts, canWrite, version, changed } = useBank()
  const toast = useToast()
  const [state, setState] = useState<BankReconciliation | null>(null)
  const [imports, setImports] = useState<BankImportRow[]>([])
  const [changedLines, setChangedLines] = useState<BankException[]>([])
  const [error, setError] = useState('')

  useEffect(() => {
    if (!account.configured) return
    let live = true
    Promise.all([bankApi.reconciliation(account.account_id), bankApi.statements(account.account_id), bankApi.exceptions(account.account_id)])
      .then(([r, s, x]) => {
        if (!live) return
        setState(r)
        setImports(s.imports)
        setChangedLines(x.exceptions)
        setError('')
      })
      .catch((err: Error) => live && setError(err.message))
    return () => {
      live = false
    }
  }, [account.configured, account.account_id, version])

  if (!account.configured) {
    return (
      <EmptyState icon={Landmark} title="The bank account is not set up yet">
        <Link to="/bank/account" className="text-accent hover:underline">Enter the opening balance</Link> first; statements are checked against the book that starts from it.
      </EmptyState>
    )
  }

  const imported = (result: BankImportResult) => {
    toast.show(`${result.new_count} line${result.new_count === 1 ? '' : 's'} imported`, {
      detail: result.auto_matched ? `${result.auto_matched} matched straight away; the rest are below.` : 'Nothing could be matched with certainty; work through them below.',
    })
    changed()
  }

  return (
    <div className="space-y-4">
      {error && <Alert variant="error">{error}</Alert>}
      {accounts.length > 1 && (
        <p className="t-small text-[color:var(--color-text-muted)]">
          Checking <span className="font-medium text-[color:var(--color-text)]">{account.account_name}</span>. A statement belongs to one account: choose another above to check it.
        </p>
      )}
      {account.account_kind === 'cash' ? null : <Standing state={state} />}
      {account.account_kind !== 'cash' && <Changed items={changedLines} canWrite={canWrite} onChanged={changed} />}
      {account.account_kind === 'cash' ? (
        <EmptyState icon={Landmark} title={`${account.account_name} is a cash account`}>
          Cash has no bank statement to check against. Choose a bank account in the switcher above to reconcile it; cash is counted, and the count comes with the next update.
        </EmptyState>
      ) : (
        <>
          {canWrite && <StatementUpload onImported={imported} accountId={account.account_id} />}
          <LineQueue meta={meta} canWrite={canWrite} openingDate={account.opening_date} accountId={account.account_id} version={version} onChanged={changed} />
          <Uploads imports={imports} canWrite={canWrite} onChanged={changed} />
        </>
      )}
    </div>
  )
}
