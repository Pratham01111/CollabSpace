const LABELS = {
  connecting: 'Connecting…',
  connected: 'Connected',
  reconnecting: 'Reconnecting…',
  offline: 'Offline',
}

/** Live-update connection state for the board, with a manual retry once it gives up. */
export default function ConnectionStatus({ status, onRetry }) {
  return (
    <span className={`connection-status is-${status}`} role="status">
      <span className="dot" aria-hidden="true" />
      {LABELS[status]}
      {status === 'offline' && (
        <button type="button" className="btn-link" onClick={onRetry}>
          Retry
        </button>
      )}
    </span>
  )
}
