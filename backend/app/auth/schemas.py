from datetime import datetime

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator

from app.auth.security import MAX_PASSWORD_BYTES


class RegisterRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8)

    @field_validator("password")
    @classmethod
    def password_fits_bcrypt(cls, value: str) -> str:
        if len(value.encode()) > MAX_PASSWORD_BYTES:
            raise ValueError(
                f"Password must be at most {MAX_PASSWORD_BYTES} bytes "
                "(non-ASCII characters count as more than one)."
            )
        return value


class LoginRequest(BaseModel):
    email: EmailStr
    # No constraints here: an existing password must be checkable even if the
    # rules tighten later, and length feedback on login leaks information.
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int  # seconds


class UserResponse(BaseModel):
    """Public view of a user. Note the absence of password_hash."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    email: EmailStr
    created_at: datetime
