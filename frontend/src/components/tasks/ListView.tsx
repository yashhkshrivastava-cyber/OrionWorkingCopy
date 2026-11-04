import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { tasksApi } from '../../api/client'
import { useTasks } from '../../context/TasksContext'
import { formatDay, formatMinutes, errorText } from '../../tasks/taskUi'
import { useOpenTask } from '../../tasks/useOpenTask'
import type { TaskCard, TaskFilters, TaskListResult } from '../../types'
import { Alert } from '../ui/Alert'
import { Button } from '../ui/Button'
import { DataTable } from '../ui/DataTable'

const COLUMNS = ['Key', 'Title', 'Type', 'Priority', 'Status', 'Assignee', 'Reviewer', 'Due', 'Estimate', 'Logged', 'Sprint', 'Labels', 'Updated']
const SORT_OF: Record<string, string> = { Key: 'key', Title: 'title', Priority: 'priority', Status: 'status', Assignee: 'assignee', Due: 'due', Updated: 'updated' }
const PAGE = 100

function row(task: TaskCard): Record<string, unknown> {
  return {
    Key: task.key,
    Title: task.title,
    Type: task.type,
    Priority: task.priority,
    Status: task.status.name,
    Assignee: task.assignee?.display_name ?? '',
    Reviewer: task.reviewer?.display_name ?? '',
    Due: task.due_date ? `${formatDay(task.due_date)}${task.overdue && task.status.category !== 'done' ? ' (overdue)' : ''}` : '',
    Estimate: task.estimate_minutes ? formatMinutes(task.estimate_minutes) : '',
    Logged: task.spent_minutes ? formatMinutes(task.spent_minutes) : '',
    Sprint: task.sprint?.name ?? '',
    Labels: task.labels.join(', '),
    Updated: formatDay(task.updated),
  }
}

/** Every task of the project as a table: sort by a column, filter any column from its header, and click a row to open the task. */
export function ListView({ project, filters }: { project: string; filters: TaskFilters }) {
  const { version } = useTasks()
  const open = useOpenTask()
  const [data, setData] = useState<TaskListResult | null>(null)
  const [error, setError] = useState('')
  const [offset, setOffset] = useState(0)
  const [sort, setSort] = useState('Updated')
  const [dir, setDir] = useState<'asc' | 'desc'>('desc')
  const [includeDone, setIncludeDone] = useState(true)
  const filterKey = JSON.stringify(filters)
  const latest = useRef(0)

  useEffect(() => setOffset(0), [filterKey, project, sort, dir, includeDone])

  const load = useCallback(async () => {
    const ticket = ++latest.current
    try {
      const found = await tasksApi.list({ ...JSON.parse(filterKey), project, limit: String(PAGE), offset: String(offset), sort: SORT_OF[sort] ?? 'updated', dir, include_archived: 'true', ...(includeDone ? {} : { open: 'true' }) })
      if (ticket === latest.current) {
        setData(found)
        setError('')
      }
    } catch (e) {
      if (ticket === latest.current) setError(errorText(e, 'The tasks could not be loaded.'))
    }
  }, [project, filterKey, offset, sort, dir, includeDone])

  useEffect(() => {
    void load()
  }, [load, version])

  const rows = useMemo(() => (data?.tasks ?? []).map(row), [data])

  if (error && !data) return <Alert variant="error">{error}</Alert>
  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <p className="t-small text-[color:var(--color-text-muted)]">
          {data ? `${data.total} task${data.total === 1 ? '' : 's'}` : 'Loading…'}
          {data && data.total > PAGE ? ` · showing ${offset + 1}–${Math.min(offset + PAGE, data.total)}` : ''}
        </p>
        <label className="flex items-center gap-2 text-sm text-[color:var(--color-text-muted)]">
          <input type="checkbox" className="h-4 w-4 accent-[color:var(--color-primary)]" checked={includeDone} onChange={(e) => setIncludeDone(e.target.checked)} /> Show finished
        </label>
      </div>
      {error && <Alert variant="error">{error}</Alert>}
      <DataTable
        columns={COLUMNS}
        rows={rows}
        allColumns
        filterable
        compact
        emptyMessage="No task matches."
        sort={sort}
        dir={dir}
        onSort={(column) => {
          if (!SORT_OF[column]) return
          if (column === sort) setDir((d) => (d === 'asc' ? 'desc' : 'asc'))
          else {
            setSort(column)
            setDir('asc')
          }
        }}
        onRowClick={(r) => open(String(r.Key))}
        rowHint="Open the task"
      />
      {data && data.total > PAGE && (
        <div className="flex justify-end gap-2">
          <Button size="sm" variant="secondary" disabled={offset === 0} onClick={() => setOffset((o) => Math.max(0, o - PAGE))}>
            Previous
          </Button>
          <Button size="sm" variant="secondary" disabled={offset + PAGE >= data.total} onClick={() => setOffset((o) => o + PAGE)}>
            Next
          </Button>
        </div>
      )}
    </div>
  )
}
