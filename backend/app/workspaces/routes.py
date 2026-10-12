import logging
from typing import Annotated

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Path, Response, status
from sqlalchemy.orm import Session

from app.auth.dependencies import CurrentUser
from app.database import get_db
from app.errors import error_docs
from app.database.models import WorkspaceMember
from app.realtime.bus import bus
from app.realtime.events import EventType, queue_broadcast
from app.validation import MAX_ID
from app.realtime.manager import CLOSE_WORKSPACE_NOT_FOUND
from app.workspaces import service
from app.workspaces.dependencies import CurrentMembership, MembershipManager
from app.workspaces.schemas import (
    MemberAdd,
    MemberResponse,
    WorkspaceCreate,
    WorkspaceDetailResponse,
    WorkspaceResponse,
)

router = APIRouter(prefix="/workspaces", tags=["workspaces"])

logger = logging.getLogger("app.workspaces")

DbSession = Annotated[Session, Depends(get_db)]


def _member_response(membership: WorkspaceMember) -> MemberResponse:
    return MemberResponse(
        user_id=membership.user_id,
        email=membership.user.email,
        role=membership.role,
        created_at=membership.created_at,
    )


def _workspace_response(membership: WorkspaceMember) -> WorkspaceResponse:
    return WorkspaceResponse(
        id=membership.workspace.id,
        name=membership.workspace.name,
        created_at=membership.workspace.created_at,
        my_role=membership.role,
    )


def _after_member_removed(background: BackgroundTasks, workspace_id: int, user_id: int) -> None:
    """Tell the workspace someone has gone, then close that person's live
    sockets, or they would keep receiving its events. Both are queued, so they
    happen only once the removal has committed, and both go via the bus, as
    sockets may be on another instance."""
    logger.info(
        "member left or removed",
        extra={"event": "workspace.member_removed", "workspace_id": workspace_id, "user_id": user_id},
    )
    queue_broadcast(background, workspace_id, {"type": EventType.MEMBER_REMOVED, "user_id": user_id})
    background.add_task(
        bus.disconnect_user, workspace_id, user_id, CLOSE_WORKSPACE_NOT_FOUND, "Workspace not found."
    )


@router.post(
    "",
    response_model=WorkspaceResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a workspace",
    responses=error_docs(401, 422),
)
def create_workspace(
    payload: WorkspaceCreate,
    current_user: CurrentUser,
    db: DbSession,
) -> WorkspaceResponse:
    """Create a workspace. The caller becomes its OWNER."""
    workspace, membership = service.create_workspace(db, payload.name, current_user)
    return WorkspaceResponse(
        id=workspace.id,
        name=workspace.name,
        created_at=workspace.created_at,
        my_role=membership.role,
    )


@router.get(
    "",
    response_model=list[WorkspaceResponse],
    summary="List my workspaces",
    responses=error_docs(401),
)
def list_workspaces(current_user: CurrentUser, db: DbSession) -> list[WorkspaceResponse]:
    """Only workspaces the caller belongs to — there is no listing of all workspaces."""
    return [_workspace_response(m) for m in service.list_memberships_for_user(db, current_user)]


@router.get(
    "/{workspace_id}",
    response_model=WorkspaceDetailResponse,
    summary="Get a workspace",
    responses=error_docs(401, 404, 422),
)
def get_workspace(membership: CurrentMembership, db: DbSession) -> WorkspaceDetailResponse:
    """The workspace, your role in it, and its members. Members only."""
    members = service.list_members(db, membership.workspace_id)
    return WorkspaceDetailResponse(
        id=membership.workspace.id,
        name=membership.workspace.name,
        created_at=membership.workspace.created_at,
        my_role=membership.role,
        members=[_member_response(m) for m in members],
    )


@router.post(
    "/{workspace_id}/members",
    response_model=MemberResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Add a member",
    responses=error_docs(
        401, 403, 404, 409, 422,
        s403="Members cannot add people, and only an owner can grant ADMIN or OWNER.",
        s409="Already a member.",
    ),
)
def add_member(
    payload: MemberAdd,
    actor: MembershipManager,
    db: DbSession,
    background: BackgroundTasks,
) -> MemberResponse:
    """Add a user by `email` or `user_id` (exactly one), as MEMBER unless `role` says
    otherwise. Owners and admins only; granting ADMIN or OWNER takes an owner.
    """
    try:
        membership = service.add_member(
            db,
            workspace_id=actor.workspace_id,
            actor=actor,
            role=payload.role,
            user_id=payload.user_id,
            email=payload.email,
        )
    except service.UserNotFoundError:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No such user.") from None
    except service.AlreadyMemberError:
        raise HTTPException(
            status.HTTP_409_CONFLICT, "That user is already a member of this workspace."
        ) from None
    except service.RoleNotPermittedError as exc:
        raise HTTPException(status.HTTP_403_FORBIDDEN, str(exc)) from None

    db.refresh(membership, ["user"])
    response = _member_response(membership)
    logger.info(
        "member added",
        extra={
            "event": "workspace.member_added",
            "workspace_id": actor.workspace_id,
            "user_id": response.user_id,
        },
    )
    queue_broadcast(
        background,
        actor.workspace_id,
        {"type": EventType.MEMBER_ADDED, "member": response.model_dump(mode="json")},
    )
    return response


# Registered before the /{user_id} route below on purpose. Route matching is
# ordered, and "/members/{user_id}" would match the literal path "/members/me"
# first and then fail int conversion with a 422 — it does not fall through.
@router.delete(
    "/{workspace_id}/members/me",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Leave a workspace",
    responses=error_docs(401, 404, 409, 422, s409="You are the last owner; promote someone else first."),
)
def leave_workspace(
    membership: CurrentMembership, db: DbSession, background: BackgroundTasks
) -> Response:
    """Leave a workspace. Open to any member, whatever their role."""
    try:
        service.leave_workspace(db, membership)
    except service.LastOwnerError:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "You are the last owner. Promote another member to owner before leaving.",
        ) from None

    _after_member_removed(background, membership.workspace_id, membership.user_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.delete(
    "/{workspace_id}/members/{user_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Remove a member",
    responses=error_docs(
        401, 403, 404, 409, 422,
        s403="Members cannot remove people, and only an owner can remove an owner.",
        s409="That would remove the last owner.",
    ),
)
def remove_member(
    user_id: Annotated[int, Path(ge=1, le=MAX_ID)],
    actor: MembershipManager,
    db: DbSession,
    background: BackgroundTasks,
) -> Response:
    """Remove someone from the workspace. Owners and admins only; removing an owner takes
    an owner, and the last owner cannot be removed. Their open WebSockets are closed
    with 4404.
    """
    try:
        service.remove_member(db, workspace_id=actor.workspace_id, actor=actor, user_id=user_id)
    except service.NotAMemberError:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND, "That user is not a member of this workspace."
        ) from None
    except service.RoleNotPermittedError as exc:
        raise HTTPException(status.HTTP_403_FORBIDDEN, str(exc)) from None
    except service.LastOwnerError:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "Cannot remove the last owner. Promote another member to owner first.",
        ) from None

    _after_member_removed(background, actor.workspace_id, user_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
