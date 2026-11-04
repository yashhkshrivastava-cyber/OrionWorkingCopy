import { createContext, useContext, useEffect, useMemo, useState, type ReactNode } from 'react'
import { useLocation } from 'react-router-dom'

/** A destination in the navigation rail. Each remembers the last address opened inside it. */
export type NavArea =
  | 'dashboard.orion'
  | 'dashboard.tally'
  | 'data.orion'
  | 'data.tally'
  | 'utility'
  | 'letterhead'
  | 'pdf'
  | 'documents'
  | 'bank'
  | 'tenders.gem'
  | 'tenders.mp'
  | 'attendance'
  | 'etl'
  | 'sql'
  | 'admin'
  | 'messages'
  | 'tasks'

const DEFAULTS: Record<NavArea, string> = {
  'dashboard.orion': '/dashboard/orion',
  'dashboard.tally': '/dashboard/tally',
  'data.orion': '/data/orion',
  'data.tally': '/data/tally',
  utility: '/utility/billing',
  letterhead: '/letterhead/letters',
  pdf: '/pdf-tools',
  documents: '/documents',
  bank: '/bank',
  'tenders.gem': '/tenders/gem',
  'tenders.mp': '/tenders/mp',
  attendance: '/attendance',
  etl: '/etl',
  sql: '/sql',
  admin: '/admin',
  messages: '/messages',
  tasks: '/tasks/mine',
}

/** The area an address belongs to, or null for pages outside the rail's areas. */
export function areaOf(pathname: string): NavArea | null {
  if (pathname.startsWith('/dashboard/tally')) return 'dashboard.tally'
  if (pathname.startsWith('/dashboard/orion')) return 'dashboard.orion'
  if (pathname.startsWith('/data/tally')) return 'data.tally'
  if (/^\/data\/(orion|operational|warehouse|clients|cases|employees)/.test(pathname)) return 'data.orion'
  if (pathname.startsWith('/utility')) return 'utility'
  if (pathname.startsWith('/letterhead')) return 'letterhead'
  if (pathname.startsWith('/pdf-tools')) return 'pdf'
  if (pathname.startsWith('/documents')) return 'documents'
  if (pathname.startsWith('/bank')) return 'bank'
  if (pathname.startsWith('/tenders/mp')) return 'tenders.mp'
  if (pathname.startsWith('/tenders')) return 'tenders.gem'
  if (pathname.startsWith('/attendance')) return 'attendance'
  if (pathname.startsWith('/etl')) return 'etl'
  if (pathname.startsWith('/sql')) return 'sql'
  if (pathname.startsWith('/admin')) return 'admin'
  if (pathname.startsWith('/messages')) return 'messages'
  if (pathname.startsWith('/tasks')) return 'tasks'
  return null
}

const TabMemoryContext = createContext<Record<NavArea, string>>(DEFAULTS)

export function TabMemoryProvider({ children }: { children: ReactNode }) {
  const location = useLocation()
  const [last, setLast] = useState(DEFAULTS)

  useEffect(() => {
    const area = areaOf(location.pathname)
    if (!area) return
    const href = `${location.pathname}${location.search}`
    setLast((current) => (current[area] === href ? current : { ...current, [area]: href }))
  }, [location.pathname, location.search])

  const value = useMemo(() => last, [last])
  return <TabMemoryContext.Provider value={value}>{children}</TabMemoryContext.Provider>
}

/** Where each area was last left, so the rail returns you to it. */
export function useTabMemory() {
  return useContext(TabMemoryContext)
}
