"""Comment logic, independent of HTTP concerns."""

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.database.models import Comment, Task, User


def list_comments(db: Session, task: Task) -> list[Comment]:
    """The task's thread, oldest first, authors loaded in one extra query.

    ``id`` breaks ties: comments posted in the same transaction share a
    ``created_at``. Matches the (task_id, created_at) index.
    """
    return list(
        db.scalars(
            select(Comment)
            .where(Comment.task_id == task.id)
            .options(selectinload(Comment.user))
            .order_by(Comment.created_at, Comment.id)
        )
    )


def create_comment(db: Session, task: Task, author: User, body: str) -> Comment:
    comment = Comment(task=task, user=author, body=body)
    db.add(comment)
    db.commit()
    db.refresh(comment)
    return comment
