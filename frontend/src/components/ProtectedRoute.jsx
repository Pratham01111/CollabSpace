import { Navigate, Outlet, useLocation } from 'react-router-dom'
import { useAuth } from '../context/AuthContext.jsx'

export default function ProtectedRoute() {
  const { isAuthenticated, loading } = useAuth()
  const location = useLocation()

  // While the stored token is being checked we know nothing yet; redirecting
  // here would sign people out on every page refresh.
  if (loading) return <p className="muted centered">Loading…</p>

  // Remember where they were headed so login can send them back there.
  if (!isAuthenticated) return <Navigate to="/login" replace state={{ from: location }} />

  return <Outlet />
}
