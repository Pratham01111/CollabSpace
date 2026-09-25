import { useCallback, useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { errorMessage, workspaces as workspacesApi } from '../api/client.js'

export default function Dashboard() {
  const [items, setItems] = useState([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)

  const [creating, setCreating] = useState(false)
  const [name, setName] = useState('')
  const [createError, setCreateError] = useState(null)
  const [busy, setBusy] = useState(false)

  const load = useCallback(async () => {
    setLoading(true)
    try {
      setItems(await workspacesApi.list())
      setError(null)
    } catch (err) {
      setError(errorMessage(err))
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    load()
  }, [load])

  async function handleCreate(event) {
    event.preventDefault()
    setCreateError(null)
    setBusy(true)
    try {
      const created = await workspacesApi.create(name.trim())
      setItems((current) => [...current, created])
      setName('')
      setCreating(false)
    } catch (err) {
      setCreateError(errorMessage(err))
    } finally {
      setBusy(false)
    }
  }

  return (
    <section className="page">
      <div className="page-head">
        <h1>My Workspaces</h1>
        {!creating && (
          <button type="button" className="btn btn-primary" onClick={() => setCreating(true)}>
            + Create Workspace
          </button>
        )}
      </div>

      {creating && (
        <form className="card inline-form" onSubmit={handleCreate}>
          <input
            type="text"
            value={name}
            placeholder="Workspace name"
            autoFocus
            required
            maxLength={120}
            onChange={(e) => setName(e.target.value)}
          />
          <button type="submit" className="btn btn-primary" disabled={busy || !name.trim()}>
            {busy ? 'Creating…' : 'Create'}
          </button>
          <button
            type="button"
            className="btn btn-quiet"
            onClick={() => {
              setCreating(false)
              setName('')
              setCreateError(null)
            }}
          >
            Cancel
          </button>
          {createError && <p className="alert" role="alert">{createError}</p>}
        </form>
      )}

      {loading && <p className="muted">Loading workspaces…</p>}
      {error && <p className="alert" role="alert">{error}</p>}

      {!loading && !error && items.length === 0 && (
        <p className="muted empty">No workspaces yet. Create one to get started.</p>
      )}

      <ul className="workspace-list">
        {items.map((workspace) => (
          <li key={workspace.id}>
            <Link to={`/workspaces/${workspace.id}`} className="card workspace-card">
              <span className="workspace-name">{workspace.name}</span>
              <span className={`role-badge role-${workspace.my_role.toLowerCase()}`}>
                {workspace.my_role}
              </span>
            </Link>
          </li>
        ))}
      </ul>
    </section>
  )
}
