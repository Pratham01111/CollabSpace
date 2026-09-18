"""Access control for task routes."""

from typing import Annotated

from fastapi import Depends, HTTPException, Path, status
from sqlalchemy.orm import Session

from app.auth.dependencies import CurrentUser
from app.database import get_db
from app.database.models import Task
from app.workspaces import service as workspace_service


def get_task_or_404(
    task_id: Annotated[int, Path(ge=1)],
    current_user: CurrentUser,
    db: Annotated[Session, Depends(get_db)],
) -> Task:
    """The task, if the caller belongs to the workspace holding it.

    A task that does not exist and a task in someone else's workspace give the
    same 404, for the same reason the workspace routes do: a 403 would confirm
    that the task exists.
    """
    not_found = HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Task not found.")

    task = db.get(Task, task_id)
    if task is None:
        raise not_found

    if workspace_service.get_membership(db, task.workspace_id, current_user.id) is None:
        raise not_found

    return task


CurrentTask = Annotated[Task, Depends(get_task_or_404)]
