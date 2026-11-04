import { useEffect, useState } from 'react'
import { tasksApi } from '../api/client'
import type { TaskPersonRow } from '../types'

const cache = new Map<string, { at: number; people: TaskPersonRow[] }>()
const FRESH_MS = 60_000

/** The people a task can be given to (everyone who can sign in; in a private project, only its members). Kept for a minute so opening several tasks asks once. */
export function useTaskPeople(project?: string | null): TaskPersonRow[] {
  const key = project ?? ''
  const [people, setPeople] = useState<TaskPersonRow[]>(() => cache.get(key)?.people ?? [])

  useEffect(() => {
    const hit = cache.get(key)
    if (hit && Date.now() - hit.at < FRESH_MS) {
      setPeople(hit.people)
      return
    }
    let cancelled = false
    tasksApi
      .people(project ?? undefined)
      .then((found) => {
        cache.set(key, { at: Date.now(), people: found.people })
        if (!cancelled) setPeople(found.people)
      })
      .catch(() => {
        // The pickers stay empty; the person can still save without choosing anyone.
      })
    return () => {
      cancelled = true
    }
  }, [key, project])

  return people
}
