import { useEffect, useState } from 'react'
import { errorMessage, workspaces as workspacesApi } from '../api/client.js'
import { Spinner } from './StatusViews.jsx'

const MANAGERS = ['OWNER', 'ADMIN']
const ROLE_ORDER = { OWNER: 0, ADMIN: 1, MEMBER: 2 }

/**
 * Who is in the workspace, and the membership actions the caller's role
 * allows. The rules mirror the backend's, which stays the authority: anything
 * hidden here would be refused there anyway.
 */
export default function MembersPanel({
  workspace,
  myUserId,
  online,
  displayName,
  refreshing,
  onChanged,
  onLeft,
  onClose,
}) {
  const myRole = workspace.my_role
  const canManage = MANAGERS.includes(myRole)

  const [email, setEmail] = useState('')
  const [role, setRole] = useState('MEMBER')
  const [adding, setAdding] = useState(false)
  const [addError, setAddError] = useState(null)
  const [added, setAdded] = useState(null)

  const [confirmRemove, setConfirmRemove] = useState(null) // user id awaiting "Yes, remove"
  const [busyId, setBusyId] = useState(null)
  const [rowError, setRowError] = useState(null) // { userId, message }

  const [confirmLeave, setConfirmLeave] = useState(false)
  const [leaving, setLeaving] = useState(false)
  const [leaveError, setLeaveError] = useState(null)

  useEffect(() => {
    function onKey(event) {
      if (event.key === 'Escape') onClose()
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [onClose])

  function canRemove(member) {
    if (!canManage || member.user_id === myUserId) return false
    // Removing an owner takes an owner (and the backend keeps the last one).
    return member.role !== 'OWNER' || myRole === 'OWNER'
  }

  async function handleAdd(event) {
    event.preventDefault()
    const address = email.trim()
    if (!address) return
    setAdding(true)
    setAddError(null)
    setAdded(null)
    try {
      const member = await workspacesApi.addMember(workspace.id, { email: address, role })
      setEmail('')
      setRole('MEMBER')
      setAdded(`${member.email} was added as ${member.role}.`)
      await onChanged()
    } catch (err) {
      // The common case deserves a better answer than "No such user."
      setAddError(
        err?.response?.status === 404
          ? 'No account uses that email. They need to sign up first.'
          : errorMessage(err),
      )
    } finally {
      setAdding(false)
    }
  }

  async function handleRemove(member) {
    setBusyId(member.user_id)
    setRowError(null)
    setAdded(null)
    try {
      await workspacesApi.removeMember(workspace.id, member.user_id)
      setConfirmRemove(null)
      await onChanged()
    } catch (err) {
      setRowError({ userId: member.user_id, message: errorMessage(err) })
    } finally {
      setBusyId(null)
    }
  }

  async function handleLeave() {
    setLeaving(true)
    setLeaveError(null)
    try {
      await workspacesApi.leave(workspace.id)
      onLeft()
    } catch (err) {
      setLeaveError({
        lastOwner: err?.response?.status === 409,
        message: errorMessage(err),
      })
      setConfirmLeave(false)
    } finally {
      setLeaving(false)
    }
  }

  const members = [...workspace.members].sort(
    (a, b) =>
      ROLE_ORDER[a.role] - ROLE_ORDER[b.role] ||
      displayName(a.email).localeCompare(displayName(b.email)),
  )

  return (
    <div className="modal-backdrop" onClick={onClose} role="presentation">
      <div
        className="modal"
        onClick={(e) => e.stopPropagation()}
        role="dialog"
        aria-modal="true"
        aria-label="Members"
      >
        <header className="modal-head">
          <h2>
            Members <span className="muted">({workspace.members.length})</span>
            {refreshing && <Spinner label="Updating members…" />}
          </h2>
          <button type="button" className="btn btn-quiet" onClick={onClose} aria-label="Close">
            ✕
          </button>
        </header>

        <div className="modal-body">
          <ul className="member-list">
            {members.map((member) => {
              const isMe = member.user_id === myUserId
              const pending = confirmRemove === member.user_id
              return (
                <li key={member.user_id} className="member-row">
                  <div className="member-who">
                    <span
                      className={`presence-dot ${online.has(member.user_id) ? '' : 'is-away'}`}
                      title={online.has(member.user_id) ? 'Online now' : 'Not online'}
                      aria-hidden="true"
                    />
                    <span className="member-name" title={member.email}>
                      {displayName(member.email)}
                      {isMe && <span className="muted"> (you)</span>}
                    </span>
                    <span className={`role-badge role-${member.role.toLowerCase()}`}>{member.role}</span>
                  </div>

                  {canRemove(member) && (
                    <div className="member-actions">
                      {pending ? (
                        <>
                          <button
                            type="button"
                            className="btn btn-danger"
                            onClick={() => handleRemove(member)}
                            disabled={busyId === member.user_id}
                          >
                            {busyId === member.user_id ? 'Removing…' : 'Yes, remove'}
                          </button>
                          <button type="button" className="btn btn-quiet" onClick={() => setConfirmRemove(null)}>
                            Cancel
                          </button>
                        </>
                      ) : (
                        <button
                          type="button"
                          className="btn btn-danger-quiet"
                          onClick={() => {
                            setConfirmRemove(member.user_id)
                            setRowError(null)
                          }}
                          aria-label={`Remove ${displayName(member.email)}`}
                        >
                          Remove
                        </button>
                      )}
                    </div>
                  )}

                  {rowError?.userId === member.user_id && (
                    <p className="alert member-error" role="alert">{rowError.message}</p>
                  )}
                </li>
              )
            })}
          </ul>

          {canManage ? (
            <form className="add-member" onSubmit={handleAdd}>
              <label htmlFor="member-email">Add a member</label>
              <div className="add-member-row">
                <input
                  id="member-email"
                  type="email"
                  value={email}
                  placeholder="teammate@example.com"
                  required
                  onChange={(e) => {
                    setEmail(e.target.value)
                    setAddError(null)
                  }}
                />
                <select value={role} onChange={(e) => setRole(e.target.value)} aria-label="Role">
                  <option value="MEMBER">Member</option>
                  {/* Only an owner can grant ADMIN; the backend refuses it from anyone else. */}
                  {myRole === 'OWNER' && <option value="ADMIN">Admin</option>}
                </select>
                <button type="submit" className="btn btn-primary" disabled={adding || !email.trim()}>
                  {adding ? 'Adding…' : 'Add'}
                </button>
              </div>
              <p className="hint">They need a CollabSpace account with this email.</p>
              {addError && <p className="alert" role="alert">{addError}</p>}
              {added && !addError && <p className="success" role="status">{added}</p>}
            </form>
          ) : (
            <p className="hint member-hint">Only owners and admins can add or remove members.</p>
          )}

          <div className="leave-zone">
            {confirmLeave ? (
              <div className="leave-confirm">
                <span>Leave {workspace.name}? You'll lose access to its board.</span>
                <div className="modal-actions">
                  <button type="button" className="btn btn-danger" onClick={handleLeave} disabled={leaving}>
                    {leaving ? 'Leaving…' : 'Yes, leave'}
                  </button>
                  <button type="button" className="btn btn-quiet" onClick={() => setConfirmLeave(false)}>
                    Cancel
                  </button>
                </div>
              </div>
            ) : (
              <button
                type="button"
                className="btn btn-danger-quiet"
                onClick={() => {
                  setConfirmLeave(true)
                  setLeaveError(null)
                  setAdded(null)
                }}
              >
                Leave workspace
              </button>
            )}

            {leaveError && (
              <div className={leaveError.lastOwner ? 'notice' : 'alert'} role="alert">
                {leaveError.lastOwner && <strong>You can't leave yet. </strong>}
                {leaveError.message}
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  )
}
