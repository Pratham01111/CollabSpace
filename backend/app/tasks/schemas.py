from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.database.models import TaskStatus
from app.validation import MAX_DESCRIPTION_LENGTH, MAX_ID, MAX_TITLE_LENGTH


class TaskCreate(BaseModel):
    # extra="forbid" so a client that tries to set created_by or version gets a
    # 422 instead of having the field silently dropped.
    model_config = ConfigDict(extra="forbid")

    title: str = Field(min_length=1, max_length=MAX_TITLE_LENGTH)
    description: str | None = Field(default=None, max_length=MAX_DESCRIPTION_LENGTH)
    status: TaskStatus = TaskStatus.TODO
    # Omitted means "append to the end of that status column".
    position: float | None = Field(default=None, allow_inf_nan=False)

    @field_validator("title")
    @classmethod
    def strip_title(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("Title must not be blank.")
        return value


class TaskUpdate(BaseModel):
    """Every field optional — only what is sent gets changed — except
    ``expected_version``, which every update must carry.

    ``description`` is genuinely nullable, so sending ``null`` clears it while
    omitting the key leaves it alone. The other fields are optional but not
    nullable: an explicit ``null`` for them is a 422, not a database error.
    """

    model_config = ConfigDict(extra="forbid")

    # The version the client last saw. The update applies only if the task is
    # still at that version; otherwise it is a 409 carrying the current task.
    expected_version: int = Field(ge=1, le=MAX_ID)
    title: str | None = Field(default=None, min_length=1, max_length=MAX_TITLE_LENGTH)
    description: str | None = Field(default=None, max_length=MAX_DESCRIPTION_LENGTH)
    status: TaskStatus | None = None
    position: float | None = Field(default=None, allow_inf_nan=False)

    # Only runs for keys the client actually sent; an omitted field keeps its
    # default without passing through here.
    @field_validator("title", "status", "position")
    @classmethod
    def not_null(cls, value):
        if value is None:
            raise ValueError("May be omitted, but not null.")
        return value

    @field_validator("title")
    @classmethod
    def strip_title(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("Title must not be blank.")
        return value


class TaskResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    workspace_id: int
    title: str
    description: str | None
    status: TaskStatus
    position: float
    created_by: int | None
    version: int
    created_at: datetime
    updated_at: datetime


class TaskConflictResponse(BaseModel):
    """409 body: the edit was based on an old version, so here is the task as
    it stands now. Nothing was changed. The usual error fields, plus
    ``current_task``."""

    detail: str
    code: str = "version_conflict"
    request_id: str | None = None
    current_task: TaskResponse
