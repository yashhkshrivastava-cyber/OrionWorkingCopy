import { useState } from 'react'
import { Archive, ArchiveRestore, ArrowDown, ArrowUp, Plus, Trash2, UserPlus, X } from 'lucide-react'
import { tasksApi } from '../../api/client'
import { CATEGORY_LABEL, errorText, Person } from '../../tasks/taskUi'
import { useTaskPeople } from '../../tasks/useTaskPeople'
import type { ProjectRole, StatusCategory, TaskProject, TaskStatus } from '../../types'
import { Alert } from '../ui/Alert'
import { Button } from '../ui/Button'
import { Field, Input, Select, Textarea } from '../ui/Field'
import { Modal } from '../ui/Modal'
import { PersonSelect } from './PersonSelect'

const CATEGORIES: StatusCategory[] = ['todo', 'doing', 'review', 'done']

/** How a project is run: its details, who is in it and what they may do, and the steps (statuses) a task goes through. For the project's managers. */
export function ProjectSettings({ project, onChanged }: { project: TaskProject; onChanged: (next: TaskProject) => void }) {
  const people = useTaskPeople(project.key)
  const everyone = useTaskPeople(null)
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')
  const [name, setName] = useState(project.name)
  const [description, setDescription] = useState(project.description ?? '')
  const [newMember, setNewMember] = useState<number | null>(null)
  const [newRole, setNewRole] = useState<ProjectRole>('Member')
  const [newStatus, setNewStatus] = useState('')
  const [newCategory, setNewCategory] = useState<StatusCategory>('doing')
  const [removing, setRemoving] = useState<TaskStatus | null>(null)
  const [moveTo, setMoveTo] = useState('')
  const archived = project.state === 'Archived'

  const run = async (work: () => Promise<void>, ok?: string) => {
    setError('')
    setNotice('')
    try {
      await work()
      if (ok) setNotice(ok)
      return true
    } catch (e) {
      setError(errorText(e))
      return false
    }
  }
  const refresh = async () => onChanged(await tasksApi.project(project.key))

  const memberIds = new Set(project.members.map((m) => m.id))
  const candidates = (project.visibility === 'Private' ? everyone : everyone).filter((p) => !memberIds.has(p.id))

  return (
    <div className="space-y-8">
      {error && (
        <Alert variant="error" onDismiss={() => setError('')}>
          {error}
        </Alert>
      )}
      {notice && (
        <Alert variant="success" onDismiss={() => setNotice('')}>
          {notice}
        </Alert>
      )}

      <section className="panel space-y-4">
        <h3 className="t-h3">Details</h3>
        <div className="grid gap-4 sm:grid-cols-2">
          <Field label="Name">
            <Input value={name} maxLength={200} onChange={(e) => setName(e.target.value)} disabled={archived} />
          </Field>
          <Field label="Who can see it" hint={project.visibility === 'Company' ? 'Everyone who signs in can see the project and add tasks.' : 'Only the people listed below can see it.'}>
            <Select
              value={project.visibility}
              disabled={archived}
              aria-label="Who can see it"
              onChange={(e) => void run(async () => onChanged(await tasksApi.updateProject(project.key, { visibility: e.target.value })), 'Saved.')}
            >
              <option value="Company">The whole company</option>
              <option value="Private">Only its members</option>
            </Select>
          </Field>
        </div>
        <Field label="Description">
          <Textarea rows={3} value={description} maxLength={5000} onChange={(e) => setDescription(e.target.value)} disabled={archived} />
        </Field>
        <label className="flex items-start gap-2.5 text-sm">
          <input
            type="checkbox"
            className="mt-0.5 h-4 w-4 accent-[color:var(--color-primary)]"
            checked={project.require_review}
            disabled={archived}
            onChange={(e) => void run(async () => onChanged(await tasksApi.updateProject(project.key, { require_review: e.target.checked })), 'Saved.')}
          />
          <span>
            <span className="font-medium text-[color:var(--color-text)]">Every task must be reviewed before it is done</span>
            <span className="block text-xs text-[color:var(--color-text-muted)]">A task can then only be finished by a reviewer approving it.</span>
          </span>
        </label>
        {!archived && (
          <div>
            <Button
              loading={false}
              disabled={name === project.name && description === (project.description ?? '')}
              onClick={() => void run(async () => onChanged(await tasksApi.updateProject(project.key, { name: name.trim(), description: description.trim() || null })), 'Saved.')}
            >
              Save details
            </Button>
          </div>
        )}
      </section>

      <section className="panel space-y-3">
        <h3 className="t-h3">People</h3>
        <ul className="divide-y divide-[color:var(--color-border)]">
          {project.members.map((member) => (
            <li key={member.id} className="flex items-center gap-3 py-2">
              <span className="min-w-0 flex-1">
                <Person person={member} />
              </span>
              <Select
                className="!h-8 !min-h-0 !w-32 !py-0 text-xs"
                value={member.role}
                disabled={archived}
                aria-label={`Role of ${member.display_name}`}
                onChange={(e) => void run(async () => (await tasksApi.setMember(project.key, member.id, e.target.value as ProjectRole), await refresh()))}
              >
                <option>Manager</option>
                <option>Member</option>
                <option>Viewer</option>
              </Select>
              <Button size="sm" variant="ghost" aria-label={`Remove ${member.display_name}`} disabled={archived} onClick={() => void run(async () => (await tasksApi.removeMember(project.key, member.id), await refresh()))}>
                <X className="h-4 w-4" />
              </Button>
            </li>
          ))}
        </ul>
        {!archived && (
          <div className="grid gap-2 sm:grid-cols-[1fr_9rem_auto]">
            <PersonSelect people={candidates} value={newMember} onChange={setNewMember} emptyLabel="Add a person…" />
            <Select value={newRole} onChange={(e) => setNewRole(e.target.value as ProjectRole)} aria-label="Role">
              <option>Manager</option>
              <option>Member</option>
              <option>Viewer</option>
            </Select>
            <Button
              variant="secondary"
              disabled={!newMember}
              onClick={() =>
                void run(async () => {
                  await tasksApi.setMember(project.key, newMember!, newRole)
                  setNewMember(null)
                  await refresh()
                })
              }
            >
              <UserPlus className="h-4 w-4" /> Add
            </Button>
          </div>
        )}
        <p className="text-xs text-[color:var(--color-text-muted)]">
          Managers change how the project is run. Members create and work on tasks. Viewers only look and, in a company project, comment. Admins are managers of every project.
          {people.length === 0 ? '' : ''}
        </p>
      </section>

      <section className="panel space-y-3">
        <h3 className="t-h3">Statuses</h3>
        <p className="text-xs text-[color:var(--color-text-muted)]">The steps a task goes through. Each is a column on the board. The kind says what it means: to do, in progress, in review or done.</p>
        <ul className="space-y-2">
          {project.statuses.map((status, index) => (
            <li key={status.id} className="grid grid-cols-[1fr_auto] items-center gap-2 sm:grid-cols-[1fr_9rem_5rem_auto]">
              <Input
                defaultValue={status.name}
                key={`${status.id}-${status.name}`}
                maxLength={40}
                disabled={archived}
                aria-label="Status name"
                onBlur={(e) => e.target.value.trim() && e.target.value.trim() !== status.name && void run(async () => (await tasksApi.updateStatus(project.key, status.id, { name: e.target.value.trim() }), await refresh()))}
              />
              <Select
                className="hidden sm:block"
                value={status.category}
                disabled={archived}
                aria-label={`Kind of ${status.name}`}
                onChange={(e) => void run(async () => (await tasksApi.updateStatus(project.key, status.id, { category: e.target.value as StatusCategory }), await refresh()))}
              >
                {CATEGORIES.map((c) => (
                  <option key={c} value={c}>
                    {CATEGORY_LABEL[c]}
                  </option>
                ))}
              </Select>
              <Input
                className="hidden sm:block"
                type="number"
                min={0}
                max={500}
                defaultValue={status.wip_limit ?? ''}
                key={`${status.id}-${status.wip_limit}`}
                placeholder="Limit"
                title="Most tasks at a time (blank for no limit)"
                aria-label={`Task limit of ${status.name}`}
                disabled={archived}
                onBlur={(e) => {
                  const next = e.target.value.trim() ? Number(e.target.value) : null
                  if (next !== status.wip_limit) void run(async () => (await tasksApi.updateStatus(project.key, status.id, { wip_limit: next }), await refresh()))
                }}
              />
              <span className="flex">
                <Button
                  size="sm"
                  variant="ghost"
                  aria-label={`Move ${status.name} left`}
                  disabled={archived || index === 0}
                  onClick={() => {
                    const ids = project.statuses.map((s) => s.id)
                    ;[ids[index - 1], ids[index]] = [ids[index], ids[index - 1]]
                    void run(async () => (await tasksApi.reorderStatuses(project.key, ids), await refresh()))
                  }}
                >
                  <ArrowUp className="h-4 w-4" />
                </Button>
                <Button
                  size="sm"
                  variant="ghost"
                  aria-label={`Move ${status.name} right`}
                  disabled={archived || index === project.statuses.length - 1}
                  onClick={() => {
                    const ids = project.statuses.map((s) => s.id)
                    ;[ids[index + 1], ids[index]] = [ids[index], ids[index + 1]]
                    void run(async () => (await tasksApi.reorderStatuses(project.key, ids), await refresh()))
                  }}
                >
                  <ArrowDown className="h-4 w-4" />
                </Button>
                <Button
                  size="sm"
                  variant="ghost"
                  aria-label={`Delete ${status.name}`}
                  disabled={archived}
                  onClick={() => {
                    setMoveTo('')
                    setRemoving(status)
                  }}
                >
                  <Trash2 className="h-4 w-4" />
                </Button>
              </span>
            </li>
          ))}
        </ul>
        {!archived && (
          <form
            className="grid gap-2 sm:grid-cols-[1fr_9rem_auto]"
            onSubmit={(event) => {
              event.preventDefault()
              if (!newStatus.trim()) return
              void run(async () => {
                await tasksApi.addStatus(project.key, newStatus.trim(), newCategory)
                setNewStatus('')
                await refresh()
              })
            }}
          >
            <Input value={newStatus} maxLength={40} onChange={(e) => setNewStatus(e.target.value)} placeholder="New status, e.g. Waiting for client" aria-label="New status" />
            <Select value={newCategory} onChange={(e) => setNewCategory(e.target.value as StatusCategory)} aria-label="Kind of the new status">
              {CATEGORIES.map((c) => (
                <option key={c} value={c}>
                  {CATEGORY_LABEL[c]}
                </option>
              ))}
            </Select>
            <Button type="submit" variant="secondary" disabled={!newStatus.trim()}>
              <Plus className="h-4 w-4" /> Add
            </Button>
          </form>
        )}
      </section>

      <section className="panel space-y-3">
        <h3 className="t-h3">{archived ? 'Archived' : 'Archive'}</h3>
        <p className="text-sm text-[color:var(--color-text-muted)]">{archived ? 'This project is read-only. Nothing in it can be changed until it is brought back.' : 'An archived project is hidden from the lists and becomes read-only. Nothing is deleted, and you can bring it back.'}</p>
        <Button
          variant={archived ? 'secondary' : 'danger'}
          onClick={() => {
            if (archived || window.confirm(`Archive ${project.name}? Its tasks become read-only.`)) void run(async () => onChanged(await tasksApi.archiveProject(project.key, !archived)), archived ? 'The project is active again.' : 'The project is archived.')
          }}
        >
          {archived ? <ArchiveRestore className="h-4 w-4" /> : <Archive className="h-4 w-4" />} {archived ? 'Bring it back' : 'Archive project'}
        </Button>
      </section>

      <Modal
        open={Boolean(removing)}
        onClose={() => setRemoving(null)}
        title={`Delete the status ${removing?.name ?? ''}`}
        footer={
          <>
            <Button variant="secondary" onClick={() => setRemoving(null)}>
              Cancel
            </Button>
            <Button
              variant="danger"
              disabled={Boolean(removing?.tasks) && !moveTo}
              onClick={async () => {
                if (!removing) return
                const ok = await run(async () => (await tasksApi.deleteStatus(project.key, removing.id, moveTo ? Number(moveTo) : undefined), await refresh()))
                if (ok) setRemoving(null)
              }}
            >
              Delete
            </Button>
          </>
        }
      >
        {removing && removing.tasks > 0 ? (
          <Field label={`${removing.tasks} task${removing.tasks === 1 ? ' is' : 's are'} in this status. Move them to`} required>
            <Select value={moveTo} onChange={(e) => setMoveTo(e.target.value)} aria-label="Move the tasks to">
              <option value="">Choose a status</option>
              {project.statuses
                .filter((s) => s.id !== removing.id && (s.category === 'done') === (removing.category === 'done'))
                .map((s) => (
                  <option key={s.id} value={s.id}>
                    {s.name}
                  </option>
                ))}
            </Select>
          </Field>
        ) : (
          <p className="text-sm text-[color:var(--color-text-muted)]">No task is in this status. It will be removed from the board.</p>
        )}
      </Modal>
    </div>
  )
}
