import { useState } from 'react'
import { Navigate, useLocation, useNavigate } from 'react-router-dom'
import { errorMessage } from '../api/client.js'
import { useAuth } from '../context/AuthContext.jsx'
import { isGuestEnabled } from '../api/guest.js'

export default function Login() {
  const { login, register, loginAsGuest, isAuthenticated, loading } = useAuth()
  const navigate = useNavigate()
  const location = useLocation()

  const [mode, setMode] = useState('login')
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState(null)
  const [busy, setBusy] = useState(false)
  const [guestBusy, setGuestBusy] = useState(false)

  const isRegister = mode === 'register'
  const destination = location.state?.from?.pathname ?? '/workspaces'

  if (loading) return <p className="muted centered">Loading…</p>
  if (isAuthenticated) return <Navigate to={destination} replace />

  async function handleSubmit(event) {
    event.preventDefault()
    setError(null)
    setBusy(true)
    try {
      if (isRegister) await register(email, password)
      else await login(email, password)
      navigate(destination, { replace: true })
    } catch (err) {
      setError(errorMessage(err))
    } finally {
      setBusy(false)
    }
  }

  async function handleGuest() {
    setError(null)
    setGuestBusy(true)
    try {
      await loginAsGuest()
      navigate(destination, { replace: true })
    } catch (err) {
      setError(errorMessage(err))
    } finally {
      setGuestBusy(false)
    }
  }

  return (
    <div className="auth-wrap">
      <form className="card auth-card" onSubmit={handleSubmit}>
        <h1>{isRegister ? 'Create an account' : 'Log in'}</h1>

        <label htmlFor="email">Email</label>
        <input
          id="email"
          type="email"
          value={email}
          autoComplete="email"
          required
          onChange={(e) => setEmail(e.target.value)}
        />

        <label htmlFor="password">Password</label>
        <input
          id="password"
          type="password"
          value={password}
          autoComplete={isRegister ? 'new-password' : 'current-password'}
          required
          minLength={isRegister ? 8 : undefined}
          onChange={(e) => setPassword(e.target.value)}
        />
        {isRegister && <p className="hint">At least 8 characters.</p>}

        {error && <p className="alert" role="alert">{error}</p>}

        <button type="submit" className="btn btn-primary" disabled={busy}>
          {busy ? 'Working…' : isRegister ? 'Create account' : 'Log in'}
        </button>

        {isGuestEnabled() && (
          <div className="guest-block">
            <div className="divider"><span>or</span></div>
            <button
              type="button"
              className="btn btn-guest"
              onClick={handleGuest}
              disabled={busy || guestBusy}
            >
              {guestBusy ? 'Setting up…' : 'Continue as guest'}
            </button>
            <p className="hint">
              Creates a throwaway account with a demo board so you can look around.
              No email needed.
            </p>
          </div>
        )}

        <p className="muted switch-mode">
          {isRegister ? 'Already have an account?' : 'No account yet?'}{' '}
          <button
            type="button"
            className="btn-link"
            onClick={() => {
              setMode(isRegister ? 'login' : 'register')
              setError(null)
            }}
          >
            {isRegister ? 'Log in' : 'Create one'}
          </button>
        </p>
      </form>
    </div>
  )
}
