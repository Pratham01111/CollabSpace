from typing import Annotated

from fastapi import APIRouter, Depends, Response, status
from sqlalchemy.orm import Session

from app.auth.dependencies import CurrentUser
from app.database import get_db
from app.tasks import service
from app.tasks.dependencies import CurrentTask
from app.tasks.schemas import TaskCreate, TaskResponse, TaskUpdate
from app.workspaces.dependencies import CurrentMembership

DbSession = Annotated[Session, Depends(get_db)]

# Board-scoped routes hang off the workspace; a single task is addressed
# directly, as the spec lays them out.
workspace_tasks_router = APIRouter(prefix="/workspaces", tags=["tasks"])
tasks_router = APIRouter(prefix="/tasks", tags=["tasks"])


@workspace_tasks_router.get("/{workspace_id}/tasks", response_model=list[TaskResponse])
def list_tasks(membership: CurrentMembership, db: DbSession) -> list[TaskResponse]:
    """All tasks in the workspace, ordered by status then position."""
    tasks = service.list_tasks(db, membership.workspace_id)
    return [TaskResponse.model_validate(t) for t in tasks]


@workspace_tasks_router.post(
    "/{workspace_id}/tasks",
    response_model=TaskResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_task(
    payload: TaskCreate,
    membership: CurrentMembership,
    current_user: CurrentUser,
    db: DbSession,
) -> TaskResponse:
    task = service.create_task(
        db,
        workspace_id=membership.workspace_id,
        creator=current_user,
        title=payload.title,
        description=payload.description,
        status=payload.status,
        position=payload.position,
    )
    return TaskResponse.model_validate(task)


@tasks_router.patch("/{task_id}", response_model=TaskResponse)
def update_task(payload: TaskUpdate, task: CurrentTask, db: DbSession) -> TaskResponse:
    """Partial update. Any member of the workspace may edit any task in it."""
    changes = payload.model_dump(exclude_unset=True)
    return TaskResponse.model_validate(service.update_task(db, task, changes))


@tasks_router.delete("/{task_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_task(task: CurrentTask, db: DbSession) -> Response:
    service.delete_task(db, task)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
