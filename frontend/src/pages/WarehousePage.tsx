import { useEffect, useState } from 'react'
import { Navigate, useSearchParams } from 'react-router-dom'
import { Layers, RefreshCw } from 'lucide-react'
import { api } from '../api/client'
import { useAuth } from '../context/AuthContext'
import { useDataRefresh } from '../context/DataRefreshContext'
import { PreviewRecords } from '../components/PreviewRecords'
import { WorkbenchPlace, WorkbenchPanel, WorkbenchShell, WorkbenchStage } from '../components/data/WorkbenchChrome'
import { WorkbenchCatalog } from '../components/data/WorkbenchCatalog'
import { WarehouseFreshness } from '../components/dashboard/WarehouseFreshness'

type DwTable = { name: string; kind: 'dimension' | 'fact'; rows: number; current: number }

function formatCount(value: number) {
  return value.toLocaleString()
}

/** Browse the Orion warehouse. Loading it is done from the ETL page, where every run is recorded. */
export function WarehousePage() {
  const { user, loading } = useAuth()
  const { generation } = useDataRefresh()
  const [searchParams] = useSearchParams()
  const [tables, setTables] = useState<DwTable[]>([])
  const [selected, setSelected] = useState('')

  const reloadTables = () =>
    api.dwTables().then((r) => {
      setTables(r.tables)
      setSelected((current) =>
        current && r.tables.some((table) => table.name === current) ? current : r.tables[0]?.name ?? '',
      )
    })

  useEffect(() => {
    if (!user?.can_dw) return
    const load = () => {
      void reloadTables()
    }
    load()
    const onVisible = () => {
      if (document.visibilityState === 'visible') load()
    }
    document.addEventListener('visibilitychange', onVisible)
    window.addEventListener('focus', load)
    return () => {
      document.removeEventListener('visibilitychange', onVisible)
      window.removeEventListener('focus', load)
    }
  }, [user, generation])

  if (loading) return null
  if (!user?.can_dw) return <Navigate to="/data/orion" replace />
  // Older links opened the load workspace here. It moved to the ETL page.
  if (searchParams.get('workspace') === 'refresh') return <Navigate to="/etl?pipeline=orion_dw" replace />

  const selectedTable = tables.find((table) => table.name === selected)
  const dims = tables.filter((table) => table.kind === 'dimension')
  const facts = tables.filter((table) => table.kind === 'fact')

  return (
    <WorkbenchShell>
      <WorkbenchPlace
        tone="amber"
        backTo="/data/orion"
        backLabel="Orion"
        here="Browse warehouse"
        item={selectedTable?.name}
      />
      <WarehouseFreshness source="dw" reloadKey={generation} />

      <WorkbenchStage
        catalog={
          <WorkbenchCatalog
            tone="amber"
            groups={[
              {
                label: 'Dimensions',
                icon: <Layers className="h-3.5 w-3.5" />,
                items: dims.map((table) => ({ id: table.name, label: table.name, meta: formatCount(table.current) })),
              },
              {
                label: 'Facts',
                icon: <RefreshCw className="h-3.5 w-3.5" />,
                items: facts.map((table) => ({ id: table.name, label: table.name, meta: formatCount(table.current) })),
              },
            ]}
            selected={selected}
            onSelect={setSelected}
          />
        }
        main={
          <WorkbenchPanel fill className="gap-3 p-4">
            <div className="min-h-0 flex-1">
              {selected && (
                <PreviewRecords
                  fill
                  key={selected}
                  title="Records and their versions"
                  allColumns
                  reloadToken={generation}
                  emptyMessage="No current warehouse records yet. Run the Orion warehouse pipeline from the ETL page."
                  load={(limit, query) => api.dwPreview(selected, limit, query)}
                  download={(limit, query) => api.downloadDwExport(selected, limit, query)}
                  values={(column, query, contains) => api.dwValues(selected, column, query, contains)}
                />
              )}
            </div>
          </WorkbenchPanel>
        }
      />
    </WorkbenchShell>
  )
}
