import { useCallback, useEffect, useState } from 'react'
import { aiApi } from '../../api/client'
import { useAssistant } from '../../ai/AssistantContext'
import { Alert } from '../ui/Alert'
import { RoutingSettings } from './RoutingSettings'
import { Button } from '../ui/Button'
import { Card, CardHeader } from '../ui/Card'
import { Switch } from '../ui/Field'
import { useToast } from '../ui/Toast'
import type { AiAuditRow, AiSettings as Settings } from '../../types'

const WHAT: Record<string, string> = {
  ok: 'Done',
  pending: 'Waiting for you',
  cancelled: 'Cancelled by you',
  denied: 'Not allowed',
  refused: 'Refused',
  invalid: 'Bad request',
  error: 'Failed',
}

function ActivityList({ rows }: { rows: AiAuditRow[] }) {
  if (rows.length === 0) return <p className="t-caption">Nothing yet. What the Copilot does for you will be listed here.</p>
  return (
    <div className="overflow-x-auto">
      <table className="w-full min-w-[30rem] border-collapse text-left text-[13px]">
        <thead>
          <tr className="text-[11px] text-[color:var(--color-text-muted)]">
            <th className="py-1.5 pr-3 font-semibold">When</th>
            <th className="py-1.5 pr-3 font-semibold">What</th>
            <th className="py-1.5 pr-3 font-semibold">Result</th>
          </tr>
        </thead>
        <tbody>
          {rows.slice(0, 30).map((row) => (
            <tr key={row.id} className="border-t border-[color:var(--color-border)]">
              <td className="t-num whitespace-nowrap py-1.5 pr-3 text-[color:var(--color-text-muted)]">
                {new Date(row.at).toLocaleString('en-IN', { day: 'numeric', month: 'short', hour: 'numeric', minute: '2-digit' })}
              </td>
              <td className="max-w-[20rem] truncate py-1.5 pr-3" title={row.summary ?? row.tool}>
                {row.summary || row.tool.replace(/_/g, ' ')}
                {row.confirmation_required && <span className="ml-1.5 text-[11px] text-[color:var(--color-text-faint)]">needed confirmation</span>}
              </td>
              <td className={`whitespace-nowrap py-1.5 pr-3 font-medium ${row.status === 'ok' ? 'text-positive' : row.status === 'pending' || row.status === 'cancelled' ? '' : 'text-negative'}`}>
                {WHAT[row.status] ?? row.status}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

/** Settings → AI Copilot: what it may do for you, what is kept, and a record of what it has done. */
export function AiSettings() {
  const toast = useToast()
  const { status, reloadStatus, newChat } = useAssistant()
  const [error, setError] = useState('')
  const [clearing, setClearing] = useState(false)
  const [sure, setSure] = useState(false)
  const [activity, setActivity] = useState<AiAuditRow[] | null>(null)

  const loadActivity = useCallback(async () => {
    try {
      setActivity((await aiApi.audit(true)).audit)
    } catch {
      setActivity([])
    }
  }, [])

  useEffect(() => {
    void loadActivity()
  }, [loadActivity])

  const change = async (patch: Partial<Settings>) => {
    setError('')
    try {
      await aiApi.saveSettings(patch)
      await reloadStatus()
    } catch (err) {
      setError(err instanceof Error ? err.message : 'That could not be saved.')
    }
  }

  const clear = async () => {
    setClearing(true)
    try {
      const { deleted } = await aiApi.clearHistory()
      newChat()
      setSure(false)
      toast.show(deleted ? `Deleted ${deleted} conversation${deleted === 1 ? '' : 's'}.` : 'There was nothing to delete.')
    } catch (err) {
      setError(err instanceof Error ? err.message : 'That could not be done.')
    } finally {
      setClearing(false)
    }
  }

  if (!status) return <p className="t-caption">Loading…</p>
  const settings = status.settings

  return (
    <div className="grid max-w-3xl gap-5">
      {error && (
        <Alert variant="error" onDismiss={() => setError('')}>
          {error}
        </Alert>
      )}
      <Card accent="teal">
        <CardHeader title="AI Copilot" subtitle="An assistant that reads your data and can do things in Orion for you." />
        <div className="space-y-5">
          <Switch label="Use the Copilot" hint="Turn it off and the button, shortcuts and suggestions disappear for you." checked={settings.enabled} onChange={(enabled) => void change({ enabled })} />
          <Switch
            label="Remember my conversations"
            hint="Saved so you can pick up where you stopped. Turn off and nothing is stored on the server (the conversation lasts until you leave the page)."
            checked={settings.keep_history}
            onChange={(keep_history) => void change({ keep_history })}
            disabled={!settings.enabled}
          />
          <Switch
            label="Show what is worth a look"
            hint="A few findings from your data when you open the Copilot, such as an overdue balance or a drop in revenue."
            checked={settings.show_insights}
            onChange={(show_insights) => void change({ show_insights })}
            disabled={!settings.enabled}
          />
        </div>
        <p className="t-caption mt-5 border-t border-[color:var(--color-border)] pt-3">
          Today you have asked {status.usage_today.requests} of {status.usage_today.limit} questions.
        </p>
      </Card>

      <RoutingSettings />

      <Card accent="blue">
        <CardHeader title="Your data and privacy" />
        <ul className="t-small list-disc space-y-1.5 pl-5 text-[color:var(--color-text-muted)]">
          <li>The Copilot can see only what you can see, and do only what you are allowed to do. It cannot give you more access.</li>
          <li>Most questions are answered by Orion itself, and the rest by an AI model running on this computer. Neither sends anything out.</li>
          <li>A cloud AI service is used only if your organisation has allowed it and you have too, only after the local AI could not answer, and never for private or restricted requests. Each answer says where it was made.</li>
          <li>It never changes anything without showing you first and waiting for you to confirm. Deleting is always confirmed.</li>
          <li>Personal details such as bank and identity numbers are never given to it.</li>
          <li>Everything it looks up or does for you is recorded below, and administrators can review the record.</li>
        </ul>
        <div className="mt-4 flex flex-wrap items-center gap-2 border-t border-[color:var(--color-border)] pt-4">
          {sure ? (
            <>
              <span className="text-sm font-medium text-negative">Delete all your saved conversations?</span>
              <Button variant="danger" size="sm" loading={clearing} onClick={() => void clear()}>
                Delete them
              </Button>
              <Button variant="ghost" size="sm" disabled={clearing} onClick={() => setSure(false)}>
                Keep them
              </Button>
            </>
          ) : (
            <Button variant="secondary" size="sm" onClick={() => setSure(true)}>
              Clear my conversation history
            </Button>
          )}
        </div>
      </Card>

      <Card accent="amber">
        <CardHeader title="What the Copilot has done for you" subtitle="Your most recent activity." />
        {activity ? <ActivityList rows={activity} /> : <p className="t-caption">Loading…</p>}
      </Card>

      <Card accent="violet">
        <CardHeader title="Shortcuts" />
        <dl className="t-small grid grid-cols-[auto_1fr] gap-x-6 gap-y-2">
          {[
            ['Ctrl + J', 'Open or close the Copilot'],
            ['Ctrl + K', 'Ask anything, or jump to a page'],
            ['Enter', 'Send your message'],
            ['Shift + Enter', 'Start a new line'],
            ['Esc', 'Stop an answer that is being written'],
          ].map(([keys, what]) => (
            <div key={keys} className="contents">
              <dt>
                <kbd className="rounded border border-[color:var(--color-border-strong)] bg-muted px-1.5 py-0.5 text-xs font-medium">{keys}</kbd>
              </dt>
              <dd className="text-[color:var(--color-text-muted)]">{what}</dd>
            </div>
          ))}
        </dl>
      </Card>

    </div>
  )
}
