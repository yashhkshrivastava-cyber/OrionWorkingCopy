import { useCallback, useEffect, useState } from 'react'
import { Bell, CheckCheck } from 'lucide-react'
import { tasksApi } from '../../api/client'
import { Alert } from '../../components/ui/Alert'
import { Button } from '../../components/ui/Button'
import { EmptyState } from '../../components/ui/EmptyState'
import { useTasks } from '../../context/TasksContext'
import { formatDateTime, timeAgo } from '../../formatTime'
import { errorText, Person } from '../../tasks/taskUi'
import { useOpenTask } from '../../tasks/useOpenTask'
import type { TaskNotification } from '../../types'

/** Everything that was said to this person about tasks, newest first. Opening one marks it read and opens the task. */
export function InboxPage() {
  const { refresh, version } = useTasks()
  const open = useOpenTask()
  const [items, setItems] = useState<TaskNotification[] | null>(null)
  const [more, setMore] = useState(false)
  const [unreadOnly, setUnreadOnly] = useState(false)
  const [error, setError] = useState('')

  const load = useCallback(async () => {
    try {
      const found = await tasksApi.inbox(unreadOnly)
      setItems(found.items)
      setMore(found.more)
      setError('')
    } catch (e) {
      setError(errorText(e, 'The notifications could not be loaded.'))
    }
  }, [unreadOnly])

  useEffect(() => {
    void load()
  }, [load, version])

  const loadMore = async () => {
    if (!items?.length) return
    try {
      const found = await tasksApi.inbox(unreadOnly, items[items.length - 1].id)
      setItems([...items, ...found.items])
      setMore(found.more)
    } catch (e) {
      setError(errorText(e))
    }
  }

  const read = async (ids?: number[]) => {
    try {
      await tasksApi.markRead(ids)
      await Promise.all([load(), refresh()])
    } catch (e) {
      setError(errorText(e))
    }
  }

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <label className="flex items-center gap-2 text-sm text-[color:var(--color-text-muted)]">
          <input type="checkbox" className="h-4 w-4 accent-[color:var(--color-primary)]" checked={unreadOnly} onChange={(e) => setUnreadOnly(e.target.checked)} /> Unread only
        </label>
        <Button size="sm" variant="secondary" onClick={() => void read()}>
          <CheckCheck className="h-4 w-4" /> Mark all read
        </Button>
      </div>
      {error && <Alert variant="error">{error}</Alert>}
      {items && items.length === 0 && (
        <EmptyState icon={Bell} title={unreadOnly ? 'Nothing unread' : 'No notifications yet'}>
          You are told here when a task is given to you, someone mentions you or comments on a task you follow, a review is asked or decided, or you are added to a project.
        </EmptyState>
      )}
      {items && items.length > 0 && (
        <ul className="panel divide-y divide-[color:var(--color-border)] !p-0">
          {items.map((item) => (
            <li key={item.id}>
              <button
                type="button"
                onClick={() => {
                  if (!item.read) void read([item.id])
                  if (item.task_key) open(item.task_key)
                }}
                className="interactive flex w-full items-start gap-3 px-4 py-3 text-left hover:bg-muted/50"
              >
                <span className={`mt-2 h-2 w-2 shrink-0 rounded-full ${item.read ? 'bg-transparent' : 'bg-accent'}`} aria-label={item.read ? undefined : 'Unread'} />
                <Person person={item.actor} name={false} />
                <span className="min-w-0 flex-1">
                  <span className={`block text-sm ${item.read ? 'text-[color:var(--color-text-muted)]' : 'font-medium text-[color:var(--color-text)]'}`}>{item.text}</span>
                  <span className="t-caption block text-[color:var(--color-text-faint)]" title={formatDateTime(item.created)}>
                    {item.task_key ? `${item.task_key}${item.task_title ? ` · ${item.task_title}` : ''} · ` : ''}
                    {timeAgo(item.created)}
                  </span>
                </span>
              </button>
            </li>
          ))}
        </ul>
      )}
      {more && (
        <div className="flex justify-center">
          <Button variant="secondary" onClick={() => void loadMore()}>
            Show older
          </Button>
        </div>
      )}
    </div>
  )
}
