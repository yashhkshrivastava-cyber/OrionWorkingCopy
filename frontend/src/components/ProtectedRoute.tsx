import { Navigate, Outlet } from 'react-router-dom'
import { useAuth } from '../context/AuthContext'
import { LoadingState } from './ui/DataTable'

function AuthSpinner() {
  return (
    <div className="flex min-h-[50vh] items-center justify-center">
      <LoadingState message="Authenticating…" />
    </div>
  )
}

export function ProtectedRoute() {
  const { user, loading } = useAuth()

  if (loading) return <AuthSpinner />
  if (!user) return <Navigate to="/login" replace />

  return <Outlet />
}

export function AdminRoute() {
  const { user, loading } = useAuth()
  if (loading) return <AuthSpinner />
  if (!user) return <Navigate to="/login" replace />
  if (user.role !== 'admin') return <Navigate to="/" replace />
  return <Outlet />
}

export function DashboardRoute() {
  const { user, loading } = useAuth()
  if (loading) return <AuthSpinner />
  if (!user) return <Navigate to="/login" replace />
  if (user.can_orion_dashboard === false && user.can_tally_dashboard !== true) {
    return <Navigate to="/" replace />
  }
  return <Outlet />
}

export function UtilityRoute() {
  const { user, loading } = useAuth()
  if (loading) return <AuthSpinner />
  if (!user) return <Navigate to="/login" replace />
  if (!user.pages.includes('utility')) return <Navigate to="/" replace />
  return <Outlet />
}

export function LetterheadRoute() {
  const { user, loading } = useAuth()
  if (loading) return <AuthSpinner />
  if (!user) return <Navigate to="/login" replace />
  if (!user.pages.includes('letterhead')) return <Navigate to="/" replace />
  return <Outlet />
}

export function DocumentsRoute() {
  const { user, loading } = useAuth()
  if (loading) return <AuthSpinner />
  if (!user) return <Navigate to="/login" replace />
  if (!user.pages.includes('documents')) return <Navigate to="/" replace />
  return <Outlet />
}

export function BankRoute() {
  const { user, loading } = useAuth()
  if (loading) return <AuthSpinner />
  if (!user) return <Navigate to="/login" replace />
  if (!user.pages.includes('bank')) return <Navigate to="/" replace />
  return <Outlet />
}

export function TendersRoute() {
  const { user, loading } = useAuth()
  if (loading) return <AuthSpinner />
  if (!user) return <Navigate to="/login" replace />
  if (!user.pages.includes('tenders')) return <Navigate to="/" replace />
  return <Outlet />
}

export function AttendanceRoute() {
  const { user, loading } = useAuth()
  if (loading) return <AuthSpinner />
  if (!user) return <Navigate to="/login" replace />
  if (!user.pages.includes('attendance')) return <Navigate to="/" replace />
  return <Outlet />
}

export function SqlRoute() {
  const { user, loading } = useAuth()
  if (loading) return <AuthSpinner />
  if (!user) return <Navigate to="/login" replace />
  if (!user.pages.includes('sql')) return <Navigate to="/" replace />
  return <Outlet />
}

export function EtlRoute() {
  const { user, loading } = useAuth()
  if (loading) return <AuthSpinner />
  if (!user) return <Navigate to="/login" replace />
  if (!user.pages.includes('etl')) return <Navigate to="/" replace />
  return <Outlet />
}

export function DataRoute() {
  const { user, loading } = useAuth()
  if (loading) return <AuthSpinner />
  if (!user) return <Navigate to="/login" replace />
  if (
    !user.can_ods &&
    !user.can_ods_write &&
    !user.can_dw &&
    !user.can_dw_write &&
    !user.can_tally &&
    !user.can_tally_write &&
    !user.can_tally_dw &&
    !user.can_tally_dw_write
  ) {
    return <Navigate to="/" replace />
  }
  return <Outlet />
}
