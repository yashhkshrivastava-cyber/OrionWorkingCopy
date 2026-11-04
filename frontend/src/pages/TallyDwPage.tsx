import { useEffect, useState } from 'react'
import { Navigate, useSearchParams } from 'react-router-dom'
import { Layers, RefreshCw } from 'lucide-react'
import { api } from '../api/client'
import { useAuth } from '../context/AuthContext'
import { useDataRefresh } from '../context/DataRefreshContext'
import { PreviewRecords } from '../components/PreviewRecords'
import { WorkbenchPlace, WorkbenchPanel, WorkbenchShell, WorkbenchStage } from '../components/data/WorkbenchChrome'
import { WorkbenchCatalog } from '../components/data/WorkbenchCatalog'

type DwTable = { name: string; kind: 'dimension' | 'fact'; rows: number; current: number }

function formatCount(value: number) {
  return value.toLocaleString()
}

/** Browse the Tally warehouse. Loading it is done from the ETL page, where every run is recorded. */
export function TallyDwPage() {
  const { user, loading } = useAuth()
  const { generation } = useDataRefresh()
  const [searchParams] = useSearchParams()
  const canBrowse = Boolean(user?.can_tally_dw)
  const [tables, setTables] = useState<DwTable[]>([])
  const [selected, setSelected] = useState('')

  const reloadTables = () =>
    api.tallyDwTables().then((r) => {
      setTables(r.tables)
      setSelected((current) =>
        current && r.tables.some((table) => table.name === current) ? current : r.tables[0]?.name ?? '',
      )
    })

  useEffect(() => {
    if (!canBrowse) return
    void reloadTables()
  }, [user, generation, canBrowse])

  if (loading) return null
  if (!canBrowse) return <Navigate to="/data/tally" replace />
  // Older links opened the load workspace here. It moved to the ETL page.
  if (searchParams.get('workspace') === 'refresh') return <Navigate to="/etl?pipeline=tally_dw" replace />

  const selectedTable = tables.find((table) => table.name === selected)
  const dims = tables.filter((table) => table.kind === 'dimension')
  const facts = tables.filter((table) => table.kind === 'fact')

  return (
    <WorkbenchShell>
      <WorkbenchPlace
        tone="violet"
        backTo="/data/tally"
        backLabel="Tally Prime"
        here="Browse Tally warehouse"
        item={selectedTable?.name}
      />

      <WorkbenchStage
        catalog={
          <WorkbenchCatalog
            tone="violet"
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
                  emptyMessage="No current Tally warehouse records yet. Run the Tally warehouse pipeline from the ETL page."
                  load={(limit, query) => api.tallyDwPreview(selected, limit, query)}
                  download={(limit, query) => api.downloadTallyDwExport(selected, limit, query)}
                  values={(column, query, contains) => api.tallyDwValues(selected, column, query, contains)}
                />
              )}
            </div>
          </WorkbenchPanel>
        }
      />
    </WorkbenchShell>
  )
}
