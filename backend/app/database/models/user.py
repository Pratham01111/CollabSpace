from typing import TYPE_CHECKING

from sqlalchemy import String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.database import Base
from app.database.models.mixins import TimestampMixin

if TYPE_CHECKING:
    from app.database.models.comment import Comment
    from app.database.models.task import Task
    from app.database.models.workspace import Workspace
    from app.database.models.workspace_member import WorkspaceMember


class User(TimestampMixin, Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    # unique=True creates the unique constraint; index=True creates the lookup
    # index used by login. Stored lower-cased by the application layer.
    email: Mapped[str] = mapped_column(String(320), unique=True, index=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)

    memberships: Mapped[list["WorkspaceMember"]] = relationship(
        back_populates="user",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
    comments: Mapped[list["Comment"]] = relationship(
        back_populates="user",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
    # Tasks are kept when their author is deleted (created_by becomes NULL),
    # so this side is not a cascading relationship.
    created_tasks: Mapped[list["Task"]] = relationship(back_populates="creator")

    # Convenience many-to-many view across the association table. Read-only:
    # membership is created by writing a WorkspaceMember (which carries a role).
    workspaces: Mapped[list["Workspace"]] = relationship(
        secondary="workspace_members",
        back_populates="users",
        viewonly=True,
    )

    def __repr__(self) -> str:
        return f"<User id={self.id} email={self.email!r}>"
