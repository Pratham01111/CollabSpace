import { useCallback, useEffect, useRef, useState } from 'react'
import { notifyUnauthorized, socketUrl } from '../api/client.js'

// Retry 1s, 2s, 4s, 8s, 16s, 30s (each jittered), then give up and show
// Offline with a manual retry, instead of hammering a server that is down.
const MAX_ATTEMPTS = 6
const BASE_DELAY_MS = 1000
const MAX_DELAY_MS = 30_000

// Close codes from the server that retrying cannot fix.
const CLOSE_UNAUTHORIZED = 4401
const CLOSE_WORKSPACE_NOT_FOUND = 4404

function backoffDelay(attempt) {
  const ceiling = Math.min(MAX_DELAY_MS, BASE_DELAY_MS * 2 ** attempt)
  // Jitter, so a server restart is not met by every client in the same instant.
  return ceiling / 2 + (Math.random() * ceiling) / 2
}

/**
 * Keeps a WebSocket open to one workspace and hands each server event to
 * `onEvent`.
 *
 * `onConnected(message)` fires on every successful (re)connect, with the
 * server's "connected" message (which carries who is online). Events sent
 * while the socket was down are gone, so that is the caller's cue to resync.
 * `onLostAccess` fires if the server says the user is no longer a member.
 *
 * Returns `{ status, retry }`, where status is one of
 * 'connecting' | 'connected' | 'reconnecting' | 'offline'.
 */
export default function useWorkspaceSocket(workspaceId, { onEvent, onConnected, onLostAccess }) {
  const [status, setStatus] = useState('connecting')
  const [generation, setGeneration] = useState(0)

  // The socket outlives any one render, so it reads the latest callbacks
  // through a ref rather than reconnecting whenever they change identity.
  const handlers = useRef({ onEvent, onConnected, onLostAccess })
  useEffect(() => {
    handlers.current = { onEvent, onConnected, onLostAccess }
  })

  useEffect(() => {
    let socket = null
    let timer = null
    let attempt = 0
    let disposed = false

    function open() {
      timer = null
      if (!navigator.onLine) {
        // No point dialling out; the 'online' listener picks it back up.
        setStatus('offline')
        return
      }

      const ws = new WebSocket(socketUrl(`/ws/workspaces/${workspaceId}`))
      socket = ws

      ws.onmessage = (message) => {
        let event
        try {
          event = JSON.parse(message.data)
        } catch {
          return
        }
        // "connected" rather than onopen: it means the server accepted the
        // token and membership, not just that the TCP handshake finished.
        if (event.type === 'connected') {
          attempt = 0
          setStatus('connected')
          handlers.current.onConnected?.(event)
          return
        }
        handlers.current.onEvent?.(event)
      }

      // onerror is always followed by onclose, which is where it is handled.
      ws.onclose = (event) => {
        if (socket === ws) socket = null
        if (disposed) return

        if (event.code === CLOSE_UNAUTHORIZED) {
          setStatus('offline')
          notifyUnauthorized()
          return
        }
        if (event.code === CLOSE_WORKSPACE_NOT_FOUND) {
          setStatus('offline')
          handlers.current.onLostAccess?.()
          return
        }
        if (!navigator.onLine) {
          setStatus('offline')
          return
        }
        if (attempt >= MAX_ATTEMPTS) {
          setStatus('offline')
          return
        }
        setStatus('reconnecting')
        timer = setTimeout(open, backoffDelay(attempt))
        attempt += 1
      }
    }

    function handleOnline() {
      if (socket) return
      clearTimeout(timer)
      attempt = 0
      setStatus('reconnecting')
      open()
    }

    function handleOffline() {
      clearTimeout(timer)
      timer = null
      setStatus('offline')
      // Browsers can take a long time to notice a dead socket on their own.
      socket?.close()
    }

    setStatus('connecting')
    open()
    window.addEventListener('online', handleOnline)
    window.addEventListener('offline', handleOffline)

    return () => {
      disposed = true
      clearTimeout(timer)
      window.removeEventListener('online', handleOnline)
      window.removeEventListener('offline', handleOffline)
      socket?.close(1000, 'Leaving workspace')
    }
  }, [workspaceId, generation])

  // A fresh connection cycle with the attempt count reset.
  const retry = useCallback(() => setGeneration((n) => n + 1), [])

  return { status, retry }
}
