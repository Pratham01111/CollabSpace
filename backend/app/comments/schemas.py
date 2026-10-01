from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator

# Generous for a comment, but bounded so one request cannot store megabytes.
MAX_BODY_LENGTH = 5000


class CommentCreate(BaseModel):
    # extra="forbid": the author comes from the token, so a body that tries to
    # name one is a 422 rather than silently ignored.
    model_config = ConfigDict(extra="forbid")

    body: str = Field(min_length=1, max_length=MAX_BODY_LENGTH)

    @field_validator("body")
    @classmethod
    def strip_body(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("Comment must not be blank.")
        return value


class CommentAuthor(BaseModel):
    id: int
    email: str


class CommentResponse(BaseModel):
    id: int
    task_id: int
    author: CommentAuthor
    body: str
    created_at: datetime
