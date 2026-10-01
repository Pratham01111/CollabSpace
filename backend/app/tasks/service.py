"""Task logic, independent of HTTP concerns."""

from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from app.database.models import Task, TaskStatus, User


def next_position(db: Session, workspace_id: int, status: TaskStatus) -> float:
    """One past the last card in that column, so new tasks land at the bottom."""
    highest = db.scalar(
        select(func.max(Task.position)).where(
            Task.workspace_id == workspace_id,
            Task.status == status,
        )
    )
    return 1.0 if highest is None else highest + 1.0


def list_tasks(db: Session, workspace_id: int) -> list[Task]:
    """Every task in the workspace, in board order.

    Postgres orders an enum by its declared order, so TODO / IN_PROGRESS / DONE
    come back as the columns are drawn. Matches the
    (workspace_id, status, position) index.
    """
    return list(
        db.scalars(
            select(Task)
            .where(Task.workspace_id == workspace_id)
            .order_by(Task.status, Task.position, Task.id)
        )
    )


def create_task(
    db: Session,
    workspace_id: int,
    creator: User,
    title: str,
    description: str | None,
    status: TaskStatus,
    position: float | None,
) -> Task:
    task = Task(
        workspace_id=workspace_id,
        title=title,
        description=description,
        status=status,
        position=position if position is not None else next_position(db, workspace_id, status),
        # Taken from the authenticated user; the request body cannot set it.
        created_by=creator.id,
    )
    db.add(task)
    db.commit()
    db.refresh(task)
    return task


class VersionConflictError(Exception):
    """The client edited an old version. ``current`` is the task as it is now."""

    def __init__(self, current: Task) -> None:
        super().__init__(f"task {current.id} is at version {current.version}")
        self.current = current


class TaskGoneError(Exception):
    """The task was deleted while this update was in flight."""


def update_task(db: Session, task: Task, changes: dict, expected_version: int) -> Task:
    """Apply a partial update, but only on top of ``expected_version``.

    ``changes`` holds only the keys the client sent. Raises
    ``VersionConflictError`` if the task has moved on, and changes nothing.
    """
    if task.version != expected_version:
        raise VersionConflictError(task)

    if not changes:
        return task

    # Moving to another column without saying where lands the card at the
    # bottom of it, rather than keeping a position that means nothing there.
    if "status" in changes and changes["status"] != task.status and "position" not in changes:
        changes["position"] = next_position(db, task.workspace_id, changes["status"])

    # The check above is only a fast path: another request can commit between
    # it and here. The version test has to be part of the write itself. Under
    # Postgres's default READ COMMITTED, a concurrent UPDATE of the same row
    # waits for the first to commit and then re-evaluates this WHERE against the
    # new row, so exactly one of two racing writers matches and the other
    # updates nothing.
    result = db.execute(
        update(Task)
        .where(Task.id == task.id, Task.version == expected_version)
        .values(**changes, version=Task.version + 1, updated_at=func.now())
        .execution_options(synchronize_session=False)
    )
    if result.rowcount == 0:
        db.rollback()
        raise VersionConflictError(_reload(db, task.id))

    db.commit()
    return _reload(db, task.id)


def _reload(db: Session, task_id: int) -> Task:
    """The task as committed now, bypassing anything stale in the session."""
    current = db.scalar(
        select(Task).where(Task.id == task_id).execution_options(populate_existing=True)
    )
    if current is None:
        raise TaskGoneError
    return current


def delete_task(db: Session, task: Task) -> None:
    # Comments cascade away with the task (ON DELETE CASCADE in the schema).
    db.delete(task)
    db.commit()
