"""Authentication business logic, independent of HTTP concerns."""

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.auth.security import hash_password, verify_password
from app.database.models import User


class EmailAlreadyRegisteredError(Exception):
    """Raised when an email is already present in the users table."""


def normalize_email(email: str) -> str:
    """Addresses are matched case-insensitively, so store one canonical form."""
    return email.strip().lower()


def get_user_by_email(db: Session, email: str) -> User | None:
    return db.scalar(select(User).where(User.email == normalize_email(email)))


def get_user_by_id(db: Session, user_id: int) -> User | None:
    return db.get(User, user_id)


def register_user(db: Session, email: str, password: str) -> User:
    email = normalize_email(email)

    if get_user_by_email(db, email) is not None:
        raise EmailAlreadyRegisteredError

    user = User(email=email, password_hash=hash_password(password))
    db.add(user)
    try:
        db.commit()
    except IntegrityError as exc:
        # The check above loses to a concurrent registration of the same
        # address; the unique index is what actually settles it.
        db.rollback()
        raise EmailAlreadyRegisteredError from exc

    db.refresh(user)
    return user


def authenticate_user(db: Session, email: str, password: str) -> User | None:
    """Return the user when the credentials are valid, otherwise ``None``."""
    user = get_user_by_email(db, email)
    if user is None:
        # Hash anyway so a missing account and a wrong password take roughly
        # the same time, which keeps the response from revealing which it was.
        verify_password(password, _DUMMY_HASH)
        return None

    if not verify_password(password, user.password_hash):
        return None

    return user


# Pre-computed once at import: a valid bcrypt hash of a value nothing can match.
_DUMMY_HASH = hash_password("collabspace-timing-equalizer")
