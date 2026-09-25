import { useEffect, useState } from 'react'
import { getHealth } from '../api/client.js'

/** The Phase 1 health check, kept on as a live indicator in the header. */
export default function BackendStatus() {
  const [status, setStatus] = useState('checking')

  useEffect(() => {
    let cancelled = false
    getHealth()
      .then((data) => !cancelled && setStatus(data.status))
      .catch(() => !cancelled && setStatus('unreachable'))
    return () => {
      cancelled = true
    }
  }, [])

  const ok = status === 'ok'
  return (
    <span className={`backend-status ${ok ? 'is-ok' : 'is-down'}`} title={`Backend status: ${status}`}>
      <span className="dot" aria-hidden="true" />
      Backend: {status}
    </span>
  )
}
