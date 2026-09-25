import { useEffect, useState } from 'react'
import { STATUSES, statusLabel } from '../constants.js'

/**
 * Task detail. Editing is local until Save, so a half-typed title never
 * reaches the server.
 */
export default function TaskDetail({
  task,
  authorName,
  comments,
  onAddComment,
  onSave,
  onDelete,
  onClose,
  busy,
  error,
}) {
  const [title, setTitle] = useState(task.title)
  const [description, setDescription] = useState(task.description ?? '')
  const [status, setStatus] = useState(task.status)
  const [commentBody, setCommentBody] = useState('')
  const [confirmingDelete, setConfirmingDelete] = useState(false)

  // Re-sync when a different card is opened, or when a save returns fresh data.
  useEffect(() => {
    setTitle(task.title)
    setDescription(task.description ?? '')
    setStatus(task.status)
    setConfirmingDelete(false)
  }, [task.id, task.title, task.description, task.status])

  useEffect(() => {
    function onKey(event) {
      if (event.key === 'Escape') onClose()
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [onClose])

  const dirty =
    title !== task.title || description !== (task.description ?? '') || status !== task.status

  function handleSave(event) {
    event.preventDefault()
    const changes = {}
    if (title !== task.title) changes.title = title.trim()
    // An emptied box means "no description", which the API models as null.
    if (description !== (task.description ?? '')) changes.description = description.trim() || null
    if (status !== task.status) changes.status = status
    onSave(changes)
  }

  function handleAddComment(event) {
    event.preventDefault()
    if (!commentBody.trim()) return
    onAddComment(commentBody.trim())
    setCommentBody('')
  }

  return (
    <div className="modal-backdrop" onClick={onClose} role="presentation">
      <div
        className="modal"
        onClick={(e) => e.stopPropagation()}
        role="dialog"
        aria-modal="true"
        aria-label="Task detail"
      >
        <header className="modal-head">
          <h2>Task</h2>
          <button type="button" className="btn btn-quiet" onClick={onClose} aria-label="Close">
            ✕
          </button>
        </header>

        <form className="modal-body" onSubmit={handleSave}>
          <label htmlFor="task-title">Title</label>
          <input
            id="task-title"
            value={title}
            required
            maxLength={255}
            onChange={(e) => setTitle(e.target.value)}
          />

          <label htmlFor="task-desc">Description</label>
          <textarea
            id="task-desc"
            rows={4}
            value={description}
            placeholder="No description"
            onChange={(e) => setDescription(e.target.value)}
          />

          <label htmlFor="task-status">Status</label>
          <select id="task-status" value={status} onChange={(e) => setStatus(e.target.value)}>
            {STATUSES.map((s) => (
              <option key={s} value={s}>
                {statusLabel(s)}
              </option>
            ))}
          </select>

          <dl className="task-facts">
            <div>
              <dt>Created by</dt>
              <dd>{authorName}</dd>
            </div>
            <div>
              <dt>Created</dt>
              <dd>{new Date(task.created_at).toLocaleString()}</dd>
            </div>
            <div>
              <dt>Updated</dt>
              <dd>{new Date(task.updated_at).toLocaleString()}</dd>
            </div>
            <div>
              <dt>Version</dt>
              <dd>{task.version}</dd>
            </div>
          </dl>

          {error && <p className="alert" role="alert">{error}</p>}

          <div className="modal-actions">
            <button type="submit" className="btn btn-primary" disabled={!dirty || busy}>
              {busy ? 'Saving…' : 'Save changes'}
            </button>
            {confirmingDelete ? (
              <>
                <span className="muted">Delete this task?</span>
                <button type="button" className="btn btn-danger" onClick={onDelete} disabled={busy}>
                  Yes, delete
                </button>
                <button
                  type="button"
                  className="btn btn-quiet"
                  onClick={() => setConfirmingDelete(false)}
                >
                  Cancel
                </button>
              </>
            ) : (
              <button
                type="button"
                className="btn btn-danger-quiet"
                onClick={() => setConfirmingDelete(true)}
                disabled={busy}
              >
                Delete task
              </button>
            )}
          </div>
        </form>

        <section className="comments">
          <h3>Comments</h3>
          <p className="hint">
            Not saved yet — these live in the browser until the comments API lands in Phase 9.
          </p>

          <ul className="comment-list">
            {comments.length === 0 && <li className="muted">No comments yet.</li>}
            {comments.map((comment) => (
              <li key={comment.id} className="comment">
                <p className="comment-meta">
                  {comment.author} · {new Date(comment.created_at).toLocaleTimeString()}
                </p>
                <p>{comment.body}</p>
              </li>
            ))}
          </ul>

          <form className="inline-form" onSubmit={handleAddComment}>
            <input
              value={commentBody}
              placeholder="Write a comment…"
              onChange={(e) => setCommentBody(e.target.value)}
            />
            <button type="submit" className="btn" disabled={!commentBody.trim()}>
              Add
            </button>
          </form>
        </section>
      </div>
    </div>
  )
}
