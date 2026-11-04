import { useCallback, useEffect, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { CheckCheck, ListChecks } from 'lucide-react'
import { tasksApi } from '../../api/client'
import { useTasks } from '../../context/TasksContext'
import { timeAgo } from '../../formatTime'
import { usePresence } from '../../hooks/usePresence'
import type { TaskInbox, TaskReminders } from '../../types'
import { errorText, formatDay } from '../../tasks/taskUi'
import { useOpenTask } from '../../tasks/useOpenTask'
import { Button } from '../ui/Button'
import { Tooltip } from '../ui/Tooltip'

/**
 * The bell for the task workspace: what happened on the tasks a person is part of (assigned, mentioned, review asked or decided, commented)
 * and the tasks of theirs that are late or due soon. Opening a notification opens its task.
 */
export function TasksBell() {
  const { me, refresh, version } = useTasks()
  const openTask = useOpenTask()
  const navigate = useNavigate()
  const [shown, setShown] = useState(false)
  const [tab, setTab] = useState<'inbox' | 'due'>('inbox')
  const [inbox, setInbox] = useState<TaskInbox | null>(null)
  const [due, setDue] = useState<TaskReminders | null>(null)
  const [error, setError] = useState('')
  const box = useRef<HTMLDivElement>(null)
  const presence = usePresence(shown)

  const load = useCallback(async () => {
    try {
      const [found, reminders] = await Promise.all([tasksApi.inbox(false), tasksApi.reminders()])
      setInbox(found)
      setDue(reminders)
      setError('')
    } catch (e) {
      setError(errorText(e, 'The notifications could not be loaded.'))
    }
  }, [])

  useEffect(() => {
    if (shown) void load()
  }, [shown, load, version])

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

  const count = me.unread + me.attention
  const open = async (key: string | null, id?: number) => {
    setShown(false)
    if (id !== undefined) {
      try {
        await tasksApi.markRead([id])
        void refresh()
      } catch {
        // Reading it again later is harmless; opening the task matters more.
      }
    }
    if (key) openTask(key)
  }
  const readAll = async () => {
    try {
      await tasksApi.markRead()
      await Promise.all([load(), refresh()])
    } catch (e) {
      setError(errorText(e))
    }
  }

  return (
    <div ref={box} className="relative">
      <Tooltip label={count ? `${me.unread} unread, ${me.attention} late or due today` : 'Nothing needs you in Tasks'}>
        <button
          type="button"
          onClick={() => setShown((value) => !value)}
          aria-label={count ? `Task notifications: ${me.unread} unread, ${me.attention} late or due today` : 'Task notifications'}
          aria-haspopup="dialog"
          aria-expanded={shown}
          className="interactive relative inline-flex h-9 w-9 items-center justify-center rounded-lg text-[color:var(--color-text-muted)] hover:bg-muted hover:text-[color:var(--color-text)]"
        >
          <ListChecks className="h-4 w-4" />
          {count > 0 && (
            <span className={`absolute -right-0.5 -top-0.5 flex h-4 min-w-4 items-center justify-center rounded-full px-1 text-[10px] font-bold leading-none ${me.overdue ? 'bg-negative text-on-negative' : 'bg-primary text-on-primary'}`}>
              {count > 9 ? '9+' : count}
            </span>
          )}
        </button>
      </Tooltip>

      {presence.present && (
        <div
          role="dialog"
          aria-label="Task notifications"
          className={`${presence.leaving ? 'pop-out' : 'pop-in'} overlay absolute right-0 top-full z-50 mt-2 w-[min(26rem,calc(100vw-1.5rem))] rounded-xl border border-[color:var(--color-border)]`}
        >
          <div className="flex items-center gap-1 border-b border-[color:var(--color-border)] px-2 pt-2">
            {(['inbox', 'due'] as const).map((id) => (
              <button
                key={id}
                type="button"
                onClick={() => setTab(id)}
                className={`rounded-t-md px-3 py-1.5 text-sm font-medium ${tab === id ? 'border-b-2 border-accent text-[color:var(--color-text)]' : 'text-[color:var(--color-text-muted)] hover:text-[color:var(--color-text)]'}`}
              >
                {id === 'inbox' ? `Notifications${me.unread ? ` (${me.unread})` : ''}` : `Due soon${due?.count ? ` (${due.count})` : ''}`}
              </button>
            ))}
            {tab === 'inbox' && me.unread > 0 && (
              <Button size="sm" variant="ghost" className="ml-auto mb-1" onClick={() => void readAll()}>
                <CheckCheck className="h-3.5 w-3.5" /> Mark all read
              </Button>
            )}
          </div>

          <div className="max-h-[min(28rem,70dvh)] overflow-y-auto p-2">
            {error && <p className="px-2 pb-2 text-xs text-negative">{error}</p>}

            {tab === 'inbox' && inbox && inbox.items.length === 0 && (
              <p className="px-3 py-6 text-center text-sm text-[color:var(--color-text-muted)]">Nothing yet. You are told here when a task is given to you, someone mentions you, or a review is asked or decided.</p>
            )}
            {tab === 'inbox' &&
              inbox?.items.map((item) => (
                <button
                  key={item.id}
                  type="button"
                  onClick={() => void open(item.task_key, item.id)}
                  className="interactive flex w-full items-start gap-2.5 rounded-lg px-3 py-2 text-left hover:bg-muted/60"
                >
                  <span className={`mt-1.5 h-2 w-2 shrink-0 rounded-full ${item.read ? 'bg-transparent' : 'bg-accent'}`} aria-label={item.read ? undefined : 'Unread'} />
                  <span className="min-w-0 flex-1">
                    <span className={`block text-sm ${item.read ? 'text-[color:var(--color-text-muted)]' : 'font-medium text-[color:var(--color-text)]'}`}>{item.text}</span>
                    <span className="t-caption mt-0.5 block text-[color:var(--color-text-faint)]">
                      {item.task_key ? `${item.task_key} · ` : ''}
                      {timeAgo(item.created)}
                    </span>
                  </span>
                </button>
              ))}

            {tab === 'due' && due && due.count === 0 && <p className="px-3 py-6 text-center text-sm text-[color:var(--color-text-muted)]">None of your tasks is late or due in the next few days.</p>}
            {tab === 'due' &&
              due &&
              (
                [
                  ['Overdue', due.overdue],
                  ['Due today', due.today],
                  ['Coming up', due.soon],
                ] as const
              ).map(
                ([title, list]) =>
                  list.length > 0 && (
                    <div key={title} className="mb-1">
                      <p className="eyebrow px-3 pb-1 pt-2">{title}</p>
                      {list.map((item) => (
                        <button key={item.key} type="button" onClick={() => void open(item.key)} className="interactive flex w-full items-center gap-2 rounded-lg px-3 py-2 text-left hover:bg-muted/60">
                          <span className="min-w-0 flex-1">
                            <span className="block truncate text-sm font-medium text-[color:var(--color-text)]">{item.title}</span>
                            <span className="t-caption text-[color:var(--color-text-faint)]">
                              {item.key} · {item.status}
                            </span>
                          </span>
                          <span className={`shrink-0 text-xs ${title === 'Overdue' ? 'font-semibold text-negative' : 'text-[color:var(--color-text-muted)]'}`}>{formatDay(item.due)}</span>
                        </button>
                      ))}
                    </div>
                  ),
              )}
          </div>

          <div className="border-t border-[color:var(--color-border)] p-2">
            <Button
              size="sm"
              variant="ghost"
              className="w-full"
              onClick={() => {
                setShown(false)
                navigate('/tasks/mine')
              }}
            >
              Open my work
            </Button>
          </div>
        </div>
      )}
    </div>
  )
}
