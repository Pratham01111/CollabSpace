import logging
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.auth import service
from app.auth.dependencies import CurrentUser
from app.auth.schemas import LoginRequest, RegisterRequest, TokenResponse, UserResponse
from app.auth.security import create_access_token
from app.config import settings
from app.database import get_db
from app.errors import error_docs

router = APIRouter(prefix="/auth", tags=["auth"])

logger = logging.getLogger("app.auth")

DbSession = Annotated[Session, Depends(get_db)]


@router.post(
    "/register",
    response_model=UserResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Register",
    responses=error_docs(409, 422, s409="An account with this email already exists."),
)
def register(payload: RegisterRequest, db: DbSession) -> UserResponse:
    """Create an account. The email is normalised (trimmed, lower-cased); the password must
    be 8 to 72 bytes. The password is never returned or logged.
    """
    try:
        user = service.register_user(db, payload.email, payload.password)
    except service.EmailAlreadyRegisteredError:
        logger.info("registration refused: email taken", extra={"event": "auth.register_conflict"})
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="An account with this email already exists.",
        ) from None

    logger.info("user registered", extra={"event": "auth.registered", "user_id": user.id})
    return UserResponse.model_validate(user)


@router.post(
    "/login",
    response_model=TokenResponse,
    summary="Log in",
    responses=error_docs(401, 422, s401="Incorrect email or password (the same answer for both)."),
)
def login(payload: LoginRequest, db: DbSession) -> TokenResponse:
    """Exchange email and password for a bearer token. A wrong password and an unknown
    email get the identical 401, so the endpoint cannot be used to find out who has an
    account.
    """
    user = service.authenticate_user(db, payload.email, payload.password)
    if user is None:
        # The address is logged for spotting brute-force attempts; never the password.
        logger.warning("login failed", extra={"event": "auth.login_failed", "email": payload.email})
        # One message for both "no such account" and "wrong password", so the
        # endpoint can't be used to discover which addresses are registered.
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    logger.info("login succeeded", extra={"event": "auth.login", "user_id": user.id})
    return TokenResponse(
        access_token=create_access_token(user.id),
        expires_in=settings.access_token_expire_minutes * 60,
    )


@router.get("/me", response_model=UserResponse, summary="Current user", responses=error_docs(401))
def me(current_user: CurrentUser) -> UserResponse:
    """The user the bearer token belongs to."""
    return UserResponse.model_validate(current_user)
