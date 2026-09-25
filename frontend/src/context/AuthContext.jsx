import { createContext, useCallback, useContext, useEffect, useMemo, useState } from 'react'
import { auth, getToken, setToken, setUnauthorizedHandler } from '../api/client.js'
import { clearGuest, createGuestAccount, getStoredGuest, seedGuestData } from '../api/guest.js'

const AuthContext = createContext(null)

export function AuthProvider({ children }) {
  const [user, setUser] = useState(null)
  const [isGuest, setIsGuest] = useState(false)
  // Starts true so protected routes wait for the stored token to be checked
  // instead of bouncing to /login on every refresh.
  const [loading, setLoading] = useState(true)

  const logout = useCallback(() => {
    setToken(null)
    setUser(null)
    // The guest credentials stay in localStorage on purpose, so "Continue as
    // guest" returns to the same sandbox rather than stranding its data.
    setIsGuest(false)
  }, [])

  useEffect(() => {
    setUnauthorizedHandler(logout)
    return () => setUnauthorizedHandler(null)
  }, [logout])

  useEffect(() => {
    let cancelled = false

    async function restore() {
      if (!getToken()) {
        if (!cancelled) setLoading(false)
        return
      }
      try {
        const me = await auth.me()
        if (!cancelled) {
          setUser(me)
          setIsGuest(getStoredGuest()?.email === me.email)
        }
      } catch {
        // Expired or tampered-with token: drop it and start clean.
        if (!cancelled) setToken(null)
      } finally {
        if (!cancelled) setLoading(false)
      }
    }

    restore()
    return () => {
      cancelled = true
    }
  }, [])

  const login = useCallback(async (email, password) => {
    const { access_token: accessToken } = await auth.login(email, password)
    setToken(accessToken)
    const me = await auth.me()
    setUser(me)
    setIsGuest(getStoredGuest()?.email === me.email)
    return me
  }, [])

  const register = useCallback(
    async (email, password) => {
      await auth.register(email, password)
      return login(email, password)
    },
    [login],
  )

  /** Resume an existing guest sandbox, or provision a fresh one and seed it. */
  const loginAsGuest = useCallback(async () => {
    const existing = getStoredGuest()
    if (existing) {
      try {
        return await login(existing.email, existing.password)
      } catch {
        // The account was wiped from the database behind us; start over.
        clearGuest()
      }
    }

    const credentials = await createGuestAccount()

    // Authenticate without publishing the user yet. Setting it here would flip
    // isAuthenticated, and the login page redirects on that the moment it
    // changes — so the guest would land on the dashboard while the demo tasks
    // were still being created, and see a half-filled board.
    const { access_token: accessToken } = await auth.login(credentials.email, credentials.password)
    setToken(accessToken)

    try {
      await seedGuestData()
    } catch {
      // A guest with an empty dashboard is still usable, so a failed seed
      // should not fail the sign-in.
    }

    const me = await auth.me()
    setUser(me)
    setIsGuest(true)
    return me
  }, [login])

  const value = useMemo(
    () => ({
      user,
      loading,
      login,
      register,
      loginAsGuest,
      logout,
      isGuest,
      isAuthenticated: Boolean(user),
    }),
    [user, loading, login, register, loginAsGuest, logout, isGuest],
  )

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>
}

export function useAuth() {
  const context = useContext(AuthContext)
  if (!context) throw new Error('useAuth must be used inside an AuthProvider')
  return context
}
