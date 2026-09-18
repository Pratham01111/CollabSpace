from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Path, Response, status
from sqlalchemy.orm import Session

from app.auth.dependencies import CurrentUser
from app.database import get_db
from app.database.models import WorkspaceMember
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


@router.post("", response_model=WorkspaceResponse, status_code=status.HTTP_201_CREATED)
def create_workspace(
    payload: WorkspaceCreate,
    current_user: CurrentUser,
    db: DbSession,
) -> WorkspaceResponse:
    workspace, membership = service.create_workspace(db, payload.name, current_user)
    return WorkspaceResponse(
        id=workspace.id,
        name=workspace.name,
        created_at=workspace.created_at,
        my_role=membership.role,
    )


@router.get("", response_model=list[WorkspaceResponse])
def list_workspaces(current_user: CurrentUser, db: DbSession) -> list[WorkspaceResponse]:
    """Only workspaces the caller belongs to — there is no listing of all workspaces."""
    return [_workspace_response(m) for m in service.list_memberships_for_user(db, current_user)]


@router.get("/{workspace_id}", response_model=WorkspaceDetailResponse)
def get_workspace(membership: CurrentMembership, db: DbSession) -> WorkspaceDetailResponse:
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
)
def add_member(
    payload: MemberAdd,
    actor: MembershipManager,
    db: DbSession,
) -> MemberResponse:
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
    return _member_response(membership)


# Registered before the /{user_id} route below on purpose. Route matching is
# ordered, and "/members/{user_id}" would match the literal path "/members/me"
# first and then fail int conversion with a 422 — it does not fall through.
@router.delete("/{workspace_id}/members/me", status_code=status.HTTP_204_NO_CONTENT)
def leave_workspace(membership: CurrentMembership, db: DbSession) -> Response:
    """Leave a workspace. Open to any member, whatever their role."""
    try:
        service.leave_workspace(db, membership)
    except service.LastOwnerError:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "You are the last owner. Promote another member to owner before leaving.",
        ) from None

    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.delete("/{workspace_id}/members/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
def remove_member(
    user_id: Annotated[int, Path(ge=1)],
    actor: MembershipManager,
    db: DbSession,
) -> Response:
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

    return Response(status_code=status.HTTP_204_NO_CONTENT)
