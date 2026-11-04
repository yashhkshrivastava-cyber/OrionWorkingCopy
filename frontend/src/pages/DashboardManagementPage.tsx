import { Navigate, useNavigate } from 'react-router-dom'
import { BookOpen, Layers } from 'lucide-react'
import { useAuth } from '../context/AuthContext'
import { Alert } from '../components/ui/Alert'
import { IntentCard } from '../components/data/IntentCard'

export function DashboardManagementPage() {
  const { user } = useAuth()
  const navigate = useNavigate()
  const canOrion = user?.can_orion_dashboard !== false
  const canTally = Boolean(user?.can_tally_dashboard)

  if (!canOrion && !canTally) {
    return (
      <div>
        <h1 className="mb-4 text-sm font-semibold text-accent">Dashboards</h1>
        <Alert variant="error">
          You do not have access to the Orion or Tally dashboards. Contact an administrator.
        </Alert>
      </div>
    )
  }

  if (canOrion && !canTally) return <Navigate to="/dashboard/orion" replace />
  if (canTally && !canOrion) return <Navigate to="/dashboard/tally" replace />

  return (
    <div className="mx-auto max-w-4xl pb-4">
      <h1 className="mb-1 text-sm font-semibold text-accent">Dashboards</h1>
      <p className="mb-6 text-sm text-[color:var(--color-text-muted)]">
        Choose which view of the business you want to open.
      </p>
      <div className="stagger-in grid gap-5 overflow-visible py-2 lg:grid-cols-2">
        <IntentCard
          tone="teal"
          icon={Layers}
          badge="Orion"
          title="Orion dashboard"
          body="Operations as planned in Orion: leadership, revenue, delivery, people, pipeline, and fleet."
          chips={['Leadership', 'Revenue', 'People']}
          cta="Open Orion"
          onClick={() => navigate('/dashboard/orion')}
        />
        <IntentCard
          tone="violet"
          icon={BookOpen}
          badge="Tally Prime"
          title="Tally dashboard"
          body="Current billed state of the business from the Tally warehouse: invoices, GST, income mix, and debtors."
          chips={['Billed', 'GST', 'Clients']}
          cta="Open Tally"
          onClick={() => navigate('/dashboard/tally')}
        />
      </div>
    </div>
  )
}
