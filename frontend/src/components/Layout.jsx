import { Link, Outlet, useLocation } from 'react-router-dom'
import { useAuth } from '../context/AuthContext.jsx'
import BackendStatus from './BackendStatus.jsx'
import ErrorBoundary from './ErrorBoundary.jsx'

export default function Layout() {
  const { user, logout, isAuthenticated, isGuest } = useAuth()
  const location = useLocation()

  return (
    <div className="app">
      <header className="app-header">
        <Link to="/" className="brand">CollabSpace</Link>
        <div className="header-right">
          <BackendStatus />
          {isAuthenticated && (
            <>
              <span className="muted header-user" title={isGuest ? undefined : user.email}>
                {isGuest ? 'Guest' : user.email}
              </span>
              <button type="button" className="btn btn-quiet" onClick={logout}>
                Log out
              </button>
            </>
          )}
        </div>
      </header>
      {isGuest && (
        <p className="guest-banner">
          Guest mode — this is a temporary account. Everything you do here is really
          saved to the database, but the account is throwaway.
        </p>
      )}
      <main className="app-main">
        {/* Inside the layout, so the header and log out stay usable. */}
        {/* Keyed by path, so navigating away clears a crashed page. */}
        <ErrorBoundary key={location.pathname}>
          <Outlet />
        </ErrorBoundary>
      </main>
    </div>
  )
}
