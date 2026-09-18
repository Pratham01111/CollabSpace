"""Workspace and membership logic, independent of HTTP concerns."""

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, selectinload

from app.auth.service import normalize_email
from app.database.models import User, Workspace, WorkspaceMember, WorkspaceRole


class WorkspaceError(Exception):
    """Base class for membership rule violations."""


class UserNotFoundError(WorkspaceError):
    pass


class AlreadyMemberError(WorkspaceError):
    pass


class NotAMemberError(WorkspaceError):
    pass


class RoleNotPermittedError(WorkspaceError):
    """The actor's role is too low for the change they asked for."""


class LastOwnerError(WorkspaceError):
    """Removing this member would leave the workspace with no owner."""


def create_workspace(db: Session, name: str, creator: User) -> tuple[Workspace, WorkspaceMember]:
    """Create a workspace and enrol its creator as OWNER, in one transaction."""
    workspace = Workspace(name=name)
    membership = WorkspaceMember(workspace=workspace, user=creator, role=WorkspaceRole.OWNER)
    db.add_all([workspace, membership])
    db.commit()
    db.refresh(workspace)
    db.refresh(membership)
    return workspace, membership


def list_memberships_for_user(db: Session, user: User) -> list[WorkspaceMember]:
    """Every membership the user holds, with its workspace already loaded."""
    return list(
        db.scalars(
            select(WorkspaceMember)
            .where(WorkspaceMember.user_id == user.id)
            .options(selectinload(WorkspaceMember.workspace))
            .order_by(WorkspaceMember.created_at)
        )
    )


def get_membership(db: Session, workspace_id: int, user_id: int) -> WorkspaceMember | None:
    return db.scalar(
        select(WorkspaceMember).where(
            WorkspaceMember.workspace_id == workspace_id,
            WorkspaceMember.user_id == user_id,
        )
    )


def list_members(db: Session, workspace_id: int) -> list[WorkspaceMember]:
    return list(
        db.scalars(
            select(WorkspaceMember)
            .where(WorkspaceMember.workspace_id == workspace_id)
            .options(selectinload(WorkspaceMember.user))
            .order_by(WorkspaceMember.created_at)
        )
    )


def _count_owners(db: Session, workspace_id: int) -> int:
    return db.scalar(
        select(func.count())
        .select_from(WorkspaceMember)
        .where(
            WorkspaceMember.workspace_id == workspace_id,
            WorkspaceMember.role == WorkspaceRole.OWNER,
        )
    )


def add_member(
    db: Session,
    workspace_id: int,
    actor: WorkspaceMember,
    role: WorkspaceRole,
    user_id: int | None = None,
    email: str | None = None,
) -> WorkspaceMember:
    # An admin can bring in ordinary members, but only an owner can create
    # someone who outranks them or matches them.
    if role is not WorkspaceRole.MEMBER and actor.role is not WorkspaceRole.OWNER:
        raise RoleNotPermittedError(f"Only an owner can grant the {role.value} role.")

    if user_id is not None:
        user = db.get(User, user_id)
    else:
        user = db.scalar(select(User).where(User.email == normalize_email(email)))

    if user is None:
        raise UserNotFoundError

    if get_membership(db, workspace_id, user.id) is not None:
        raise AlreadyMemberError

    membership = WorkspaceMember(workspace_id=workspace_id, user_id=user.id, role=role)
    db.add(membership)
    try:
        db.commit()
    except IntegrityError as exc:
        # Loses to a concurrent add of the same user; the unique constraint on
        # (workspace_id, user_id) is what actually settles it.
        db.rollback()
        raise AlreadyMemberError from exc

    db.refresh(membership)
    return membership


def remove_member(
    db: Session,
    workspace_id: int,
    actor: WorkspaceMember,
    user_id: int,
) -> None:
    target = get_membership(db, workspace_id, user_id)
    if target is None:
        raise NotAMemberError

    if target.role is WorkspaceRole.OWNER:
        if actor.role is not WorkspaceRole.OWNER:
            raise RoleNotPermittedError("Only an owner can remove another owner.")
        if _count_owners(db, workspace_id) <= 1:
            # Otherwise the workspace is left with nobody able to administer it.
            raise LastOwnerError

    db.delete(target)
    db.commit()
