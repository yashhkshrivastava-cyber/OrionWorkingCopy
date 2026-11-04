import { useCallback } from 'react'
import { useLocation, useNavigate } from 'react-router-dom'

/** Opens a task on top of whatever task page is open (or on My work from anywhere else). The task is the `task` part of the address, so it can be shared. */
export function useOpenTask() {
  const navigate = useNavigate()
  const location = useLocation()
  return useCallback(
    (key: string) => {
      const inTasks = location.pathname.startsWith('/tasks')
      const search = new URLSearchParams(inTasks ? location.search : '')
      search.set('task', key)
      navigate({ pathname: inTasks ? location.pathname : '/tasks/mine', search: `?${search.toString()}` })
    },
    [navigate, location.pathname, location.search],
  )
}
