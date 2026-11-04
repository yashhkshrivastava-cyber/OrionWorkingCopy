import { useMemo, useState } from 'react'
import { Users } from 'lucide-react'
import { api } from '../../api/client'
import { Button } from '../ui/Button'
import { Modal } from '../ui/Modal'
import { MultiSelect } from '../ui/MultiSelect'
import { GroupAvatar } from './GroupAvatar'
import type { ChatPeer, ChatThread } from '../../types'

export const MAX_GROUP = 50
export const MAX_TITLE = 60

/** How a person is named in the picker: the name, and the user name so two people with the same name can be told apart. */
export const personLabel = (person: ChatPeer) => `${person.display_name} (@${person.username})`

/**
 * Making a group: a name and the people. Whoever makes it runs it. Everybody in a group sees all of its messages, earlier ones
 * included, and the dialog says so before anyone is added.
 */
export function NewGroupDialog({ open, people, onClose, onCreated }: { open: boolean; people: ChatPeer[]; onClose: () => void; onCreated: (chat: ChatThread) => void }) {
  const [title, setTitle] = useState('')
  const [chosen, setChosen] = useState<string[]>([])
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const byLabel = useMemo(() => new Map(people.map((p) => [personLabel(p), p])), [people])
  const ready = title.trim().length > 0 && chosen.length > 0

  const close = () => {
    if (busy) return
    setTitle('')
    setChosen([])
    setError('')
    onClose()
  }

  const create = async () => {
    if (!ready || busy) return
    setBusy(true)
    setError('')
    try {
      const made = await api.createGroup(
        title.trim(),
        chosen.map((label) => byLabel.get(label)?.id).filter((id): id is number => id !== undefined),
      )
      setTitle('')
      setChosen([])
      onCreated(made)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not make the group.')
    } finally {
      setBusy(false)
    }
  }

  return (
    <Modal
      open={open}
      onClose={close}
      title="New group"
      footer={
        <>
          <Button variant="secondary" onClick={close} disabled={busy}>
            Cancel
          </Button>
          <Button onClick={() => void create()} loading={busy} disabled={!ready}>
            Create group
          </Button>
        </>
      }
    >
      <form
        className="space-y-5 px-5 py-4"
        onSubmit={(event) => {
          event.preventDefault()
          void create()
        }}
      >
        <div className="flex items-center gap-4">
          {title.trim() ? <GroupAvatar title={title} size="xl" /> : (
            <span className="inline-flex h-14 w-14 shrink-0 items-center justify-center rounded-full bg-muted text-[color:var(--color-text-faint)]" aria-hidden="true">
              <Users className="h-6 w-6" />
            </span>
          )}
          <label className="block min-w-0 flex-1">
            <span className="eyebrow mb-1 block">Group name</span>
            <input
              autoFocus
              value={title}
              onChange={(event) => setTitle(event.target.value)}
              maxLength={MAX_TITLE}
              placeholder="Site leads, Billing team…"
              className="w-full rounded-xl border border-[color:var(--color-border)] bg-[color:var(--color-bg)] px-3.5 py-2.5 text-sm outline-none focus:border-accent"
            />
          </label>
        </div>
        <div>
          <span className="eyebrow mb-1 block">People</span>
          <MultiSelect
            label="People in the group"
            values={chosen}
            onChange={setChosen}
            options={people.map(personLabel)}
            noun={['person', 'people']}
            placeholder="Choose who is in the group"
            searchPlaceholder="Search people"
            max={MAX_GROUP - 1}
          />
        </div>
        <p className="rounded-xl bg-muted px-3.5 py-2.5 text-xs leading-relaxed text-[color:var(--color-text-muted)]">
          You will run the group. Everyone in it can read all of its messages, including ones sent before they joined, and can leave at any time. You can add or remove people later.
        </p>
        {error && (
          <p role="alert" className="text-sm text-negative">
            {error}
          </p>
        )}
      </form>
    </Modal>
  )
}
