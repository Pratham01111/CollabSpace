export default function TaskCard({ task, authorName, onOpen, onDragStart, onDragEnd, dragging }) {
  return (
    <article
      className={`card task-card ${dragging ? 'is-dragging' : ''}`}
      draggable
      onDragStart={(e) => onDragStart(e, task)}
      onDragEnd={onDragEnd}
      onClick={() => onOpen(task)}
      onKeyDown={(e) => {
        if (e.key === 'Enter' || e.key === ' ') {
          e.preventDefault()
          onOpen(task)
        }
      }}
      role="button"
      tabIndex={0}
      aria-label={`Open task ${task.title}`}
    >
      <p className="task-title">{task.title}</p>
      {task.description && <p className="task-desc">{task.description}</p>}
      <p className="task-meta">Created by {authorName}</p>
    </article>
  )
}
