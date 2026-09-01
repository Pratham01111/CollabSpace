import enum
from typing import TYPE_CHECKING

from sqlalchemy import Enum, ForeignKey, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.database import Base
from app.database.models.mixins import TimestampMixin

if TYPE_CHECKING:
    from app.database.models.user import User
    from app.database.models.workspace import Workspace


class WorkspaceRole(str, enum.Enum):
    OWNER = "OWNER"
    ADMIN = "ADMIN"
    MEMBER = "MEMBER"


class WorkspaceMember(TimestampMixin, Base):
    """Association object joining users to workspaces, carrying a role."""

    __tablename__ = "workspace_members"
    __table_args__ = (
        # A user appears at most once per workspace.
        UniqueConstraint("workspace_id", "user_id", name="uq_workspace_members_workspace_id_user_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    workspace_id: Mapped[int] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    # Indexed on its own to answer "which workspaces does this user belong to?"
    # The unique constraint above already covers workspace-first lookups.
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    role: Mapped[WorkspaceRole] = mapped_column(
        Enum(WorkspaceRole, name="workspace_role", native_enum=True),
        default=WorkspaceRole.MEMBER,
        server_default=WorkspaceRole.MEMBER.value,
        nullable=False,
    )

    workspace: Mapped["Workspace"] = relationship(back_populates="members")
    user: Mapped["User"] = relationship(back_populates="memberships")

    def __repr__(self) -> str:
        return (
            f"<WorkspaceMember workspace_id={self.workspace_id} "
            f"user_id={self.user_id} role={self.role.value}>"
        )
