import { Link, Outlet } from 'react-router-dom'
import { useAuth } from '../context/AuthContext.jsx'
import BackendStatus from './BackendStatus.jsx'

export default function Layout() {
  const { user, logout, isAuthenticated, isGuest } = useAuth()

  return (
    <div className="app">
      <header className="app-header">
        <Link to="/" className="brand">CollabSpace</Link>
        <div className="header-right">
          <BackendStatus />
          {isAuthenticated && (
            <>
              <span className="muted">{isGuest ? 'Guest' : user.email}</span>
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
        <Outlet />
      </main>
    </div>
  )
}
