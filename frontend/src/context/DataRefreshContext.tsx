import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from 'react'

type DataRefreshValue = {
  /** Bumps whenever the user asks for a fresh copy from the database. */
  generation: number
  refreshing: boolean
  refresh: () => void
}

const DataRefreshContext = createContext<DataRefreshValue | null>(null)

export function DataRefreshProvider({ children }: { children: ReactNode }) {
  const [generation, setGeneration] = useState(0)
  const [refreshing, setRefreshing] = useState(false)

  const refresh = useCallback(() => {
    if (refreshing) return
    setRefreshing(true)
    setGeneration((n) => n + 1)
  }, [refreshing])

  useEffect(() => {
    if (!refreshing) return
    const timer = window.setTimeout(() => setRefreshing(false), 900)
    return () => window.clearTimeout(timer)
  }, [refreshing, generation])

  const value = useMemo(
    () => ({ generation, refreshing, refresh }),
    [generation, refreshing, refresh],
  )

  return <DataRefreshContext.Provider value={value}>{children}</DataRefreshContext.Provider>
}

export function useDataRefresh() {
  const context = useContext(DataRefreshContext)
  if (!context) throw new Error('useDataRefresh must be used within DataRefreshProvider')
  return context
}
