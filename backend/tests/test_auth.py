"""Authentication: registration, login, and what counts as a valid token."""

from datetime import UTC, datetime, timedelta

import jwt
import pytest

from app.auth.security import create_access_token
from app.config import settings
from tests.conftest import PASSWORD

ME = "/auth/me"


def register(client, email="new@example.com", password=PASSWORD):
    return client.post("/auth/register", json={"email": email, "password": password})


def login(client, email="new@example.com", password=PASSWORD):
    return client.post("/auth/login", json={"email": email, "password": password})


def bearer(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


# ---- register -----------------------------------------------------------------


def test_register_succeeds_and_never_returns_the_password(client):
    response = register(client)

    assert response.status_code == 201
    body = response.json()
    assert body["email"] == "new@example.com"
    assert set(body) == {"id", "email", "created_at"}


def test_register_normalizes_email_case_and_whitespace(client):
    assert register(client, email="  Mixed.Case@Example.COM ").json()["email"] == "mixed.case@example.com"


@pytest.mark.parametrize("second", ["dup@example.com", "DUP@example.com"])
def test_register_duplicate_email_is_409(client, second):
    assert register(client, email="dup@example.com").status_code == 201

    response = register(client, email=second)

    assert response.status_code == 409
    assert response.json()["detail"] == "An account with this email already exists."


@pytest.mark.parametrize("email", ["not-an-email", "missing-at.example.com", "a@", "@example.com", ""])
def test_register_rejects_invalid_email(client, email):
    assert register(client, email=email).status_code == 422


@pytest.mark.parametrize(
    "password",
    [
        "short",  # under 8 characters
        "",
        "x" * 73,  # over bcrypt's 72-byte limit
        "é" * 37,  # 37 characters but 74 bytes
    ],
)
def test_register_rejects_invalid_password(client, password):
    assert register(client, password=password).status_code == 422


def test_register_accepts_a_72_byte_password(client):
    assert register(client, password="x" * 72).status_code == 201
    assert login(client, password="x" * 72).status_code == 200


@pytest.mark.parametrize("body", [{}, {"email": "a@example.com"}, {"password": PASSWORD}])
def test_register_requires_both_fields(client, body):
    assert client.post("/auth/register", json=body).status_code == 422


# ---- login ----------------------------------------------------------------------


def test_login_returns_a_working_token(client):
    register(client)

    response = login(client)

    assert response.status_code == 200
    body = response.json()
    assert body["token_type"] == "bearer"
    assert body["expires_in"] == settings.access_token_expire_minutes * 60
    me = client.get(ME, headers=bearer(body["access_token"]))
    assert me.status_code == 200
    assert me.json()["email"] == "new@example.com"


def test_login_email_is_case_insensitive(client):
    register(client)
    assert login(client, email="NEW@Example.com").status_code == 200


def test_wrong_password_and_unknown_email_are_indistinguishable(client):
    register(client)

    wrong_password = login(client, password="not-the-password")
    unknown_email = login(client, email="nobody@example.com")

    # Same status, same body, same header: the endpoint must not reveal
    # which addresses have accounts.
    assert wrong_password.status_code == unknown_email.status_code == 401
    assert wrong_password.json() == unknown_email.json() == {"detail": "Incorrect email or password."}
    assert wrong_password.headers["www-authenticate"] == unknown_email.headers["www-authenticate"] == "Bearer"


# ---- tokens -----------------------------------------------------------------------


def _token(user_id: int, *, key: str | None = None, expires_in: timedelta = timedelta(minutes=5), **claims) -> str:
    now = datetime.now(UTC)
    payload = {"sub": str(user_id), "iat": now, "exp": now + expires_in, **claims}
    return jwt.encode(payload, key or settings.jwt_secret_key, algorithm=settings.jwt_algorithm)


def test_missing_token_is_401(client):
    response = client.get(ME)
    assert response.status_code == 401
    assert response.json()["detail"] == "Not authenticated"
    assert response.headers["www-authenticate"] == "Bearer"


def test_expired_token_is_401(client, make_account):
    account = make_account("expired")
    token = _token(account.id, expires_in=timedelta(seconds=-1))

    response = client.get(ME, headers=bearer(token))

    assert response.status_code == 401
    assert response.json()["detail"] == "Token has expired"


def test_token_signed_with_another_key_is_401(client, make_account):
    account = make_account("forged")
    forged = _token(account.id, key="not-the-server-secret-but-long-enough-for-hs256")

    response = client.get(ME, headers=bearer(forged))

    assert response.status_code == 401
    assert response.json()["detail"] == "Could not validate credentials"


def test_alg_none_token_is_rejected(client, make_account):
    account = make_account("unsigned")
    unsigned = jwt.encode(
        {"sub": str(account.id), "exp": datetime.now(UTC) + timedelta(minutes=5)}, key=None, algorithm="none"
    )
    assert client.get(ME, headers=bearer(unsigned)).status_code == 401


@pytest.mark.parametrize(
    "token",
    ["not-a-jwt", "a.b.c", "eyJhbGciOiJIUzI1NiJ9.e30.", "Bearer", ""],
)
def test_malformed_token_is_401(client, token):
    assert client.get(ME, headers={"Authorization": f"Bearer {token}"}).status_code == 401


def test_wrong_auth_scheme_is_401(client, make_account):
    account = make_account("basic")
    assert client.get(ME, headers={"Authorization": f"Basic {account.token}"}).status_code == 401


@pytest.mark.parametrize("sub", [None, "not-a-number"])
def test_token_without_a_usable_subject_is_401(client, sub):
    now = datetime.now(UTC)
    payload = {"iat": now, "exp": now + timedelta(minutes=5)}
    if sub is not None:
        payload["sub"] = sub
    token = jwt.encode(payload, settings.jwt_secret_key, algorithm=settings.jwt_algorithm)
    assert client.get(ME, headers=bearer(token)).status_code == 401


def test_token_for_a_deleted_user_is_401(client):
    token = create_access_token(999_999)  # validly signed, but no such user

    response = client.get(ME, headers=bearer(token))

    assert response.status_code == 401
    assert response.json()["detail"] == "User no longer exists"


@pytest.mark.parametrize("path", ["/workspaces", "/workspaces/1", "/workspaces/1/tasks", "/tasks/1/comments"])
def test_protected_routes_reject_missing_token(client, path):
    assert client.get(path).status_code == 401
