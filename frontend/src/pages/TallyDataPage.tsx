import { useEffect } from 'react'
import { Link, Navigate, useNavigate, useSearchParams } from 'react-router-dom'
import { ArrowRight, BookOpen, ChevronLeft, Eye, Layers, RefreshCw } from 'lucide-react'
import { useAuth } from '../context/AuthContext'
import { IntentCard } from '../components/data/IntentCard'

export function TallyDataPage() {
  const { user } = useAuth()
  const navigate = useNavigate()
  const [searchParams] = useSearchParams()
  const canTallyOds = Boolean(user?.can_tally || user?.can_tally_write)
  const canTallyDw = Boolean(user?.can_tally_dw || user?.can_tally_dw_write)
  const canEtl = Boolean(user?.can_etl)
  const canTally = canTallyOds || canTallyDw
  const canOrion = Boolean(user?.can_ods || user?.can_ods_write || user?.can_dw || user?.can_dw_write)

  // Older links opened the load workspaces from here. They moved to the ETL page.
  useEffect(() => {
    if (searchParams.get('workspace') !== 'refresh') return
    navigate('/etl?pipeline=tally_ods', { replace: true })
  }, [searchParams, navigate])

  if (!canTally) return <Navigate to="/data" replace />

  return (
    <div className="mx-auto max-w-6xl pb-4">
      <nav className="mb-4 flex flex-wrap items-center gap-1.5 text-sm" aria-label="Location">
        {canOrion ? (
          <Link
            to="/data"
            className="interactive inline-flex items-center gap-1 font-medium text-violet hover:underline"
          >
            <ChevronLeft className="h-4 w-4" />
            Data
          </Link>
        ) : (
          <h1 className="text-sm font-semibold tracking-tight text-violet">Data management</h1>
        )}
        {canOrion ? (
          <>
            <span className="text-[color:var(--color-text-faint)]">/</span>
            <h1 className="text-sm font-semibold tracking-tight text-violet">Tally Prime</h1>
          </>
        ) : null}
      </nav>

      <div className="space-y-8">
        {canTallyOds ? (
          <section>
            <h2 className="mb-3 text-xs font-semibold uppercase tracking-[0.16em] text-[color:var(--color-text-faint)]">
              Working copy
            </h2>
            <div
              className={`stagger-in grid gap-5 overflow-visible py-2 ${canEtl ? 'lg:grid-cols-2' : 'max-w-3xl'}`}
            >
              <IntentCard
                tone="violet"
                icon={Eye}
                badge="Read Tally ODS"
                title="Browse Tally working copy"
                body="Inspect the latest Tally Prime masters and vouchers after they have been loaded. Nothing is pulled from Tally in this view."
                chips={['Masters', 'Vouchers', 'Preview']}
                cta="Browse tables"
                onClick={() => navigate('/data/tally/working')}
              />
              {canEtl && (
                <IntentCard
                  tone="violet"
                  icon={BookOpen}
                  badge="Writes Tally ODS"
                  title="Run the Tally ODS load"
                  body="Pull the open company from Tally Prime. The company must be open (F1). Runs are started and recorded on the ETL page."
                  chips={['Full load', 'SCD Type 1']}
                  cta="Open ETL"
                  onClick={() => navigate('/etl?pipeline=tally_ods')}
                />
              )}
            </div>
          </section>
        ) : null}

        {canTallyDw ? (
          <section>
            <h2 className="mb-3 text-xs font-semibold uppercase tracking-[0.16em] text-[color:var(--color-text-faint)]">
              Tally warehouse
            </h2>
            <div
              className={`stagger-in grid gap-5 overflow-visible py-2 ${canEtl ? 'lg:grid-cols-2' : 'max-w-3xl'}`}
            >
              <IntentCard
                tone="violet"
                icon={Layers}
                badge="Read Tally DW"
                title="Browse Tally warehouse"
                body="Inspect billed dimensions and facts versioned from the Tally working copy. History stays in place. Nothing loads from this view."
                chips={['Dimensions', 'Facts', 'Client month']}
                cta="Browse tables"
                onClick={() => navigate('/data/tally/warehouse')}
              />
              {canEtl && (
                <IntentCard
                  tone="violet"
                  icon={RefreshCw}
                  badge="Writes Tally DW"
                  title="Run the Tally warehouse load"
                  body="Load Tally dimensions first, then facts with point-in-time keys as of voucher date. Runs are started and recorded on the ETL page."
                  chips={['Full refresh', 'SCD Type 2']}
                  cta="Open ETL"
                  onClick={() => navigate('/etl?pipeline=tally_dw')}
                />
              )}
            </div>
          </section>
        ) : null}

        <div className="overflow-hidden rounded-2xl border border-[color:var(--color-border)] bg-surface/80 px-5 py-4 sm:px-6">
          <p className="mb-3 text-xs font-semibold uppercase tracking-[0.16em] text-[color:var(--color-text-faint)]">
            How they connect
          </p>
          <div className="flex flex-col items-stretch gap-3 overflow-visible sm:flex-row sm:items-center sm:gap-4">
            <div className="data-hot flex-1 rounded-xl bg-violet-dim/70 px-4 py-3">
              <p className="text-sm font-semibold text-[color:var(--color-text)]">Tally Prime</p>
              <p className="text-xs text-[color:var(--color-text-muted)]">Live books on port 9000</p>
            </div>
            <ArrowRight className="mx-auto hidden h-4 w-4 shrink-0 text-[color:var(--color-text-faint)] sm:block" />
            <div className="data-hot flex-1 rounded-xl bg-violet-dim/60 px-4 py-3">
              <p className="text-sm font-semibold text-[color:var(--color-text)]">Tally ODS</p>
              <p className="text-xs text-[color:var(--color-text-muted)]">SCD Type 1 working copy</p>
            </div>
            <ArrowRight className="mx-auto hidden h-4 w-4 shrink-0 text-[color:var(--color-text-faint)] sm:block" />
            <div className="data-hot flex-1 rounded-xl bg-violet-dim/70 px-4 py-3">
              <p className="text-sm font-semibold text-[color:var(--color-text)]">Tally warehouse</p>
              <p className="text-xs text-[color:var(--color-text-muted)]">SCD Type 2, billed grain</p>
            </div>
          </div>
        </div>
      </div>
    </div>
  )
}
