"""Model package.

Importing this module registers every model on ``Base.metadata``, which is what
Alembic autogenerate reads. Import it (not the individual modules) anywhere the
full schema is needed.
"""

from app.database.models.comment import Comment
from app.database.models.task import Task, TaskStatus
from app.database.models.user import User
from app.database.models.workspace import Workspace
from app.database.models.workspace_member import WorkspaceMember, WorkspaceRole

__all__ = [
    "Comment",
    "Task",
    "TaskStatus",
    "User",
    "Workspace",
    "WorkspaceMember",
    "WorkspaceRole",
]
