import type { TaskPersonRow } from '../../types'
import { SearchSelect } from '../ui/SearchSelect'

/** Choosing one person (or nobody) from a list, with a search box. The value is the person's id as text, empty for nobody. */
export function PersonSelect({
  people,
  value,
  onChange,
  emptyLabel = 'Unassigned',
  disabled = false,
}: {
  people: TaskPersonRow[]
  value: number | null
  onChange: (id: number | null) => void
  emptyLabel?: string
  disabled?: boolean
}) {
  return (
    <SearchSelect
      value={value === null ? '' : String(value)}
      options={people.map((person) => ({ id: String(person.id), label: person.display_name }))}
      onChange={(next) => onChange(next ? Number(next) : null)}
      placeholder={emptyLabel}
      emptyLabel={emptyLabel}
      disabled={disabled}
    />
  )
}
