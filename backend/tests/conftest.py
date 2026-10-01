"""Test setup: a separate Postgres database, rebuilt per run, emptied per test.

The concurrency tests need real Postgres row locking, so SQLite will not do.
DATABASE_URL is pointed at ``<dev database>_test`` *before* the app is
imported, so the app's engine never touches development data.
"""

import os

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url

from app.config import Settings

_dev_url = make_url(Settings().database_url)
TEST_DATABASE_URL = _dev_url.set(database=f"{_dev_url.database}_test")
os.environ["DATABASE_URL"] = TEST_DATABASE_URL.render_as_string(hide_password=False)


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


@pytest.fixture(scope="session", autouse=True)
def schema():
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    yield
    engine.dispose()


@pytest.fixture(autouse=True)
def clean_tables():
    yield
    tables = ", ".join(t.name for t in Base.metadata.sorted_tables)
    with engine.begin() as conn:
        conn.execute(text(f"TRUNCATE {tables} RESTART IDENTITY CASCADE"))


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


@pytest.fixture
def task(client, owner):
    """A fresh task (version 1) in a fresh workspace."""
    workspace = client.post("/workspaces", json={"name": "W"}, headers=owner).json()
    return client.post(
        f"/workspaces/{workspace['id']}/tasks", json={"title": "Original"}, headers=owner
    ).json()
