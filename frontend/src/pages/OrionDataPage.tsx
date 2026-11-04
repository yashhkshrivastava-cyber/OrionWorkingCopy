import { useState } from 'react'
import { Link, Navigate, useNavigate } from 'react-router-dom'
import { ArrowRight, ChevronLeft, Eye, Layers, Pencil, RefreshCw } from 'lucide-react'
import { useAuth } from '../context/AuthContext'
import { WriteGate } from '../components/data/WriteGate'
import { DataDesk } from '../components/data/DataDesk'
import { IntentCard } from '../components/data/IntentCard'
import { useLumen } from '../lumen/useLumen'
import { Alert } from '../components/ui/Alert'

export function OrionDataPage() {
  const { user } = useAuth()
  const navigate = useNavigate()
  const lumen = useLumen()
  const [gate, setGate] = useState<'ods' | null>(null)
  const canOds = Boolean(user?.can_ods)
  const canOdsWrite = Boolean(user?.can_ods_write)
  const canDw = Boolean(user?.can_dw)
  const canEtl = Boolean(user?.can_etl)
  const canOrion = canOds || canOdsWrite || canDw
  const canTally = Boolean(
    user?.can_tally || user?.can_tally_write || user?.can_tally_dw || user?.can_tally_dw_write,
  )

  if (!canOrion) return <Navigate to="/data" replace />
  if (lumen) return <DataDesk canOds={canOds} canOdsWrite={canOdsWrite} canDw={canDw} canEtl={canEtl} backToData={canTally} />

  return (
    <div className="mx-auto max-w-6xl pb-4">
      <nav className="mb-4 flex flex-wrap items-center gap-1.5 text-sm" aria-label="Location">
        {canTally ? (
          <Link
            to="/data"
            className="interactive inline-flex items-center gap-1 font-medium text-accent hover:underline"
          >
            <ChevronLeft className="h-4 w-4" />
            Data
          </Link>
        ) : (
          <h1 className="text-sm font-semibold tracking-tight text-accent">Data management</h1>
        )}
        {canTally ? (
          <>
            <span className="text-[color:var(--color-text-faint)]">/</span>
            <h1 className="text-sm font-semibold tracking-tight text-accent">Orion</h1>
          </>
        ) : null}
      </nav>

      <div className="space-y-8">
        {(canOds || canOdsWrite) && (
          <section>
            <h2 className="mb-3 text-xs font-semibold uppercase tracking-[0.16em] text-[color:var(--color-text-faint)]">
              Operational data
            </h2>
            <div
              className={`stagger-in grid gap-5 overflow-visible py-2 ${canOds && canOdsWrite ? 'lg:grid-cols-2' : 'max-w-3xl'}`}
            >
              {canOds && (
                <IntentCard
                  tone="teal"
                  icon={Eye}
                  badge="No writes"
                  title="Review operational data"
                  body="Browse clients, cases, people, and the rest. The latest records stay on the page. Forms stay closed."
                  chips={['Preview', 'Download']}
                  cta="Open as review"
                  onClick={() => navigate('/data/operational')}
                />
              )}
              {canOdsWrite && (
                <IntentCard
                  tone="teal"
                  icon={Pencil}
                  badge="Writes ODS"
                  title="Change operational data"
                  body="Add, edit, or upload live operational records. You will confirm before this workspace opens."
                  chips={['Create', 'Update', 'Upload']}
                  cta="Open to change records"
                  onClick={() => setGate('ods')}
                />
              )}
            </div>
          </section>
        )}

        {canDw && (
          <section>
            <h2 className="mb-3 text-xs font-semibold uppercase tracking-[0.16em] text-[color:var(--color-text-faint)]">
              Warehouse
            </h2>
            <div
              className={`stagger-in grid gap-5 overflow-visible py-2 ${canDw && canEtl ? 'lg:grid-cols-2' : 'max-w-3xl'}`}
            >
              {canDw && (
                <IntentCard
                  tone="amber"
                  icon={Layers}
                  badge="Read warehouse"
                  title="Browse warehouse tables"
                  body="Inspect current dimensions and facts. History stays in place. Nothing loads from this view."
                  chips={['Dimensions', 'Facts', 'Preview']}
                  cta="Browse tables"
                  onClick={() => navigate('/data/warehouse')}
                />
              )}
              {canEtl && (
                <IntentCard
                  tone="amber"
                  icon={RefreshCw}
                  badge="Writes DW"
                  title="Run the warehouse load"
                  body="Load dimensions first, then facts with point-in-time keys. Runs are started and recorded on the ETL page."
                  chips={['Full refresh', 'SCD Type 2']}
                  cta="Open ETL"
                  onClick={() => navigate('/etl?pipeline=orion_dw')}
                />
              )}
            </div>
          </section>
        )}

        {canOds && canDw && (
          <div className="overflow-hidden rounded-2xl border border-[color:var(--color-border)] bg-surface/80 px-5 py-4 sm:px-6">
            <p className="mb-3 text-xs font-semibold uppercase tracking-[0.16em] text-[color:var(--color-text-faint)]">
              How they connect
            </p>
            <div className="flex flex-col items-stretch gap-3 overflow-visible sm:flex-row sm:items-center sm:gap-4">
              <div className="data-hot flex-1 rounded-xl bg-accent-dim/70 px-4 py-3">
                <p className="text-sm font-semibold text-[color:var(--color-text)]">Review or change ODS</p>
                <p className="text-xs text-[color:var(--color-text-muted)]">Working records stay here</p>
              </div>
              <ArrowRight className="mx-auto hidden h-4 w-4 shrink-0 text-[color:var(--color-text-faint)] sm:block" />
              <div className="data-hot flex-1 rounded-xl bg-violet-dim/70 px-4 py-3">
                <p className="text-sm font-semibold text-[color:var(--color-text)]">Confirm, then load</p>
                <p className="text-xs text-[color:var(--color-text-muted)]">Nothing writes by accident</p>
              </div>
              <ArrowRight className="mx-auto hidden h-4 w-4 shrink-0 text-[color:var(--color-text-faint)] sm:block" />
              <div className="data-hot flex-1 rounded-xl bg-warning-dim px-4 py-3">
                <p className="text-sm font-semibold text-[color:var(--color-text)]">Warehouse picture</p>
                <p className="text-xs text-[color:var(--color-text-muted)]">Versioned, point in time</p>
              </div>
            </div>
          </div>
        )}
      </div>

      {!canOds && !canOdsWrite && !canDw ? (
        <Alert variant="error">You do not have Orion data access.</Alert>
      ) : null}

      <WriteGate
        open={gate === 'ods'}
        title="Change operational data"
        body="You are opening a write workspace on live operational records. Anything you add, change, or delete is real working data. Dashboards and the warehouse stay as they are until someone loads them. Continue only if you intend to edit records."
        confirmLabel="I understand this is sensitive operational data"
        continueLabel="Continue to change records"
        onCancel={() => setGate(null)}
        onContinue={() => {
          setGate(null)
          navigate('/data/operational?intent=change', { state: { writeAck: true } })
        }}
      />
    </div>
  )
}
