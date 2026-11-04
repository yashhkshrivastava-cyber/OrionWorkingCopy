import { useEffect, useMemo, useState } from 'react'
import { Check, ChevronDown, CircleCheck, Link2, Link2Off, Plus, RotateCcw, Search, Sparkles, X } from 'lucide-react'
import { bankApi } from '../../api/client'
import { day, money } from '../../bank/format'
import type { BankAiSuggestions, BankLine, BankLineMatch, BankMeta, BankMovement, BankSuggestions } from '../../types'
import { AiButton, AiNotice, AiProvenance, useAiTask } from '../ai/AiTask'
import { BillNumber } from '../billing/BillNumber'
import { Alert } from '../ui/Alert'
import { Button } from '../ui/Button'
import { EmptyState } from '../ui/EmptyState'
import { Field, Input, Textarea } from '../ui/Field'
import { Modal } from '../ui/Modal'
import { Segmented } from '../ui/Segmented'
import { useToast } from '../ui/Toast'
import { useLumen } from '../../lumen/useLumen'
import { BillText } from './BillText'
import { EntryModal, type EntryPreset } from './EntryModal'
import { DirectionTile } from './lumenBank'

type Status = 'Unmatched' | 'Matched' | 'Ignored'
const PAGE = 25

const METHOD: Record<BankLineMatch['method'], string> = { auto: 'Matched by Orion', manual: 'Matched by hand', created: 'Entry made from this line' }

/** What a movement of the book is, in a line: who, what, and the bill it belongs to. */
function MovementLine({ who, what, reference, billCode, source }: { who: string | null; what: string | null; reference: string | null; billCode: string | null; source: string }) {
  return (
    <span className="min-w-0">
      {source === 'gst' ? (
        <span className="font-medium">
          <BillText text={what || who} />
        </span>
      ) : (
        <span className="font-medium">{who || what || 'Movement'}</span>
      )}
      {source !== 'gst' && who && what && <span className="text-[color:var(--color-text-muted)]"> · {what}</span>}
      {source === 'revenue' && reference && (
        <span className="text-[color:var(--color-text-muted)]">
          {' · '}
          <BillNumber number={reference} code={billCode} />
        </span>
      )}
      {source !== 'revenue' && source !== 'gst' && reference && <span className="text-[color:var(--color-text-muted)]"> · {reference}</span>}
    </span>
  )
}

function Candidate({ movement, reasons, onMatch, busy }: { movement: BankMovement; reasons: string[]; onMatch: () => void; busy: boolean }) {
  return (
    <li className="flex flex-wrap items-center justify-between gap-2 rounded-lg border border-[color:var(--color-border)] bg-surface px-3 py-2 text-sm">
      <div className="min-w-0 flex-1">
        <div className="flex flex-wrap items-center gap-x-2">
          <span className="tabular-nums text-[color:var(--color-text-muted)]">{day(movement.move_date)}</span>
          <MovementLine who={movement.counterparty} what={movement.description} reference={movement.reference} billCode={movement.bill_code} source={movement.source} />
        </div>
        <div className="mt-1 flex flex-wrap gap-1">
          {reasons.map((reason) => (
            <span key={reason} className="rounded bg-accent-dim px-1.5 py-0.5 text-[10px] font-medium text-accent">
              {reason}
            </span>
          ))}
        </div>
      </div>
      <Button size="sm" variant="secondary" onClick={onMatch} disabled={busy}>
        <Link2 className="h-3.5 w-3.5" aria-hidden="true" />
        This is it
      </Button>
    </li>
  )
}

function Suggestions({ line, version, onMatch, busy }: { line: BankLine; version: number; onMatch: (movements: BankMovement[]) => void; busy: boolean }) {
  const [found, setFound] = useState<BankSuggestions | null>(null)
  const [error, setError] = useState('')
  useEffect(() => {
    let live = true
    setFound(null)
    bankApi
      .suggestions(line.line_id)
      .then((r) => live && setFound(r))
      .catch((err: Error) => live && setError(err.message))
    return () => {
      live = false
    }
  }, [line.line_id, version])

  if (error) return <Alert variant="error">{error}</Alert>
  if (!found) return <p className="t-small text-[color:var(--color-text-muted)]">Looking for it in the book…</p>
  if (!found.candidates.length && !found.combinations.length) {
    return (
      <p className="t-small text-[color:var(--color-text-muted)]">
        Nothing in the book has this amount near this date. If it is real money Orion does not know about, record it. If a payment has not been entered on its bill yet, enter it and come back.
      </p>
    )
  }
  return (
    <div className="space-y-3">
      {found.candidates.length > 0 && (
        <div>
          <p className="t-label mb-1.5">Could be</p>
          <ul className="space-y-2">
            {found.candidates.map((c) => (
              <Candidate key={`${c.movement.source}:${c.movement.source_ref}`} movement={c.movement} reasons={c.reasons} busy={busy} onMatch={() => onMatch([c.movement])} />
            ))}
          </ul>
        </div>
      )}
      {found.combinations.map((group, at) => (
        <div key={at} className="rounded-lg border border-dashed border-[color:var(--color-border-strong)] p-3">
          <p className="t-label mb-1.5">{group.length} payments that add up to exactly {money(line.amount)}</p>
          <ul className="space-y-1 text-sm">
            {group.map((m) => (
              <li key={`${m.source}:${m.source_ref}`} className="flex items-baseline justify-between gap-3">
                <span className="min-w-0">
                  <span className="tabular-nums text-[color:var(--color-text-muted)]">{day(m.move_date)}</span>{' '}
                  <MovementLine who={m.counterparty} what={m.description} reference={m.reference} billCode={m.bill_code} source={m.source} />
                </span>
                <span className="tabular-nums">{money(m.amount)}</span>
              </li>
            ))}
          </ul>
          <Button size="sm" variant="secondary" className="mt-2" onClick={() => onMatch(group)} disabled={busy}>
            <Link2 className="h-3.5 w-3.5" aria-hidden="true" />
            Match all {group.length}
          </Button>
        </div>
      ))}
    </div>
  )
}

/**
 * The statement lines to work through. Unmatched ones are the work: each can be matched to a payment, expense or entry Orion already has (it suggests
 * the likely ones), recorded as a new entry (interest, a charge ...), or set aside with a reason. Nothing is guessed for the person: Orion matches on
 * its own only what is certain, and everything else waits for a click.
 */
export function LineQueue({
  meta,
  canWrite,
  openingDate,
  accountId,
  version,
  onChanged,
}: {
  meta: BankMeta
  canWrite: boolean
  openingDate?: string
  /** The account whose statement lines these are. */
  accountId?: number
  version: number
  onChanged: () => void
}) {
  const toast = useToast()
  const lumen = useLumen()
  const [status, setStatus] = useState<Status>('Unmatched')
  const [typed, setTyped] = useState('')
  const [q, setQ] = useState('')
  const [page, setPage] = useState(1)
  const [data, setData] = useState<{ rows: BankLine[]; total: number } | null>(null)
  const [error, setError] = useState('')
  const [open, setOpen] = useState<number | null>(null)
  const [busy, setBusy] = useState(false)
  const [recording, setRecording] = useState<{ line: BankLine; preset: EntryPreset } | null>(null)
  const [setting, setSetting] = useState<BankLine | null>(null)
  const [why, setWhy] = useState('')
  const [whyError, setWhyError] = useState('')
  const ai = useAiTask<BankAiSuggestions>()

  useEffect(() => {
    const timer = window.setTimeout(() => {
      setQ(typed)
      setPage(1)
    }, 300)
    return () => window.clearTimeout(timer)
  }, [typed])

  useEffect(() => {
    let live = true
    bankApi
      .lines({ status, q, page, limit: PAGE, account_id: accountId })
      .then((r) => {
        if (!live) return
        setData(r)
        setError('')
      })
      .catch((err: Error) => live && setError(err.message))
    return () => {
      live = false
    }
  }, [status, q, page, version, accountId])

  const aiFor = (line: BankLine) => ai.result?.suggestions?.[String(line.line_id)]
  const total = data?.total ?? 0
  const last = Math.max(1, Math.ceil(total / PAGE))
  const unnamed = useMemo(() => (data?.rows ?? []).filter((l) => l.status === 'Unmatched' && !l.guess).length, [data])

  const act = async (work: () => Promise<unknown>, done: string) => {
    if (busy) return
    setBusy(true)
    try {
      await work()
      toast.show(done)
      setOpen(null)
      onChanged()
    } catch (err) {
      setError(err instanceof Error ? err.message : 'That did not work. Try again.')
      onChanged()
    } finally {
      setBusy(false)
    }
  }

  const certain = async () => {
    if (busy) return
    setBusy(true)
    try {
      const result = await bankApi.autoMatch(accountId)
      toast.show(result.matched ? `${result.matched} line${result.matched === 1 ? '' : 's'} matched` : 'Nothing more is certain')
      onChanged()
    } catch (err) {
      setError(err instanceof Error ? err.message : 'That did not work. Try again.')
    } finally {
      setBusy(false)
    }
  }

  const recordPreset = (line: BankLine): EntryPreset => {
    const suggestion = aiFor(line)
    return {
      direction: line.direction,
      category: line.guess?.category ?? suggestion?.category,
      counterparty: suggestion?.counterparty ?? undefined,
    }
  }

  const setAside = async () => {
    if (!setting) return
    if (why.trim().length < 3) return setWhyError('Say why, in a few words.')
    setWhyError('')
    await act(() => bankApi.ignoreLine(setting.line_id, why.trim()), 'Line set aside')
    setSetting(null)
    setWhy('')
  }

  return (
    <section aria-label="Statement lines" className="panel space-y-4 p-4 sm:p-5">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <Segmented
          label="Statement lines"
          value={status}
          onChange={(next) => {
            setStatus(next)
            setPage(1)
            setOpen(null)
          }}
          options={[
            { id: 'Unmatched', label: 'To do' },
            { id: 'Matched', label: 'Matched' },
            { id: 'Ignored', label: 'Set aside' },
          ]}
        />
        <div className="relative w-full sm:w-64">
          <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-[color:var(--color-text-faint)]" aria-hidden="true" />
          <Input value={typed} onChange={(e) => setTyped(e.target.value)} placeholder="Search narration" className="pl-9" aria-label="Search statement lines" />
        </div>
      </div>

      {canWrite && status === 'Unmatched' && (
        <div className="space-y-2">
          <div className="flex flex-wrap items-center gap-2">
            <Button size="sm" variant="secondary" onClick={certain} disabled={busy}>
              <Check className="h-3.5 w-3.5" aria-hidden="true" />
              Match what is certain
            </Button>
            {unnamed > 0 && (
              <AiButton onClick={() => ai.run((once) => bankApi.categorise(once))} disabled={ai.busy} title="Ask the assistant what the lines Orion could not recognise are">
                Suggest what the rest are
              </AiButton>
            )}
          </div>
          <AiNotice task={ai} />
          {ai.phase === 'ok' && ai.result && (
            <p className="t-caption flex flex-wrap items-center gap-1.5">
              <Sparkles className="h-3.5 w-3.5 text-accent" aria-hidden="true" />
              {Object.keys(ai.result.suggestions).length} suggestion{Object.keys(ai.result.suggestions).length === 1 ? '' : 's'} added to the lines below. Nothing is saved until you record a line.
              <AiProvenance where={ai.result.where} provider={ai.result.provider} />
            </p>
          )}
        </div>
      )}

      {error && <Alert variant="error" onDismiss={() => setError('')}>{error}</Alert>}

      {data && data.rows.length === 0 && (
        <EmptyState compact icon={status === 'Unmatched' ? CircleCheck : undefined} title={status === 'Unmatched' ? (q ? 'No unmatched line has those words' : 'Nothing left to do') : 'Nothing here'}>
          {status === 'Unmatched' && !q ? 'Every line of the statements uploaded so far is matched or set aside.' : undefined}
        </EmptyState>
      )}

      <ul className="space-y-2">
        {data?.rows.map((line) => {
          const expanded = open === line.line_id
          const suggestion = aiFor(line)
          return (
            <li key={line.line_id} className={`border border-[color:var(--color-border)] bg-surface ${lumen ? 'rounded-2xl' : 'rounded-xl'}`}>
              <div className="flex flex-wrap items-start justify-between gap-3 p-3">
                {lumen && <DirectionTile direction={line.direction} />}
                <div className="min-w-0 flex-1">
                  <p className="text-sm">
                    <span className="tabular-nums text-[color:var(--color-text-muted)]">{day(line.line_date)}</span>
                    <span className="mx-2 text-[color:var(--color-text-faint)]">·</span>
                    <span className="break-words font-medium">{line.description || 'No narration'}</span>
                  </p>
                  {line.reference && <p className="t-caption mt-0.5">Ref {line.reference}</p>}
                  {line.status === 'Unmatched' && (line.guess || suggestion) && (
                    <p className="mt-1.5 flex flex-wrap items-center gap-1.5 text-xs">
                      {line.guess && (
                        <span className="rounded bg-accent-dim px-1.5 py-0.5 font-medium text-accent">
                          {line.guess.category_label} · {line.guess.why}
                        </span>
                      )}
                      {!line.guess && suggestion && (
                        <span className="inline-flex items-center gap-1 rounded bg-muted px-1.5 py-0.5 font-medium">
                          <Sparkles className="h-3 w-3 text-accent" aria-hidden="true" />
                          AI suggests {suggestion.category_label}
                          {suggestion.counterparty ? ` · ${suggestion.counterparty}` : ''}
                        </span>
                      )}
                    </p>
                  )}
                  {line.status === 'Matched' && (
                    <ul className="mt-1.5 space-y-0.5 text-sm">
                      {line.matches.map((m) => (
                        <li key={`${m.source}:${m.source_ref}`} className="flex flex-wrap items-baseline gap-x-2">
                          <CircleCheck className="h-3.5 w-3.5 shrink-0 translate-y-0.5 text-positive" aria-hidden="true" />
                          <MovementLine who={m.counterparty} what={m.description} reference={m.reference} billCode={m.bill_code} source={m.source} />
                          {line.matches.length > 1 && <span className="tabular-nums text-[color:var(--color-text-muted)]">{money(m.amount)}</span>}
                          <span className="t-caption">{METHOD[m.method]}</span>
                        </li>
                      ))}
                    </ul>
                  )}
                  {line.status === 'Ignored' && <p className="mt-1 text-sm text-[color:var(--color-text-muted)]">Set aside: {line.ignore_reason}</p>}
                </div>
                <div className="flex shrink-0 items-center gap-3">
                  <span className={`font-semibold tabular-nums ${lumen ? 'font-display text-lg' : 'text-sm'} ${line.direction === 'in' ? 'text-positive' : 'text-negative'}`}>
                    {line.direction === 'in' ? '+' : '−'}
                    {money(line.amount)}
                  </span>
                  {canWrite && line.status === 'Unmatched' && (
                    <>
                      <Button size="sm" variant="secondary" aria-expanded={expanded} onClick={() => setOpen(expanded ? null : line.line_id)}>
                        Find match
                        <ChevronDown className={`h-3.5 w-3.5 transition-transform ${expanded ? 'rotate-180' : ''}`} aria-hidden="true" />
                      </Button>
                      <Button size="sm" variant="secondary" onClick={() => setRecording({ line, preset: recordPreset(line) })}>
                        <Plus className="h-3.5 w-3.5" aria-hidden="true" />
                        Record
                      </Button>
                      <Button size="sm" variant="ghost" onClick={() => { setSetting(line); setWhy(''); setWhyError('') }}>
                        <X className="h-3.5 w-3.5" aria-hidden="true" />
                        Set aside
                      </Button>
                    </>
                  )}
                  {canWrite && line.status === 'Matched' && (
                    <Button size="sm" variant="ghost" disabled={busy} onClick={() => act(() => bankApi.unmatchLine(line.line_id), 'Unmatched')}>
                      <Link2Off className="h-3.5 w-3.5" aria-hidden="true" />
                      Unmatch
                    </Button>
                  )}
                  {canWrite && line.status === 'Ignored' && (
                    <Button size="sm" variant="ghost" disabled={busy || Boolean(openingDate && line.line_date < openingDate)} onClick={() => act(() => bankApi.unignoreLine(line.line_id), 'Brought back')}>
                      <RotateCcw className="h-3.5 w-3.5" aria-hidden="true" />
                      Bring back
                    </Button>
                  )}
                </div>
              </div>
              {expanded && (
                <div className="border-t border-[color:var(--color-border)] bg-muted/40 p-3">
                  <Suggestions line={line} version={version} busy={busy} onMatch={(movements) => act(() => bankApi.matchLine(line.line_id, movements.map((m) => ({ source: m.source, source_ref: m.source_ref }))), 'Matched')} />
                </div>
              )}
            </li>
          )
        })}
      </ul>

      {data && last > 1 && (
        <nav aria-label="Pages" className="flex items-center justify-between">
          <Button variant="secondary" size="sm" disabled={page <= 1} onClick={() => setPage(page - 1)}>
            Newer
          </Button>
          <span className="t-caption">
            Page {page} of {last} · {total.toLocaleString('en-IN')} lines
          </span>
          <Button variant="secondary" size="sm" disabled={page >= last} onClick={() => setPage(page + 1)}>
            Older
          </Button>
        </nav>
      )}

      <EntryModal
        open={recording !== null}
        meta={meta}
        openingDate={openingDate}
        line={recording?.line}
        preset={recording?.preset}
        onClose={() => setRecording(null)}
        onSaved={() => {
          setRecording(null)
          toast.show('Recorded and matched')
          onChanged()
        }}
      />

      <Modal
        open={setting !== null}
        title="Set this line aside"
        onClose={() => setSetting(null)}
        footer={
          <>
            <Button variant="ghost" onClick={() => setSetting(null)} disabled={busy}>
              Cancel
            </Button>
            <Button onClick={setAside} loading={busy}>
              Set aside
            </Button>
          </>
        }
      >
        {setting && (
          <div className="space-y-4">
            <p className="text-sm">
              For a line that is not the firm’s movement to book: a transfer between its own accounts, or a line the bank shows twice. It stays on file with your reason, and can be brought back.
              Setting aside a real payment hides it from the book instead of fixing it: record it if it is real.
            </p>
            <p className="rounded-xl bg-muted px-3 py-2 text-sm">
              {day(setting.line_date)} · {setting.description} · <span className="font-semibold tabular-nums">{money(setting.amount)}</span>
            </p>
            <Field label="Why" required>
              <Textarea value={why} onChange={(e) => setWhy(e.target.value)} maxLength={200} placeholder="For example: transfer to the firm’s other account" />
            </Field>
            {whyError && <Alert variant="error">{whyError}</Alert>}
          </div>
        )}
      </Modal>
    </section>
  )
}
