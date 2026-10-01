/** Shared loading / error placeholders, so every page fails and waits the same way. */

export function Spinner({ label = 'Loading…' }) {
  return (
    <span className="spinner-wrap" role="status">
      <span className="spinner" aria-hidden="true" />
      <span className="visually-hidden">{label}</span>
    </span>
  )
}

/** A failed load: what went wrong, and a way to try again. */
export function ErrorState({ title = 'Something went wrong', message, onRetry, children }) {
  return (
    <div className="error-state" role="alert">
      <p className="error-state-title">{title}</p>
      {message && <p className="error-state-message">{message}</p>}
      <div className="error-state-actions">
        {onRetry && (
          <button type="button" className="btn btn-primary" onClick={onRetry}>
            Try again
          </button>
        )}
        {children}
      </div>
    </div>
  )
}

/** Grey placeholder shapes, laid out like the content they stand in for. */
export function DashboardSkeleton() {
  return (
    <ul className="workspace-list" aria-busy="true" aria-label="Loading workspaces">
      {[0, 1, 2].map((i) => (
        <li key={i} className="card skeleton-card">
          <span className="skeleton skeleton-line" style={{ width: `${45 + i * 12}%` }} />
          <span className="skeleton skeleton-pill" />
        </li>
      ))}
    </ul>
  )
}

export function BoardSkeleton() {
  return (
    <section className="page board-page" aria-busy="true" aria-label="Loading board">
      <div className="page-head">
        <div>
          <span className="skeleton skeleton-line" style={{ width: '7rem' }} />
          <span className="skeleton skeleton-title" />
          <span className="skeleton skeleton-line" style={{ width: '12rem' }} />
        </div>
      </div>
      <div className="board">
        {[2, 1, 1].map((cards, col) => (
          <div key={col} className="column">
            <span className="skeleton skeleton-line" style={{ width: '5rem', marginBottom: '0.9rem' }} />
            <div className="column-body">
              {Array.from({ length: cards }, (_, i) => (
                <div key={i} className="card task-card">
                  <span className="skeleton skeleton-line" style={{ width: '80%' }} />
                  <span className="skeleton skeleton-line" style={{ width: '45%', marginTop: '0.6rem' }} />
                </div>
              ))}
            </div>
          </div>
        ))}
      </div>
    </section>
  )
}
