import { useState } from 'react'
import { api } from '../../api/client'
import type { DashboardFilters, FilterChip, RecordPage } from '../../types'
import { Drawer } from '../ui/Drawer'
import { RecordTable } from './RecordTable'
import { count } from './format'

/**
 * The rows behind a figure. Opened from a chart's "Records" button or the Explore menu, it reads the same
 * warehouse rows the chart summed, with the same filters, so a total on the page can be checked line by line.
 */
export function RecordsDrawer({
  dataset,
  label,
  filters,
  chips,
  onClose,
}: {
  dataset: string | null
  label?: string
  filters: DashboardFilters
  chips: FilterChip[]
  onClose: () => void
}) {
  const [data, setData] = useState<RecordPage | null>(null)
  const filterKey = JSON.stringify(filters)

  return (
    <Drawer
      open={dataset !== null}
      onClose={onClose}
      title={data?.label ?? label ?? 'Records'}
      subtitle={data ? `${count(data.total)} ${data.total === 1 ? 'record' : 'records'}` : 'Loading the records…'}
    >
      {dataset && (
        <div className="space-y-3">
          <p className="text-xs text-[color:var(--color-text-muted)]">
            {chips.length || filters.from || filters.to ? (
              <>
                Filtered by{' '}
                {[...chips.map((c) => `${c.label}: ${c.display}`), ...(filters.from || filters.to ? [`Period ${filters.from ?? '…'} to ${filters.to ?? '…'}`] : [])].join(' · ')}.
              </>
            ) : (
              'Every record, no filters applied.'
            )}
            {data && !data.period_applies && ' This set shows today’s position, so the period does not narrow it.'}
          </p>
          <RecordTable
            load={(query) => api.dashboardRecords(dataset, filters, query)}
            resetKey={`${dataset}|${filterKey}`}
            fileName={dataset}
            onData={setData}
          />
        </div>
      )}
    </Drawer>
  )
}
