from typing import Annotated

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Response, status
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from app.auth.dependencies import CurrentUser
from app.database import get_db
from app.realtime.events import EventType, queue_broadcast, task_event
from app.tasks import service
from app.tasks.dependencies import CurrentTask
from app.tasks.schemas import TaskConflictResponse, TaskCreate, TaskResponse, TaskUpdate
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
    background: BackgroundTasks,
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
    response = TaskResponse.model_validate(task)
    queue_broadcast(background, task.workspace_id, task_event(EventType.TASK_CREATED, response))
    return response


@tasks_router.patch(
    "/{task_id}",
    response_model=TaskResponse,
    responses={status.HTTP_409_CONFLICT: {"model": TaskConflictResponse}},
)
def update_task(
    payload: TaskUpdate, task: CurrentTask, db: DbSession, background: BackgroundTasks
) -> TaskResponse | JSONResponse:
    """Partial update, applied only if the task is still at ``expected_version``.

    Any member of the workspace may edit any task in it. A stale
    ``expected_version`` is a 409 whose body carries the current task, so the
    client can show what changed. Nothing is written and nothing is broadcast.
    """
    changes = payload.model_dump(exclude_unset=True, exclude={"expected_version"})
    try:
        updated = service.update_task(db, task, changes, payload.expected_version)
    except service.VersionConflictError as conflict:
        body = TaskConflictResponse(
            detail="This task was updated by someone else.",
            current_task=TaskResponse.model_validate(conflict.current),
        )
        return JSONResponse(status_code=status.HTTP_409_CONFLICT, content=body.model_dump(mode="json"))
    except service.TaskGoneError:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Task not found.") from None

    response = TaskResponse.model_validate(updated)
    # An empty body changes nothing and commits nothing, so there is no news.
    if changes:
        queue_broadcast(background, task.workspace_id, task_event(EventType.TASK_UPDATED, response))
    return response


@tasks_router.delete("/{task_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_task(task: CurrentTask, db: DbSession, background: BackgroundTasks) -> Response:
    # Snapshot before the row goes; the event carries the task as it last was.
    event = task_event(EventType.TASK_DELETED, task)
    workspace_id = task.workspace_id
    service.delete_task(db, task)
    queue_broadcast(background, workspace_id, event)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
