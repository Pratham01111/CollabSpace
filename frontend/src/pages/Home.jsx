import { useEffect, useState } from 'react'
import { getHealth } from '../api/client.js'

export default function Home() {
  const [status, setStatus] = useState('checking...')
  const [error, setError] = useState(null)

  useEffect(() => {
    let cancelled = false

    getHealth()
      .then((data) => {
        if (!cancelled) setStatus(data.status)
      })
      .catch((err) => {
        if (!cancelled) setError(err.message)
      })

    return () => {
      cancelled = true
    }
  }, [])

  return (
    <section>
      <h1>Welcome to CollabSpace</h1>
      {error ? (
        <p className="status status-error">Backend status: unreachable ({error})</p>
      ) : (
        <p className="status">Backend status: {status}</p>
      )}
    </section>
  )
}
