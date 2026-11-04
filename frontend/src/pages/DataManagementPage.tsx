import { Navigate, useNavigate } from 'react-router-dom'
import { BookOpen, Layers } from 'lucide-react'
import { useAuth } from '../context/AuthContext'
import { Alert } from '../components/ui/Alert'
import { IntentCard } from '../components/data/IntentCard'

export function DataManagementPage() {
  const { user } = useAuth()
  const navigate = useNavigate()
  const canOrion = Boolean(user?.can_ods || user?.can_ods_write || user?.can_dw || user?.can_dw_write)
  const canTally = Boolean(
    user?.can_tally || user?.can_tally_write || user?.can_tally_dw || user?.can_tally_dw_write,
  )

  if (!canOrion && !canTally) {
    return (
      <div>
        <h1 className="mb-4 text-sm font-semibold text-accent">Data management</h1>
        <Alert variant="error">
          You do not have access to Orion or Tally Prime data. Contact an administrator.
        </Alert>
      </div>
    )
  }

  if (canOrion && !canTally) return <Navigate to="/data/orion" replace />
  if (canTally && !canOrion) return <Navigate to="/data/tally" replace />

  return (
    <div className="mx-auto max-w-4xl pb-4">
      <h1 className="mb-1 text-sm font-semibold text-accent">Data management</h1>
      <p className="mb-6 text-sm text-[color:var(--color-text-muted)]">
        Choose which store you want to work in.
      </p>
      <div className="stagger-in grid gap-5 overflow-visible py-2 lg:grid-cols-2">
        <IntentCard
          tone="teal"
          icon={Layers}
          badge="Orion"
          title="Orion"
          body="Operational records and the Orion warehouse: clients, cases, people, fleet, and versioned facts loaded from them."
          chips={['ODS', 'Warehouse']}
          cta="Open Orion"
          onClick={() => navigate('/data/orion')}
        />
        <IntentCard
          tone="violet"
          icon={BookOpen}
          badge="Tally Prime"
          title="Tally Prime"
          body="Tally working copy and billed warehouse: masters, vouchers, and client-month facts loaded from the books."
          chips={['Tally ODS', 'Tally warehouse']}
          cta="Open Tally"
          onClick={() => navigate('/data/tally')}
        />
      </div>
    </div>
  )
}
