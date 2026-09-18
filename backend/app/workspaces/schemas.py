from datetime import datetime

from pydantic import BaseModel, ConfigDict, EmailStr, Field, model_validator

from app.database.models import WorkspaceRole


class WorkspaceCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)

    @model_validator(mode="after")
    def strip_name(self) -> "WorkspaceCreate":
        # A name of only spaces passes min_length but is not a name.
        object.__setattr__(self, "name", self.name.strip())
        if not self.name:
            raise ValueError("Name must not be blank.")
        return self


class MemberResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    user_id: int
    email: EmailStr
    role: WorkspaceRole
    created_at: datetime


class WorkspaceResponse(BaseModel):
    """A workspace as it appears in a list, with the caller's own role."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    created_at: datetime
    my_role: WorkspaceRole


class WorkspaceDetailResponse(WorkspaceResponse):
    members: list[MemberResponse]


class MemberAdd(BaseModel):
    """Identify the new member by id or email — exactly one."""

    user_id: int | None = None
    email: EmailStr | None = None
    role: WorkspaceRole = WorkspaceRole.MEMBER

    @model_validator(mode="after")
    def exactly_one_identifier(self) -> "MemberAdd":
        if (self.user_id is None) == (self.email is None):
            raise ValueError("Provide exactly one of 'user_id' or 'email'.")
        return self
