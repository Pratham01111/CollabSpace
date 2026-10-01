/** Who has this workspace open right now. Only meaningful while connected. */
export default function OnlineNow({ users, myUserId, connected, displayName }) {
  if (!connected) {
    return (
      <div className="online-now">
        <span className="online-label">Online now</span>
        <span className="muted">unknown while disconnected</span>
      </div>
    )
  }

  // You first, then everyone else alphabetically.
  const sorted = [...users].sort((a, b) => {
    if (a.id === myUserId) return -1
    if (b.id === myUserId) return 1
    return displayName(a.email).localeCompare(displayName(b.email))
  })

  return (
    <div className="online-now">
      <span className="online-label">Online now</span>
      <ul className="online-list">
        {sorted.map((user) => (
          <li key={user.id} className="online-user" title={user.email}>
            <span className="presence-dot" aria-hidden="true" />
            {displayName(user.email)}
            {user.id === myUserId && <span className="muted"> (you)</span>}
          </li>
        ))}
      </ul>
    </div>
  )
}
