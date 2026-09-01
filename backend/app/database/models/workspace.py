from typing import TYPE_CHECKING

from sqlalchemy import String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.database import Base
from app.database.models.mixins import TimestampMixin

if TYPE_CHECKING:
    from app.database.models.task import Task
    from app.database.models.user import User
    from app.database.models.workspace_member import WorkspaceMember


class Workspace(TimestampMixin, Base):
    __tablename__ = "workspaces"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False)

    members: Mapped[list["WorkspaceMember"]] = relationship(
        back_populates="workspace",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
    tasks: Mapped[list["Task"]] = relationship(
        back_populates="workspace",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )

    users: Mapped[list["User"]] = relationship(
        secondary="workspace_members",
        back_populates="workspaces",
        viewonly=True,
    )

    def __repr__(self) -> str:
        return f"<Workspace id={self.id} name={self.name!r}>"
