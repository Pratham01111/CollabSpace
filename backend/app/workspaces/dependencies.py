"""Access control for workspace routes."""

from typing import Annotated

from fastapi import Depends, HTTPException, Path, status
from sqlalchemy.orm import Session

from app.auth.dependencies import CurrentUser
from app.database import get_db
from app.database.models import WorkspaceMember, WorkspaceRole
from app.workspaces import service


def get_membership_or_404(
    workspace_id: Annotated[int, Path(ge=1)],
    current_user: CurrentUser,
    db: Annotated[Session, Depends(get_db)],
) -> WorkspaceMember:
    """The caller's membership, or 404.

    A workspace that does not exist and one the caller is not a member of give
    the same answer on purpose: a 403 on someone else's workspace would confirm
    that it exists, which is exactly what "users cannot access another user's
    private workspace" is meant to prevent.
    """
    membership = service.get_membership(db, workspace_id, current_user.id)
    if membership is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Workspace not found.",
        )
    return membership


CurrentMembership = Annotated[WorkspaceMember, Depends(get_membership_or_404)]

MEMBERSHIP_MANAGER_ROLES = frozenset({WorkspaceRole.OWNER, WorkspaceRole.ADMIN})


def require_membership_manager(membership: CurrentMembership) -> WorkspaceMember:
    """Guards membership changes. The caller is already known to be a member,
    so a 403 here reveals nothing they could not already see."""
    if membership.role not in MEMBERSHIP_MANAGER_ROLES:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only an owner or admin can modify membership.",
        )
    return membership


MembershipManager = Annotated[WorkspaceMember, Depends(require_membership_manager)]
