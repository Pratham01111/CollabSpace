import { useCallback, useEffect, useMemo, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { errorMessage, tasks as tasksApi, workspaces as workspacesApi } from '../api/client.js'
import { useAuth } from '../context/AuthContext.jsx'
import { STATUSES, statusLabel } from '../constants.js'
import TaskCard from '../components/TaskCard.jsx'
import TaskDetail from '../components/TaskDetail.jsx'

/** The API identifies people by id; the member list is what turns one into a name. */
function displayName(email) {
  return email ? email.split('@')[0] : 'Unknown'
}

export default function Workspace() {
  const { id } = useParams()
  const { user } = useAuth()

  const [workspace, setWorkspace] = useState(null)
  const [taskList, setTaskList] = useState([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)

  const [openTaskId, setOpenTaskId] = useState(null)
  const [detailBusy, setDetailBusy] = useState(false)
  const [detailError, setDetailError] = useState(null)
  const [draggingId, setDraggingId] = useState(null)
  const [composing, setComposing] = useState(null) // which column has its form open
  const [newTitle, setNewTitle] = useState('')
  // Comments have no backend until Phase 9, so they live here for the session.
  const [commentsByTask, setCommentsByTask] = useState({})

  const load = useCallback(async () => {
    setLoading(true)
    try {
      const [detail, list] = await Promise.all([workspacesApi.get(id), tasksApi.list(id)])
      setWorkspace(detail)
      setTaskList(list)
      setError(null)
    } catch (err) {
      setError(errorMessage(err))
    } finally {
      setLoading(false)
    }
  }, [id])

  useEffect(() => {
    load()
  }, [load])

  const namesByUserId = useMemo(() => {
    const map = new Map()
    for (const member of workspace?.members ?? []) map.set(member.user_id, displayName(member.email))
    return map
  }, [workspace])

  // A task's author may have left the workspace, or been deleted entirely
  // (created_by goes null), so this has to tolerate a miss.
  const authorFor = useCallback(
    (task) => namesByUserId.get(task.created_by) ?? 'Unknown',
    [namesByUserId],
  )

  const byStatus = useMemo(() => {
    const groups = Object.fromEntries(STATUSES.map((s) => [s, []]))
    for (const task of taskList) groups[task.status]?.push(task)
    for (const status of STATUSES) groups[status].sort((a, b) => a.position - b.position)
    return groups
  }, [taskList])

  const openTask = taskList.find((t) => t.id === openTaskId) ?? null

  function replaceTask(updated) {
    setTaskList((current) => current.map((t) => (t.id === updated.id ? updated : t)))
  }

  async function handleCreate(event, status) {
    event.preventDefault()
    const title = newTitle.trim()
    if (!title) return
    try {
      const created = await tasksApi.create(id, { title, status })
      setTaskList((current) => [...current, created])
      setNewTitle('')
      setComposing(null)
    } catch (err) {
      setError(errorMessage(err))
    }
  }

  async function handleMove(task, status) {
    if (task.status === status) return
    // Show the card in its new column straight away; the server decides the
    // final position and we reconcile when it answers.
    const previous = taskList
    setTaskList((current) => current.map((t) => (t.id === task.id ? { ...t, status } : t)))
    try {
      replaceTask(await tasksApi.update(task.id, { status }))
    } catch (err) {
      setTaskList(previous)
      setError(errorMessage(err))
    }
  }

  async function handleSave(changes) {
    if (Object.keys(changes).length === 0) return
    setDetailBusy(true)
    setDetailError(null)
    try {
      replaceTask(await tasksApi.update(openTaskId, changes))
    } catch (err) {
      setDetailError(errorMessage(err))
    } finally {
      setDetailBusy(false)
    }
  }

  async function handleDelete() {
    setDetailBusy(true)
    setDetailError(null)
    try {
      await tasksApi.remove(openTaskId)
      setTaskList((current) => current.filter((t) => t.id !== openTaskId))
      setOpenTaskId(null)
    } catch (err) {
      setDetailError(errorMessage(err))
    } finally {
      setDetailBusy(false)
    }
  }

  function handleAddComment(body) {
    setCommentsByTask((current) => {
      const existing = current[openTaskId] ?? []
      const comment = {
        id: `local-${Date.now()}`,
        body,
        author: displayName(user?.email),
        created_at: new Date().toISOString(),
      }
      return { ...current, [openTaskId]: [...existing, comment] }
    })
  }

  if (loading) return <p className="muted centered">Loading workspace…</p>

  if (error && !workspace) {
    return (
      <section className="page">
        <p className="alert" role="alert">{error}</p>
        <Link to="/workspaces" className="btn">← Back to workspaces</Link>
      </section>
    )
  }

  return (
    <section className="page board-page">
      <div className="page-head">
        <div>
          <Link to="/workspaces" className="back-link">← My Workspaces</Link>
          <h1>{workspace.name}</h1>
          <p className="muted">
            {workspace.members.length} member{workspace.members.length === 1 ? '' : 's'} ·
            you are {workspace.my_role}
          </p>
        </div>
        <button type="button" className="btn btn-quiet" onClick={load}>Refresh</button>
      </div>

      {error && <p className="alert" role="alert">{error}</p>}

      <div className="board">
        {STATUSES.map((status) => (
          <div
            key={status}
            className="column"
            onDragOver={(e) => e.preventDefault()}
            onDrop={(e) => {
              e.preventDefault()
              const taskId = Number(e.dataTransfer.getData('text/plain'))
              const task = taskList.find((t) => t.id === taskId)
              if (task) handleMove(task, status)
              setDraggingId(null)
            }}
          >
            <header className="column-head">
              <h2>{statusLabel(status)}</h2>
              <span className="count">{byStatus[status].length}</span>
            </header>

            <div className="column-body">
              {byStatus[status].map((task) => (
                <TaskCard
                  key={task.id}
                  task={task}
                  authorName={authorFor(task)}
                  dragging={draggingId === task.id}
                  onOpen={(t) => {
                    setOpenTaskId(t.id)
                    setDetailError(null)
                  }}
                  onDragStart={(e, t) => {
                    e.dataTransfer.setData('text/plain', String(t.id))
                    e.dataTransfer.effectAllowed = 'move'
                    setDraggingId(t.id)
                  }}
                  onDragEnd={() => setDraggingId(null)}
                />
              ))}

              {composing === status ? (
                <form className="card compose" onSubmit={(e) => handleCreate(e, status)}>
                  <input
                    value={newTitle}
                    placeholder="Task title"
                    autoFocus
                    maxLength={255}
                    onChange={(e) => setNewTitle(e.target.value)}
                    onKeyDown={(e) => {
                      if (e.key === 'Escape') {
                        setComposing(null)
                        setNewTitle('')
                      }
                    }}
                  />
                  <div className="compose-actions">
                    <button type="submit" className="btn btn-primary" disabled={!newTitle.trim()}>
                      Add
                    </button>
                    <button
                      type="button"
                      className="btn btn-quiet"
                      onClick={() => {
                        setComposing(null)
                        setNewTitle('')
                      }}
                    >
                      Cancel
                    </button>
                  </div>
                </form>
              ) : (
                <button
                  type="button"
                  className="add-task"
                  onClick={() => {
                    setComposing(status)
                    setNewTitle('')
                  }}
                >
                  + Add Task
                </button>
              )}
            </div>
          </div>
        ))}
      </div>

      {openTask && (
        <TaskDetail
          task={openTask}
          authorName={authorFor(openTask)}
          comments={commentsByTask[openTask.id] ?? []}
          onAddComment={handleAddComment}
          onSave={handleSave}
          onDelete={handleDelete}
          onClose={() => setOpenTaskId(null)}
          busy={detailBusy}
          error={detailError}
        />
      )}
    </section>
  )
}
