import { useEffect, useState } from 'react'
import { api } from '../../api/client'
import { MultiSelect } from '../ui/MultiSelect'

let known: Promise<string[]> | null = null
/** The tags already used on documents (most used first), fetched once for the page: they are what the picker suggests. */
function knownTags(): Promise<string[]> {
  known ??= api
    .documentOverview()
    .then((overview) => overview.tags.map((item) => item.tag))
    .catch(() => {
      known = null
      return []
    })
  return known
}

/** A document's tags: pick from the ones already in use, or type a new one and press Enter (a comma starts the next). */
export function TagPicker({ values, onChange, max }: { values: string[]; onChange: (next: string[]) => void; max?: number }) {
  const [options, setOptions] = useState<string[]>([])
  useEffect(() => {
    let live = true
    knownTags().then((found) => live && setOptions(found))
    return () => {
      live = false
    }
  }, [])
  return (
    <MultiSelect
      label="Tags"
      values={values}
      onChange={onChange}
      options={options}
      noun={['tag', 'tags']}
      placeholder="Add tags"
      searchPlaceholder="Search the tags in use, or type a new one and press Enter"
      allowCustom
      separator={/,/}
      max={max}
    />
  )
}
