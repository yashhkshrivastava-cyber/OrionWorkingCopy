import { useCallback, useEffect, useState } from 'react'
import { Laptop, LogOut } from 'lucide-react'
import { api } from '../api/client'
import type { UserSession } from '../types'
import { formatDateTime, timeAgo } from '../formatTime'
import { Card, CardHeader } from './ui/Card'
import { Button } from './ui/Button'
import { Badge } from './ui/Alert'
import { useToast } from './ui/Toast'

/**
 * Where this person is signed in. A session is ended on the server, so "Sign out" here really cuts that browser off, not just
 * hides it: use it for a shared PC, a lost phone, or any place that should not still have the workspace open.
 */
export function SignedInDevices() {
  const toast = useToast()
  const [sessions, setSessions] = useState<UserSession[] | null>(null)
  const [busy, setBusy] = useState<number | 'others' | null>(null)
  const [error, setError] = useState('')

  const load = useCallback(async () => {
    try {
      setSessions((await api.mySessions()).sessions)
      setError('')
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not load your devices')
    }
  }, [])

  useEffect(() => {
    void load()
  }, [load])

  const end = async (id: number) => {
    setBusy(id)
    try {
      await api.endSession(id)
      toast.show('Signed out of that device.')
      await load()
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not sign that device out')
    } finally {
      setBusy(null)
    }
  }

  const endOthers = async () => {
    setBusy('others')
    try {
      const { ended } = await api.signOutOtherDevices()
      toast.show(ended === 1 ? 'Signed out of 1 other device.' : `Signed out of ${ended} other devices.`)
      await load()
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not sign the other devices out')
    } finally {
      setBusy(null)
    }
  }

  const others = (sessions ?? []).filter((item) => !item.current)

  return (
    <Card accent="violet">
      <CardHeader
        title="Where you are signed in"
        subtitle="Sign out of any place you do not recognise, or that should not still have Orion open."
        action={<Laptop className="h-4 w-4 text-[color:var(--color-text-faint)]" aria-hidden="true" />}
      />
      {error && (
        <p role="alert" className="mb-3 text-xs text-negative">
          {error}
        </p>
      )}
      {sessions === null && !error && <p className="text-sm text-[color:var(--color-text-muted)]">Loading…</p>}
      <ul className="divide-y divide-[color:var(--color-border)]">
        {(sessions ?? []).map((item) => (
          <li key={item.id} className="flex flex-wrap items-center justify-between gap-3 py-3 first:pt-0 last:pb-0">
            <div className="min-w-0">
              <p className="flex flex-wrap items-center gap-2 text-sm font-medium text-[color:var(--color-text)]">
                {item.device}
                {item.current && <Badge variant="emerald">This device</Badge>}
              </p>
              <p className="mt-0.5 text-xs text-[color:var(--color-text-muted)]">
                {item.current ? 'Active now' : `Last active ${timeAgo(item.last_seen)}`}
                {item.ip ? ` · ${item.ip}` : ''} · signed in {formatDateTime(item.created)}
              </p>
            </div>
            {!item.current && (
              <Button size="sm" variant="secondary" loading={busy === item.id} disabled={busy !== null} onClick={() => end(item.id)}>
                <LogOut className="h-3.5 w-3.5" aria-hidden="true" />
                Sign out
              </Button>
            )}
          </li>
        ))}
      </ul>
      {others.length > 1 && (
        <div className="mt-4">
          <Button size="sm" variant="ghost" loading={busy === 'others'} disabled={busy !== null} onClick={endOthers}>
            Sign out of all other devices
          </Button>
        </div>
      )}
    </Card>
  )
}
