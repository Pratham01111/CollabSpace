"""Events pushed to workspace sockets, and the one way routes should send them.

Routes queue events as background tasks *after* the service call that commits
has returned. FastAPI runs background tasks only once the handler has finished
without raising, so a rejected request or a failed commit never reaches anyone:
clients only ever hear about state that is actually in the database.
"""

from enum import StrEnum

from fastapi import BackgroundTasks

from app.database.models import Task
from app.realtime.manager import manager
from app.tasks.schemas import TaskResponse


class EventType(StrEnum):
    TASK_CREATED = "TASK_CREATED"
    TASK_UPDATED = "TASK_UPDATED"
    TASK_DELETED = "TASK_DELETED"


def task_event(event_type: EventType, task: Task | TaskResponse) -> dict:
    """``{"type": ..., "task": {...}}`` with the task as the REST API returns it,
    so a client can treat an event payload and a response body the same way."""
    if isinstance(task, Task):
        task = TaskResponse.model_validate(task)
    return {"type": event_type, "task": task.model_dump(mode="json")}


def queue_broadcast(background: BackgroundTasks, workspace_id: int, event: dict) -> None:
    """Broadcast ``event`` once the response has gone out. Call only after the
    commit it describes has succeeded."""
    background.add_task(manager.broadcast_to_workspace, workspace_id, event)
