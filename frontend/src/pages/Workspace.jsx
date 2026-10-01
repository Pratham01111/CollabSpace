import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import {
  comments as commentsApi,
  conflictTask,
  errorMessage,
  tasks as tasksApi,
  workspaces as workspacesApi,
} from '../api/client.js'
import { STATUSES, statusLabel } from '../constants.js'
import ConnectionStatus from '../components/ConnectionStatus.jsx'
import TaskCard from '../components/TaskCard.jsx'
import TaskDetail from '../components/TaskDetail.jsx'
import useWorkspaceSocket from '../hooks/useWorkspaceSocket.js'

/** The API identifies people by id; the member list is what turns one into a name. */
function displayName(email) {
  return email ? email.split('@')[0] : 'Unknown'
}

// The same task can reach us twice, via the REST response to our own change
// and via the broadcast of it, in either order. Every write to the list goes
// through these, so a task is never added twice and an older version never
// overwrites a newer one.
const CONFLICT_MESSAGE =
  'This task was updated by someone else — showing the latest version. Your change was not saved.'

function addTask(list, task) {
  return list.some((t) => t.id === task.id) ? list : [...list, task]
}

function updateTask(list, task) {
  // An update for a task we do not have (say, one we just deleted) is not a
  // reason to bring it back.
  return list.map((t) => (t.id === task.id && task.version >= t.version ? task : t))
}

function removeTask(list, taskId) {
  return list.filter((t) => t.id !== taskId)
}

// Comments arrive the same two ways (POST response and broadcast) and can also
// race a thread fetch, so threads are merged by id, never appended blindly.
function mergeComments(existing, incoming) {
  const byId = new Map((existing ?? []).map((c) => [c.id, c]))
  for (const comment of incoming) byId.set(comment.id, comment)
  return [...byId.values()].sort(
    (a, b) => Date.parse(a.created_at) - Date.parse(b.created_at) || a.id - b.id,
  )
}

export default function Workspace() {
  const { id } = useParams()

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
  // Threads fetched so far, by task id. A live COMMENT_CREATED is only kept
  // for a thread already here; any other is read fresh when its task opens.
  const [commentsByTask, setCommentsByTask] = useState({})
  const [commentsLoading, setCommentsLoading] = useState(false)
  const [commentsError, setCommentsError] = useState(null)
  // Bumped on reconnect to re-read the open thread, which may have missed events.
  const [commentsReload, setCommentsReload] = useState(0)

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

  const handleEvent = useCallback((event) => {
    switch (event.type) {
      case 'TASK_CREATED':
        setTaskList((current) => addTask(current, event.task))
        break
      case 'TASK_UPDATED':
        setTaskList((current) => updateTask(current, event.task))
        break
      case 'TASK_DELETED':
        setTaskList((current) => removeTask(current, event.task.id))
        break
      case 'COMMENT_CREATED': {
        const { comment } = event
        setCommentsByTask((current) =>
          comment.task_id in current
            ? { ...current, [comment.task_id]: mergeComments(current[comment.task_id], [comment]) }
            : current,
        )
        break
      }
      default:
        // Ignore event types this client does not know yet.
        break
    }
  }, [])

  // Anything broadcast while the socket was down was missed, so each
  // (re)connect re-reads the board. This also covers the gap between the
  // first REST fetch and the socket opening.
  const resync = useCallback(async () => {
    setCommentsReload((n) => n + 1)
    try {
      setTaskList(await tasksApi.list(id))
    } catch (err) {
      setError(errorMessage(err))
    }
  }, [id])

  const { status: liveStatus, retry: retryLive } = useWorkspaceSocket(id, {
    onEvent: handleEvent,
    onConnected: resync,
    onLostAccess: () => setError('You are no longer a member of this workspace.'),
  })

  useEffect(() => {
    if (openTaskId == null) return undefined
    let cancelled = false
    setCommentsLoading(true)
    setCommentsError(null)
    commentsApi
      .list(openTaskId)
      .then((list) => {
        if (cancelled) return
        setCommentsByTask((current) => ({
          ...current,
          [openTaskId]: mergeComments(current[openTaskId], list),
        }))
      })
      .catch((err) => !cancelled && setCommentsError(errorMessage(err)))
      .finally(() => !cancelled && setCommentsLoading(false))
    return () => {
      cancelled = true
    }
  }, [openTaskId, commentsReload])

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
    setTaskList((current) => updateTask(current, updated))
  }

  async function handleCreate(event, status) {
    event.preventDefault()
    const title = newTitle.trim()
    if (!title) return
    try {
      const created = await tasksApi.create(id, { title, status })
      setTaskList((current) => addTask(current, created))
      setNewTitle('')
      setComposing(null)
    } catch (err) {
      setError(errorMessage(err))
    }
  }

  // Cards with a move still in flight. A second move would quote the version
  // the first is about to replace and be refused as a conflict with ourselves.
  const movingIds = useRef(new Set())

  async function handleMove(task, status) {
    if (task.status === status || movingIds.current.has(task.id)) return
    movingIds.current.add(task.id)
    // Show the card in its new column straight away; the server decides the
    // final position and we reconcile when it answers.
    setTaskList((current) => current.map((t) => (t.id === task.id ? { ...t, status } : t)))
    try {
      replaceTask(await tasksApi.update(task.id, { status }, task.version))
    } catch (err) {
      // Undo only our optimistic move. Restoring a whole-list snapshot would
      // also throw away anything that arrived over the socket meanwhile.
      setTaskList((current) =>
        current.map((t) => (t.id === task.id && t.version === task.version ? task : t)),
      )
      const current = conflictTask(err)
      if (current) replaceTask(current)
      setError(current ? CONFLICT_MESSAGE : errorMessage(err))
    } finally {
      movingIds.current.delete(task.id)
    }
  }

  // Resolves to the current task if the save was refused as outdated, so the
  // form can show it; otherwise null.
  async function handleSave(changes, expectedVersion) {
    if (Object.keys(changes).length === 0) return null
    setDetailBusy(true)
    setDetailError(null)
    try {
      replaceTask(await tasksApi.update(openTaskId, changes, expectedVersion))
      return null
    } catch (err) {
      const current = conflictTask(err)
      if (current) replaceTask(current)
      setDetailError(current ? CONFLICT_MESSAGE : errorMessage(err))
      return current
    } finally {
      setDetailBusy(false)
    }
  }

  async function handleDelete() {
    setDetailBusy(true)
    setDetailError(null)
    try {
      await tasksApi.remove(openTaskId)
      setTaskList((current) => removeTask(current, openTaskId))
      setOpenTaskId(null)
    } catch (err) {
      setDetailError(errorMessage(err))
    } finally {
      setDetailBusy(false)
    }
  }

  // Throws on failure so the form can keep the text and show why.
  async function handleAddComment(body) {
    const taskId = openTaskId
    const created = await commentsApi.create(taskId, body)
    setCommentsByTask((current) => ({
      ...current,
      [taskId]: mergeComments(current[taskId], [created]),
    }))
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
        <div className="board-actions">
          <ConnectionStatus status={liveStatus} onRetry={retryLive} />
          <button type="button" className="btn btn-quiet" onClick={load}>Refresh</button>
        </div>
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
          comments={(commentsByTask[openTask.id] ?? []).map((c) => ({
            ...c,
            authorName: displayName(c.author.email),
          }))}
          commentsLoading={commentsLoading}
          commentsError={commentsError}
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
