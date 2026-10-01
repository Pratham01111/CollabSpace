"""Test setup: a separate Postgres database, rebuilt per run, emptied per test.

The concurrency tests need real Postgres row locking, so SQLite will not do.

Order matters here. ``app.config`` builds its settings the moment it is first
imported, and the engine is created from them, so the overrides below must be
in the environment before *anything* imports ``app``. This file therefore
reads the development values straight from the environment and ``.env``,
without going through ``app.config``.
"""

import functools
import os
import time
from dataclasses import dataclass
from pathlib import Path

import bcrypt
import pytest
from dotenv import dotenv_values
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url

_env_file = dotenv_values(Path(__file__).resolve().parent.parent / ".env")


def _setting(name: str, default: str) -> str:
    return os.environ.get(name) or _env_file.get(name) or default


_dev_url = make_url(
    _setting("DATABASE_URL", "postgresql+psycopg://collabspace:collabspace@localhost:5432/collabspace")
)
TEST_DATABASE_URL = _dev_url.set(database=f"{_dev_url.database}_test")
os.environ["DATABASE_URL"] = TEST_DATABASE_URL.render_as_string(hide_password=False)

# The app under test runs single-instance, on in-memory delivery, so the suite
# does not need Redis. The bus tests build their own instances against this URL.
REDIS_URL = _setting("REDIS_URL", "redis://localhost:6379/0")
os.environ["REDIS_URL"] = ""


def _ensure_test_database() -> None:
    admin = create_engine(_dev_url.set(database="postgres"), isolation_level="AUTOCOMMIT")
    with admin.connect() as conn:
        exists = conn.scalar(
            text("SELECT 1 FROM pg_database WHERE datname = :name"),
            {"name": TEST_DATABASE_URL.database},
        )
        if not exists:
            conn.execute(text(f'CREATE DATABASE "{TEST_DATABASE_URL.database}"'))
    admin.dispose()


_ensure_test_database()

# Imported only now, so they bind to the test database.
from fastapi.testclient import TestClient  # noqa: E402

from app.database import Base, engine  # noqa: E402
from app.database import models  # noqa: E402, F401  (registers every table)
from app.main import app  # noqa: E402
from app.auth.security import create_access_token  # noqa: E402
from app.realtime.manager import manager  # noqa: E402

# bcrypt's default cost (12) is deliberately slow, and nearly every test
# registers several users. Cost 4 exercises the same code at a fraction of the
# time; nothing here depends on the work factor.
bcrypt.gensalt = functools.partial(bcrypt.gensalt, rounds=4)


def _refuse_unless_test_database() -> None:
    """Last line of defence: these fixtures drop and truncate every table."""
    if not (engine.url.database or "").endswith("_test"):
        raise RuntimeError(
            f"Refusing to run tests against {engine.url.database!r}: "
            "the app was configured before the test database override applied."
        )


@pytest.fixture(scope="session", autouse=True)
def schema():
    _refuse_unless_test_database()
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    yield
    engine.dispose()


@pytest.fixture(autouse=True)
def clean_tables():
    yield
    _refuse_unless_test_database()
    tables = ", ".join(t.name for t in Base.metadata.sorted_tables)
    with engine.begin() as conn:
        conn.execute(text(f"TRUNCATE {tables} RESTART IDENTITY CASCADE"))


@pytest.fixture(autouse=True)
def no_leaked_sockets():
    """Every test must leave the app's connection manager as it found it:
    empty. A socket closes on the server a moment after the client lets go, so
    allow it a second."""
    yield
    deadline = time.monotonic() + 1.0
    while manager.connections and time.monotonic() < deadline:
        time.sleep(0.01)
    leaked = manager.connections
    manager.connections = {}  # so one failure does not cascade into the next test
    assert not leaked, f"sockets left registered after the test: {leaked}"


@pytest.fixture
def client():
    with TestClient(app) as c:
        yield c


def register_and_login(client: TestClient, email: str) -> dict:
    client.post("/auth/register", json={"email": email, "password": "password123"})
    token = client.post("/auth/login", json={"email": email, "password": "password123"}).json()[
        "access_token"
    ]
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def owner(client):
    return register_and_login(client, "owner@example.com")


PASSWORD = "password123"


@dataclass
class Account:
    id: int
    email: str
    token: str

    @property
    def headers(self) -> dict:
        return {"Authorization": f"Bearer {self.token}"}


@pytest.fixture
def make_account(client):
    """Register and log in a new user: ``make_account("alice")``."""

    def make(name: str) -> Account:
        email = f"{name}@example.com"
        created = client.post("/auth/register", json={"email": email, "password": PASSWORD})
        assert created.status_code == 201, created.text
        # The same token /auth/login would issue. Login itself is covered in
        # test_auth.py; going through it here would only add bcrypt time.
        user_id = created.json()["id"]
        return Account(id=user_id, email=email, token=create_access_token(user_id))

    return make


@dataclass
class Team:
    """A workspace with one account per role, plus someone outside it."""

    workspace_id: int
    owner: Account
    admin: Account
    member: Account
    outsider: Account


@pytest.fixture
def team(client, make_account) -> Team:
    owner, admin, member, outsider = (
        make_account(n) for n in ("teamowner", "teamadmin", "teammember", "outsider")
    )
    workspace = client.post("/workspaces", json={"name": "Team"}, headers=owner.headers).json()
    for account, role in ((admin, "ADMIN"), (member, "MEMBER")):
        added = client.post(
            f"/workspaces/{workspace['id']}/members",
            json={"user_id": account.id, "role": role},
            headers=owner.headers,
        )
        assert added.status_code == 201, added.text
    return Team(workspace["id"], owner, admin, member, outsider)


@pytest.fixture
def team_task(client, team) -> dict:
    """A task in the team's workspace, created by its owner."""
    response = client.post(
        f"/workspaces/{team.workspace_id}/tasks", json={"title": "Team task"}, headers=team.owner.headers
    )
    assert response.status_code == 201, response.text
    return response.json()


@pytest.fixture
def task(client, owner):
    """A fresh task (version 1) in a fresh workspace."""
    workspace = client.post("/workspaces", json={"name": "W"}, headers=owner).json()
    return client.post(
        f"/workspaces/{workspace['id']}/tasks", json={"title": "Original"}, headers=owner
    ).json()
