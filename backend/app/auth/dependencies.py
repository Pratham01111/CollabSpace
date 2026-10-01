"""The dependency that turns an Authorization header into a User."""

from typing import Annotated

import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.auth.security import decode_access_token
from app.auth.service import get_user_by_id
from app.database import get_db
from app.database.models import User

# auto_error=False so a missing header lands here rather than becoming
# FastAPI's default 403; an absent credential is a 401.
bearer_scheme = HTTPBearer(auto_error=False, description="Paste the access_token from /auth/login")


def _unauthorized(detail: str) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail=detail,
        headers={"WWW-Authenticate": "Bearer"},
    )


class InvalidTokenError(Exception):
    """The token does not identify a current user. ``str(exc)`` says why."""


def user_from_token(db: Session, token: str) -> User:
    """The user a bearer token belongs to, or ``InvalidTokenError``.

    Shared by the REST dependency below and the WebSocket handshake, so both
    accept exactly the same tokens.
    """
    try:
        payload = decode_access_token(token)
    except jwt.ExpiredSignatureError:
        raise InvalidTokenError("Token has expired") from None
    except jwt.PyJWTError:
        raise InvalidTokenError("Could not validate credentials") from None

    try:
        user_id = int(payload["sub"])
    except (KeyError, TypeError, ValueError):
        raise InvalidTokenError("Could not validate credentials") from None

    user = get_user_by_id(db, user_id)
    if user is None:
        # Signature was valid but the account is gone — the token outlived it.
        raise InvalidTokenError("User no longer exists")

    return user


def get_current_user(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer_scheme)],
    db: Annotated[Session, Depends(get_db)],
) -> User:
    if credentials is None:
        raise _unauthorized("Not authenticated")

    try:
        return user_from_token(db, credentials.credentials)
    except InvalidTokenError as exc:
        raise _unauthorized(str(exc)) from None


CurrentUser = Annotated[User, Depends(get_current_user)]
