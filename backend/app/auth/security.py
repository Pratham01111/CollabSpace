"""Password hashing and JWT encoding/decoding.

Kept free of database and FastAPI imports so it stays easy to test on its own.
"""

from datetime import UTC, datetime, timedelta

import bcrypt
import jwt

from app.config import settings

# bcrypt hashes at most 72 bytes and silently ignores anything beyond that,
# which would make "<72 bytes><anything>" accepted as the same password. The
# registration schema rejects longer passwords instead of truncating them.
MAX_PASSWORD_BYTES = 72


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return bcrypt.checkpw(password.encode(), password_hash.encode())
    except ValueError:
        # Malformed/corrupt hash in the database — treat as a failed login
        # rather than a 500.
        return False


def create_access_token(user_id: int) -> str:
    now = datetime.now(UTC)
    payload = {
        # The JWT spec requires "sub" to be a string.
        "sub": str(user_id),
        "iat": now,
        "exp": now + timedelta(minutes=settings.access_token_expire_minutes),
    }
    return jwt.encode(payload, settings.jwt_secret_key, algorithm=settings.jwt_algorithm)


def decode_access_token(token: str) -> dict:
    """Decode and verify a token. Raises ``jwt.PyJWTError`` if it isn't valid.

    ``algorithms`` is pinned to the configured algorithm so a token can't talk
    the server into accepting a weaker one (or "none").
    """
    return jwt.decode(
        token,
        settings.jwt_secret_key,
        algorithms=[settings.jwt_algorithm],
        options={"require": ["exp", "sub"]},
    )
