import enum
from typing import TYPE_CHECKING

from sqlalchemy import Enum, Float, ForeignKey, Index, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.database import Base
from app.database.models.mixins import TimestampMixin, UpdatedAtMixin

if TYPE_CHECKING:
    from app.database.models.comment import Comment
    from app.database.models.user import User
    from app.database.models.workspace import Workspace


class TaskStatus(str, enum.Enum):
    TODO = "TODO"
    IN_PROGRESS = "IN_PROGRESS"
    DONE = "DONE"


class Task(TimestampMixin, UpdatedAtMixin, Base):
    __tablename__ = "tasks"
    __table_args__ = (
        # Covers the board query: every task in a workspace, grouped by column,
        # already in display order.
        Index("ix_tasks_workspace_id_status_position", "workspace_id", "status", "position"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    workspace_id: Mapped[int] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[TaskStatus] = mapped_column(
        Enum(TaskStatus, name="task_status", native_enum=True),
        default=TaskStatus.TODO,
        server_default=TaskStatus.TODO.value,
        nullable=False,
    )
    # Float rather than int: dragging a card between two neighbours becomes a
    # single-row write at the midpoint of their positions, instead of
    # renumbering (and re-broadcasting) every card below it.
    position: Mapped[float] = mapped_column(Float, default=0.0, server_default="0", nullable=False)
    # Author is kept for display only, so deleting a user empties the field
    # rather than deleting their tasks.
    created_by: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"),
        index=True,
        nullable=True,
    )
    # Optimistic-concurrency counter. Phase 10 compares a client's expected
    # version against this column and rejects a stale write with 409.
    version: Mapped[int] = mapped_column(default=1, server_default="1", nullable=False)

    workspace: Mapped["Workspace"] = relationship(back_populates="tasks")
    creator: Mapped["User | None"] = relationship(back_populates="created_tasks")
    comments: Mapped[list["Comment"]] = relationship(
        back_populates="task",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="Comment.created_at",
    )

    def __repr__(self) -> str:
        return f"<Task id={self.id} title={self.title!r} status={self.status.value}>"
