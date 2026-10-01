from typing import Annotated

from fastapi import APIRouter, BackgroundTasks, Depends, status
from sqlalchemy.orm import Session

from app.auth.dependencies import CurrentUser
from app.comments import service
from app.comments.schemas import CommentAuthor, CommentCreate, CommentResponse
from app.database import get_db
from app.database.models import Comment
from app.realtime.events import EventType, queue_broadcast
from app.tasks.dependencies import CurrentTask

DbSession = Annotated[Session, Depends(get_db)]

# CurrentTask is the same check the task routes use: a task that does not
# exist and a task in someone else's workspace are both a 404.
router = APIRouter(prefix="/tasks", tags=["comments"])


def _comment_response(comment: Comment) -> CommentResponse:
    return CommentResponse(
        id=comment.id,
        task_id=comment.task_id,
        author=CommentAuthor(id=comment.user.id, email=comment.user.email),
        body=comment.body,
        created_at=comment.created_at,
    )


@router.get("/{task_id}/comments", response_model=list[CommentResponse])
def list_comments(task: CurrentTask, db: DbSession) -> list[CommentResponse]:
    """The task's comments, oldest first."""
    return [_comment_response(c) for c in service.list_comments(db, task)]


@router.post(
    "/{task_id}/comments",
    response_model=CommentResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_comment(
    payload: CommentCreate,
    task: CurrentTask,
    current_user: CurrentUser,
    db: DbSession,
    background: BackgroundTasks,
) -> CommentResponse:
    comment = service.create_comment(db, task, current_user, payload.body)
    response = _comment_response(comment)
    # Queued only now that the commit has succeeded; see app.realtime.events.
    queue_broadcast(
        background,
        task.workspace_id,
        {"type": EventType.COMMENT_CREATED, "comment": response.model_dump(mode="json")},
    )
    return response
