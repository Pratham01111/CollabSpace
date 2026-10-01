import { useEffect, useRef, useState } from 'react'
import { errorMessage } from '../api/client.js'
import { STATUSES, statusLabel } from '../constants.js'

/**
 * Task detail. Editing is local until Save, so a half-typed title never
 * reaches the server.
 */
export default function TaskDetail({
  task,
  authorName,
  comments,
  commentsLoading,
  commentsError,
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
  const [posting, setPosting] = useState(false)
  const [postError, setPostError] = useState(null)
  const [confirmingDelete, setConfirmingDelete] = useState(false)
  // The version the form's contents are based on, sent as expected_version.
  // Not simply task.version: the task updates live, and quoting the newest
  // version for an edit begun on an older one would overwrite unseen changes.
  const [baseVersion, setBaseVersion] = useState(task.version)

  function showTask(t) {
    setTitle(t.title)
    setDescription(t.description ?? '')
    setStatus(t.status)
    setBaseVersion(t.version)
  }

  // Re-sync the form when the task changes: a different card was opened, our
  // own save came back, or someone else's edit arrived over the socket. In
  // that last case, an edit in progress here is kept rather than wiped out.
  const shown = useRef(task)
  useEffect(() => {
    const before = shown.current
    shown.current = task
    if (before === task) return

    const untouched =
      title === before.title &&
      description === (before.description ?? '') &&
      status === before.status
    // What Save sends, after trimming: matching it means this is our save returning.
    const justSaved =
      title.trim() === task.title &&
      (description.trim() || null) === task.description &&
      status === task.status

    if (task.id !== before.id || untouched || justSaved) showTask(task)
    if (task.id !== before.id) {
      setConfirmingDelete(false)
      setCommentBody('')
      setPostError(null)
    }
    // Reads the form fields but must run only when the task changes.
  }, [task])

  useEffect(() => {
    function onKey(event) {
      if (event.key === 'Escape') onClose()
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [onClose])

  const dirty =
    title !== task.title || description !== (task.description ?? '') || status !== task.status
  // Someone else's save landed while this form held unsaved edits.
  const outdated = dirty && task.version !== baseVersion

  async function handleSave(event) {
    event.preventDefault()
    const changes = {}
    if (title !== task.title) changes.title = title.trim()
    // An emptied box means "no description", which the API models as null.
    if (description !== (task.description ?? '')) changes.description = description.trim() || null
    if (status !== task.status) changes.status = status

    const conflict = await onSave(changes, baseVersion)
    // Refused: show the task as it now is. No merging; the user redoes their
    // edit on top of it if they still want it.
    if (conflict) showTask(conflict)
  }

  async function handleAddComment(event) {
    event.preventDefault()
    if (!commentBody.trim()) return
    setPosting(true)
    setPostError(null)
    try {
      await onAddComment(commentBody.trim())
      setCommentBody('')
    } catch (err) {
      // Keep what they typed so a failed post costs nothing to retry.
      setPostError(errorMessage(err))
    } finally {
      setPosting(false)
    }
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

          {outdated && !error && (
            <p className="notice" role="status">
              Someone else changed this task while you were editing. Saving now will be refused.
            </p>
          )}
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

          {commentsError && <p className="alert" role="alert">{commentsError}</p>}

          <ul className="comment-list">
            {comments.length === 0 && (
              <li className="muted">{commentsLoading ? 'Loading comments…' : 'No comments yet.'}</li>
            )}
            {comments.map((comment) => (
              <li key={comment.id} className="comment">
                <p className="comment-meta">
                  {comment.authorName} ·{' '}
                  {new Date(comment.created_at).toLocaleString(undefined, {
                    dateStyle: 'medium',
                    timeStyle: 'short',
                  })}
                </p>
                <p>{comment.body}</p>
              </li>
            ))}
          </ul>

          <form className="inline-form" onSubmit={handleAddComment}>
            <input
              value={commentBody}
              placeholder="Write a comment…"
              maxLength={5000}
              onChange={(e) => setCommentBody(e.target.value)}
            />
            <button type="submit" className="btn" disabled={posting || !commentBody.trim()}>
              {posting ? 'Posting…' : 'Add'}
            </button>
          </form>
          {postError && <p className="alert" role="alert">{postError}</p>}
        </section>
      </div>
    </div>
  )
}
