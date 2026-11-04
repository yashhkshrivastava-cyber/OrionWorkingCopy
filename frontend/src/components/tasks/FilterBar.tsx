import { useCallback, useEffect, useState } from 'react'
import { BookmarkPlus, Search, X } from 'lucide-react'
import { tasksApi } from '../../api/client'
import { errorText, KINDS, PRIORITIES } from '../../tasks/taskUi'
import type { TaskFilters, TaskPersonRow, TaskSavedFilter } from '../../types'
import { Button } from '../ui/Button'
import { Select } from '../ui/Field'

const SHARED = 'h-9 !min-h-0 !py-0 text-sm'

/** The narrowing controls over a project's board, list and calendar, and the views a person (or the team) has saved. */
export function FilterBar({
  value,
  onChange,
  people,
  project,
  canShare,
  onError,
}: {
  value: TaskFilters
  onChange: (next: TaskFilters) => void
  people: TaskPersonRow[]
  project: string
  canShare: boolean
  onError: (message: string) => void
}) {
  const [saved, setSaved] = useState<TaskSavedFilter[]>([])

  const load = useCallback(() => {
    tasksApi
      .filters(project)
      .then((found) => setSaved(found.filters))
      .catch(() => setSaved([]))
  }, [project])
  useEffect(load, [load])

  const set = (patch: Partial<TaskFilters>) => {
    const next: Record<string, string | undefined> = { ...value, ...patch }
    for (const key of Object.keys(next)) if (!next[key]) delete next[key]
    onChange(next as TaskFilters)
  }
  const active = Object.keys(value).length > 0

  const saveCurrent = async () => {
    const name = window.prompt('Name this view')
    if (!name?.trim()) return
    const share = canShare && window.confirm('Share it with everyone in the project?\n\nOK shares it, Cancel keeps it for you only.')
    try {
      setSaved((await tasksApi.saveFilter({ name: name.trim(), definition: { ...value }, project, shared: share })).filters)
    } catch (e) {
      onError(errorText(e))
    }
  }

  return (
    <div className="flex flex-wrap items-center gap-2">
      <div className="relative min-w-40 flex-1 sm:max-w-64">
        <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-[color:var(--color-text-faint)]" />
        <input
          value={value.q ?? ''}
          onChange={(e) => set({ q: e.target.value })}
          placeholder="Filter by words"
          aria-label="Filter by words"
          className="h-9 w-full rounded-lg border border-[color:var(--color-border-strong)] bg-surface pl-9 pr-3 text-sm text-[color:var(--color-text)] placeholder:text-[color:var(--color-text-faint)] focus:border-accent focus:ring-[3px] focus:ring-[color:var(--orion-ring)]"
        />
      </div>
      <Select className={`${SHARED} !w-auto`} value={value.assignee ?? ''} onChange={(e) => set({ assignee: e.target.value })} aria-label="Assignee">
        <option value="">Anyone</option>
        <option value="me">Me</option>
        <option value="none">Unassigned</option>
        {people.map((p) => (
          <option key={p.id} value={p.id}>
            {p.display_name}
          </option>
        ))}
      </Select>
      <Select className={`${SHARED} !w-auto`} value={value.priority ?? ''} onChange={(e) => set({ priority: e.target.value })} aria-label="Priority">
        <option value="">Any priority</option>
        {PRIORITIES.map((p) => (
          <option key={p}>{p}</option>
        ))}
      </Select>
      <Select className={`${SHARED} !w-auto`} value={value.type ?? ''} onChange={(e) => set({ type: e.target.value })} aria-label="Type">
        <option value="">Any type</option>
        {KINDS.map((k) => (
          <option key={k}>{k}</option>
        ))}
      </Select>
      <Select className={`${SHARED} !w-auto`} value={value.due ?? ''} onChange={(e) => set({ due: e.target.value })} aria-label="Due">
        <option value="">Any due date</option>
        <option value="overdue">Overdue</option>
        <option value="today">Due today</option>
        <option value="week">Due this week</option>
        <option value="none">No due date</option>
      </Select>
      {saved.length > 0 && (
        <Select
          className={`${SHARED} !w-auto`}
          value=""
          aria-label="Saved views"
          onChange={(e) => {
            const found = saved.find((s) => String(s.id) === e.target.value)
            if (found) onChange(Object.fromEntries(Object.entries(found.definition).map(([k, v]) => [k, String(v)])) as TaskFilters)
          }}
        >
          <option value="">Saved views</option>
          {saved.map((s) => (
            <option key={s.id} value={s.id}>
              {s.name}
              {s.shared ? ' (shared)' : ''}
            </option>
          ))}
        </Select>
      )}
      {active && (
        <>
          <Button size="sm" variant="ghost" onClick={() => onChange({})}>
            <X className="h-3.5 w-3.5" /> Clear
          </Button>
          <Button size="sm" variant="ghost" onClick={() => void saveCurrent()}>
            <BookmarkPlus className="h-3.5 w-3.5" /> Save view
          </Button>
        </>
      )}
      {saved.some((s) => s.mine) && active === false && (
        <Button
          size="sm"
          variant="ghost"
          onClick={async () => {
            const mine = saved.filter((s) => s.mine)
            const pick = window.prompt(`Delete which saved view?\n${mine.map((s) => s.name).join('\n')}`)
            const found = mine.find((s) => s.name.toLowerCase() === pick?.trim().toLowerCase())
            if (!found) return
            try {
              setSaved((await tasksApi.deleteFilter(found.id)).filters)
            } catch (e) {
              onError(errorText(e))
            }
          }}
        >
          Delete a view
        </Button>
      )}
    </div>
  )
}
