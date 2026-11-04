import { useCallback, useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { FolderKanban, Lock, Plus } from 'lucide-react'
import { tasksApi } from '../../api/client'
import { Alert, Badge } from '../../components/ui/Alert'
import { Button } from '../../components/ui/Button'
import { EmptyState, Skeleton } from '../../components/ui/EmptyState'
import { Field, Input, Select, Textarea } from '../../components/ui/Field'
import { Modal } from '../../components/ui/Modal'
import { useTasks } from '../../context/TasksContext'
import { timeAgo } from '../../formatTime'
import { errorText, Person } from '../../tasks/taskUi'
import type { TaskProjectSummary } from '../../types'

/** Every project the person can see, with how much is open and late in each. */
export function ProjectsPage() {
  const navigate = useNavigate()
  const { version } = useTasks()
  const [projects, setProjects] = useState<TaskProjectSummary[] | null>(null)
  const [archived, setArchived] = useState(false)
  const [error, setError] = useState('')
  const [creating, setCreating] = useState(false)
  const [key, setKey] = useState('')
  const [name, setName] = useState('')
  const [description, setDescription] = useState('')
  const [visibility, setVisibility] = useState('Company')
  const [review, setReview] = useState(false)
  const [busy, setBusy] = useState(false)
  const [formError, setFormError] = useState('')

  const load = useCallback(async () => {
    try {
      setProjects((await tasksApi.projects(archived)).projects)
      setError('')
    } catch (e) {
      setError(errorText(e, 'The projects could not be loaded.'))
    }
  }, [archived])

  useEffect(() => {
    void load()
  }, [load, version])

  const create = async () => {
    setBusy(true)
    setFormError('')
    try {
      const made = await tasksApi.createProject({ key: key.trim().toUpperCase(), name: name.trim(), description: description.trim() || undefined, visibility, require_review: review })
      setCreating(false)
      navigate(`/tasks/projects/${made.key}`)
    } catch (e) {
      setFormError(errorText(e))
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="space-y-5">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <label className="flex items-center gap-2 text-sm text-[color:var(--color-text-muted)]">
          <input type="checkbox" className="h-4 w-4 accent-[color:var(--color-primary)]" checked={archived} onChange={(e) => setArchived(e.target.checked)} /> Show archived projects
        </label>
        <Button
          onClick={() => {
            setKey('')
            setName('')
            setDescription('')
            setVisibility('Company')
            setReview(false)
            setFormError('')
            setCreating(true)
          }}
        >
          <Plus className="h-4 w-4" /> New project
        </Button>
      </div>

      {error && <Alert variant="error">{error}</Alert>}
      {!projects && !error && (
        <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
          {[0, 1, 2].map((i) => (
            <Skeleton key={i} className="h-36" />
          ))}
        </div>
      )}
      {projects && projects.length === 0 && (
        <EmptyState icon={FolderKanban} title="No projects yet" action={<Button onClick={() => setCreating(true)}>New project</Button>}>
          A project holds the tasks of one piece of work, such as a client, a department or a recurring job. Make one, add people to it and start giving out tasks.
        </EmptyState>
      )}

      <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
        {projects?.map((p) => (
          <button key={p.key} type="button" onClick={() => navigate(`/tasks/projects/${p.key}`)} className="panel interactive space-y-3 text-left hover:shadow-raised">
            <div className="flex items-start gap-3">
              <span className="flex h-10 w-10 shrink-0 items-center justify-center rounded-lg bg-accent-dim text-xs font-bold text-accent">{p.key}</span>
              <div className="min-w-0 flex-1">
                <p className="flex items-center gap-2 truncate text-sm font-semibold text-[color:var(--color-text)]">
                  <span className="truncate">{p.name}</span>
                  {p.visibility === 'Private' && <Lock className="h-3.5 w-3.5 shrink-0 text-[color:var(--color-text-faint)]" aria-label="Private" />}
                  {p.state === 'Archived' && <Badge>Archived</Badge>}
                </p>
                {p.description && <p className="line-clamp-2 text-xs text-[color:var(--color-text-muted)]">{p.description}</p>}
              </div>
            </div>
            <dl className="grid grid-cols-4 gap-2 text-center">
              {[
                ['Open', p.open_tasks ?? 0, ''],
                ['Mine', p.my_open_tasks ?? 0, ''],
                ['Late', p.overdue_tasks ?? 0, 'text-negative'],
                ['Done', p.done_tasks ?? 0, 'text-positive'],
              ].map(([label, value, tone]) => (
                <div key={String(label)}>
                  <dd className={`text-lg font-semibold tabular-nums ${Number(value) && tone ? String(tone) : 'text-[color:var(--color-text)]'}`}>{value}</dd>
                  <dt className="t-caption text-[color:var(--color-text-muted)]">{label}</dt>
                </div>
              ))}
            </dl>
            <div className="flex items-center justify-between gap-2 text-xs text-[color:var(--color-text-faint)]">
              <Person person={p.lead} size="xs" />
              <span>{p.last_activity ? `Active ${timeAgo(p.last_activity)}` : `${p.members ?? 0} people`}</span>
            </div>
          </button>
        ))}
      </div>

      <Modal
        open={creating}
        onClose={() => setCreating(false)}
        title="New project"
        footer={
          <>
            <Button variant="secondary" onClick={() => setCreating(false)}>
              Cancel
            </Button>
            <Button loading={busy} disabled={!key.trim() || !name.trim()} onClick={() => void create()}>
              Create project
            </Button>
          </>
        }
      >
        <form
          className="space-y-4"
          onSubmit={(event) => {
            event.preventDefault()
            if (key.trim() && name.trim()) void create()
          }}
        >
          {formError && <Alert variant="error">{formError}</Alert>}
          <div className="grid gap-4 sm:grid-cols-[8rem_1fr]">
            <Field label="Key" required hint="2–10 letters. Tasks are numbered KEY-1, KEY-2…">
              <Input value={key} maxLength={10} onChange={(e) => setKey(e.target.value.toUpperCase().replace(/[^A-Z0-9]/g, ''))} placeholder="OPS" />
            </Field>
            <Field label="Name" required>
              <Input autoFocus value={name} maxLength={200} onChange={(e) => setName(e.target.value)} placeholder="Operations" />
            </Field>
          </div>
          <Field label="Description">
            <Textarea rows={3} value={description} maxLength={5000} onChange={(e) => setDescription(e.target.value)} />
          </Field>
          <Field label="Who can see it">
            <Select value={visibility} onChange={(e) => setVisibility(e.target.value)} aria-label="Who can see it">
              <option value="Company">The whole company</option>
              <option value="Private">Only the people I add</option>
            </Select>
          </Field>
          <label className="flex items-start gap-2.5 text-sm">
            <input type="checkbox" className="mt-0.5 h-4 w-4 accent-[color:var(--color-primary)]" checked={review} onChange={(e) => setReview(e.target.checked)} />
            <span>
              <span className="font-medium text-[color:var(--color-text)]">Every task must be reviewed before it is done</span>
              <span className="block text-xs text-[color:var(--color-text-muted)]">You become the project’s manager and can change all of this later.</span>
            </span>
          </label>
        </form>
      </Modal>
    </div>
  )
}
