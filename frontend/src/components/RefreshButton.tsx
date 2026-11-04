import { RefreshCw } from 'lucide-react'
import { Tooltip } from './ui/Tooltip'
import { useAuth } from '../context/AuthContext'
import { useDataRefresh } from '../context/DataRefreshContext'

export function RefreshButton({ className = '', compact = false }: { className?: string; compact?: boolean }) {
  const { refresh: refreshData, refreshing: dataRefreshing } = useDataRefresh()
  const { refresh: refreshAuth } = useAuth()
  const refreshing = dataRefreshing

  const handleRefresh = () => {
    refreshData()
    void refreshAuth()
  }

  const button = (
    <button
      type="button"
      onClick={handleRefresh}
      disabled={refreshing}
      aria-label="Refresh data"
      className={`interactive inline-flex items-center justify-center gap-2 rounded-lg text-sm font-medium text-[color:var(--color-text-muted)] hover:bg-muted hover:text-[color:var(--color-text)] disabled:opacity-70 ${
        compact ? 'h-9 w-9 p-0' : 'border border-[color:var(--color-border)] bg-surface px-3 py-1.5'
      } ${className}`}
    >
      <RefreshCw className={`h-4 w-4 ${refreshing ? 'animate-spin' : ''}`} />
      {!compact && <span>{refreshing ? 'Refreshing' : 'Refresh'}</span>}
    </button>
  )
  return compact ? <Tooltip label="Reload the latest data">{button}</Tooltip> : button
}
