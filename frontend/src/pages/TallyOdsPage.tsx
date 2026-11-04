import { useEffect, useState } from 'react'
import { Navigate, useSearchParams } from 'react-router-dom'
import { BookOpen, RefreshCw } from 'lucide-react'
import { api } from '../api/client'
import { useAuth } from '../context/AuthContext'
import { useDataRefresh } from '../context/DataRefreshContext'
import { PreviewRecords } from '../components/PreviewRecords'
import { Alert } from '../components/ui/Alert'
import { WorkbenchPlace, WorkbenchPanel, WorkbenchShell, WorkbenchStage } from '../components/data/WorkbenchChrome'
import { WorkbenchCatalog } from '../components/data/WorkbenchCatalog'

type TallyStatus = {
  running?: boolean
  warning?: string | null
}
type TallyTable = { name: string; kind: 'master' | 'transaction'; rows: number }

function formatCount(value: number) {
  return value.toLocaleString()
}

/** Browse the Tally working copy. Loading it from Tally Prime is done from the ETL page, where every run is recorded. */
export function TallyOdsPage() {
  const { user, loading } = useAuth()
  const { generation } = useDataRefresh()
  const [searchParams] = useSearchParams()
  const canBrowse = Boolean(user?.can_tally)
  const [tables, setTables] = useState<TallyTable[]>([])
  const [status, setStatus] = useState<TallyStatus>({})
  const [selected, setSelected] = useState('')

  const reloadTables = () =>
    Promise.all([api.tallyTables(), api.tallyStatus().catch((): TallyStatus => ({ running: false }))]).then(
      ([tableResult, tallyStatus]) => {
        setTables(tableResult.tables)
        setStatus(tallyStatus)
        setSelected((current) =>
          current && tableResult.tables.some((table) => table.name === current)
            ? current
            : tableResult.tables[0]?.name ?? '',
        )
      },
    )

  useEffect(() => {
    if (!canBrowse) return
    void reloadTables()
  }, [user, generation, canBrowse])

  if (loading) return null
  if (!canBrowse) return <Navigate to="/data" replace />
  // Older links opened the load workspace here. It moved to the ETL page.
  if (searchParams.get('workspace') === 'refresh') return <Navigate to="/etl?pipeline=tally_ods" replace />

  const selectedTable = tables.find((table) => table.name === selected)
  const masters = tables.filter((table) => table.kind === 'master')
  const transactions = tables.filter((table) => table.kind === 'transaction')

  return (
    <WorkbenchShell>
      <WorkbenchPlace
        tone="violet"
        backTo="/data/tally"
        backLabel="Tally Prime"
        here="Browse Tally ODS"
        item={selectedTable?.name}
      />

      {status.warning ? (
        <div className="px-4 pt-3">
          <Alert variant="info">{status.warning}</Alert>
        </div>
      ) : null}

      <WorkbenchStage
        catalog={
          <WorkbenchCatalog
            tone="violet"
            groups={[
              {
                label: 'Masters',
                icon: <BookOpen className="h-3.5 w-3.5" />,
                items: masters.map((table) => ({ id: table.name, label: table.name, meta: formatCount(table.rows) })),
              },
              {
                label: 'Transactions',
                icon: <RefreshCw className="h-3.5 w-3.5" />,
                items: transactions.map((table) => ({ id: table.name, label: table.name, meta: formatCount(table.rows) })),
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
                  title="Current records"
                  reloadToken={generation}
                  emptyMessage="No Tally ODS records yet. Run the Tally working copy pipeline from the ETL page."
                  load={(limit, query) => api.tallyPreview(selected, limit, query)}
                  download={(limit, query) => api.downloadTallyExport(selected, limit, query)}
                  values={(column, query, contains) => api.tallyValues(selected, column, query, contains)}
                />
              )}
            </div>
          </WorkbenchPanel>
        }
      />
    </WorkbenchShell>
  )
}
