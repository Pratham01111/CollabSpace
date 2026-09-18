"""Task logic, independent of HTTP concerns."""

from sqlalchemy import func, select
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


def update_task(db: Session, task: Task, changes: dict) -> Task:
    """Apply a partial update. ``changes`` holds only the keys the client sent."""
    if not changes:
        return task

    # Moving to another column without saying where lands the card at the
    # bottom of it, rather than keeping a position that means nothing there.
    if "status" in changes and changes["status"] != task.status and "position" not in changes:
        changes["position"] = next_position(db, task.workspace_id, changes["status"])

    for field, value in changes.items():
        setattr(task, field, value)

    # Not concurrency control — that arrives in Phase 10. Bumping here just
    # keeps the counter meaningful, so Phase 10 only has to add the comparison.
    task.version += 1

    db.commit()
    db.refresh(task)
    return task


def delete_task(db: Session, task: Task) -> None:
    # Comments cascade away with the task (ON DELETE CASCADE in the schema).
    db.delete(task)
    db.commit()
