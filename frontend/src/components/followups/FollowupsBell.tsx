import { useEffect, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { Bell, BriefcaseBusiness, Landmark, RotateCcw, X } from 'lucide-react'
import { useAuth } from '../../context/AuthContext'
import { useFollowups } from '../../context/FollowupsContext'
import { timeAgo } from '../../formatTime'
import type { Followup } from '../../types'
import { usePresence } from '../../hooks/usePresence'
import { Badge } from '../ui/Alert'
import { Button } from '../ui/Button'
import { Textarea } from '../ui/Field'
import { Tooltip } from '../ui/Tooltip'

/**
 * The bell at the top: what has to be done for opportunities that were won (create the case, record the EMD). It keeps showing them until the
 * case or the EMD exists, or someone says it is not required; "Not required" is the only way to make one go away without doing it.
 */
export function FollowupsBell() {
  const { user } = useAuth()
  const { open: waiting, dismissed, dismiss, reopen } = useFollowups()
  const navigate = useNavigate()
  const [shown, setShown] = useState(false)
  const [tab, setTab] = useState<'waiting' | 'dismissed'>('waiting')
  const [asking, setAsking] = useState<number | null>(null)
  const [note, setNote] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const box = useRef<HTMLDivElement>(null)
  const presence = usePresence(shown)

  useEffect(() => {
    if (!shown) return
    const onPointer = (event: PointerEvent) => {
      if (!box.current?.contains(event.target as Node)) setShown(false)
    }
    const onKey = (event: KeyboardEvent) => {
      if (event.key === 'Escape') setShown(false)
    }
    document.addEventListener('pointerdown', onPointer)
    document.addEventListener('keydown', onKey)
    return () => {
      document.removeEventListener('pointerdown', onPointer)
      document.removeEventListener('keydown', onKey)
    }
  }, [shown])

  if (!user?.can_ods_write) return null

  const go = (item: Followup) => {
    setShown(false)
    // The click is the person's decision to change records, so the "this changes live data" screen is not asked again.
    navigate(item.action.path, { state: { writeAck: true } })
  }

  const run = async (work: () => Promise<void>) => {
    setBusy(true)
    setError('')
    try {
      await work()
      setAsking(null)
      setNote('')
    } catch (e) {
      setError(e instanceof Error ? e.message : 'That did not work. Try again.')
    } finally {
      setBusy(false)
    }
  }

  const count = waiting.length
  return (
    <div ref={box} className="relative">
      <Tooltip label={count ? `${count} to do for won opportunities` : 'Nothing waiting for won opportunities'}>
        <button
          type="button"
          onClick={() => setShown((value) => !value)}
          aria-label={count ? `Notifications: ${count} waiting` : 'Notifications'}
          aria-haspopup="dialog"
          aria-expanded={shown}
          className="interactive relative inline-flex h-9 w-9 items-center justify-center rounded-lg text-[color:var(--color-text-muted)] hover:bg-muted hover:text-[color:var(--color-text)]"
        >
          <Bell className="h-4 w-4" />
          {count > 0 && (
            <span className="absolute -right-0.5 -top-0.5 flex h-4 min-w-4 items-center justify-center rounded-full bg-primary px-1 text-[10px] font-bold leading-none text-on-primary">
              {count > 9 ? '9+' : count}
            </span>
          )}
        </button>
      </Tooltip>

      {presence.present && (
        <div
          role="dialog"
          aria-label="Notifications"
          className={`${presence.leaving ? 'pop-out' : 'pop-in'} overlay absolute right-0 top-full z-50 mt-2 w-[min(24rem,calc(100vw-1.5rem))] rounded-xl border border-[color:var(--color-border)]`}
        >
          <div className="flex items-center gap-1 border-b border-[color:var(--color-border)] px-2 pt-2">
            {(['waiting', 'dismissed'] as const).map((id) => (
              <button
                key={id}
                type="button"
                onClick={() => setTab(id)}
                className={`rounded-t-md px-3 py-1.5 text-sm font-medium ${tab === id ? 'border-b-2 border-accent text-[color:var(--color-text)]' : 'text-[color:var(--color-text-muted)] hover:text-[color:var(--color-text)]'}`}
              >
                {id === 'waiting' ? `To do (${count})` : `Not required (${dismissed.length})`}
              </button>
            ))}
          </div>

          <div className="max-h-[min(28rem,70dvh)] overflow-y-auto p-2">
            {error && <p className="px-2 pb-2 text-xs text-negative">{error}</p>}

            {tab === 'waiting' && count === 0 && (
              <p className="px-3 py-6 text-center text-sm text-[color:var(--color-text-muted)]">
                Nothing waiting. When an opportunity is saved as won, you are asked here to create its case and record its EMD.
              </p>
            )}
            {tab === 'waiting' &&
              waiting.map((item) => (
                <div key={item.id} className="rounded-lg px-3 py-2.5 hover:bg-muted/60">
                  <div className="flex items-start gap-3">
                    <span className="mt-0.5 flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-accent-dim text-accent">
                      {item.kind === 'case' ? <BriefcaseBusiness className="h-4 w-4" /> : <Landmark className="h-4 w-4" />}
                    </span>
                    <div className="min-w-0 flex-1">
                      <p className="text-sm font-medium text-[color:var(--color-text)]">{item.title}</p>
                      <p className="t-caption mt-0.5">{item.message}</p>
                      <p className="t-caption mt-0.5 text-[color:var(--color-text-faint)]">
                        {item.tender_id ? `Tender ${item.tender_id} · ` : ''}
                        {item.place ? `${item.place} · ` : ''}
                        {timeAgo(item.created_timestamp)}
                      </p>
                      {asking === item.id ? (
                        <div className="mt-2 space-y-2">
                          <Textarea
                            autoFocus
                            rows={2}
                            maxLength={300}
                            value={note}
                            placeholder={item.kind === 'case' ? 'Why is no case needed? (optional)' : 'Why is no EMD needed? (optional)'}
                            onChange={(e) => setNote(e.target.value)}
                          />
                          <div className="flex gap-2">
                            <Button size="sm" loading={busy} onClick={() => void run(() => dismiss(item.id, note))}>
                              Not required
                            </Button>
                            <Button
                              size="sm"
                              variant="secondary"
                              onClick={() => {
                                setAsking(null)
                                setNote('')
                              }}
                            >
                              Keep reminding me
                            </Button>
                          </div>
                        </div>
                      ) : (
                        <div className="mt-2 flex flex-wrap gap-2">
                          <Button size="sm" onClick={() => go(item)}>
                            {item.action.label}
                          </Button>
                          <Button
                            size="sm"
                            variant="ghost"
                            onClick={() => {
                              setAsking(item.id)
                              setNote('')
                              setError('')
                            }}
                          >
                            <X className="h-3.5 w-3.5" /> {item.kind === 'case' ? 'No case needed' : 'No EMD needed'}
                          </Button>
                        </div>
                      )}
                    </div>
                  </div>
                </div>
              ))}

            {tab === 'dismissed' && dismissed.length === 0 && (
              <p className="px-3 py-6 text-center text-sm text-[color:var(--color-text-muted)]">
                Nothing has been marked as not required.
              </p>
            )}
            {tab === 'dismissed' &&
              dismissed.map((item) => (
                <div key={item.id} className="flex items-start gap-3 rounded-lg px-3 py-2.5 hover:bg-muted/60">
                  <div className="min-w-0 flex-1">
                    <p className="text-sm font-medium text-[color:var(--color-text)]">
                      {item.kind === 'case' ? 'No case needed' : 'No EMD needed'} <Badge>{item.opportunity_code}</Badge>
                    </p>
                    <p className="t-caption mt-0.5">{item.opportunity_name}</p>
                    <p className="t-caption mt-0.5 text-[color:var(--color-text-faint)]">
                      {item.resolved_by_name ? `By ${item.resolved_by_name}` : ''}
                      {item.resolved_timestamp ? ` · ${timeAgo(item.resolved_timestamp)}` : ''}
                      {item.resolution_note ? ` · “${item.resolution_note}”` : ''}
                    </p>
                  </div>
                  <Button size="sm" variant="ghost" loading={busy} onClick={() => void run(() => reopen(item.id))}>
                    <RotateCcw className="h-3.5 w-3.5" /> Remind me again
                  </Button>
                </div>
              ))}
          </div>
        </div>
      )}
    </div>
  )
}
