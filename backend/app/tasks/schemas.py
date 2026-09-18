from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.database.models import TaskStatus


class TaskCreate(BaseModel):
    # extra="forbid" so a client that tries to set created_by or version gets a
    # 422 instead of having the field silently dropped.
    model_config = ConfigDict(extra="forbid")

    title: str = Field(min_length=1, max_length=255)
    description: str | None = None
    status: TaskStatus = TaskStatus.TODO
    # Omitted means "append to the end of that status column".
    position: float | None = None

    @field_validator("title")
    @classmethod
    def strip_title(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("Title must not be blank.")
        return value


class TaskUpdate(BaseModel):
    """Every field optional — only what is sent gets changed.

    ``description`` is genuinely nullable, so sending ``null`` clears it while
    omitting the key leaves it alone.
    """

    model_config = ConfigDict(extra="forbid")

    title: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = None
    status: TaskStatus | None = None
    position: float | None = None

    @field_validator("title")
    @classmethod
    def strip_title(cls, value: str | None) -> str | None:
        if value is None:
            return None
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
