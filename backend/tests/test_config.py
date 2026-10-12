"""Settings accept the connection strings hosting providers hand out."""

import pytest

from app.config import Settings


@pytest.mark.parametrize(
    ("given", "expected"),
    [
        # Railway's Postgres plugin, and the older Heroku-style scheme.
        (
            "postgresql://u:p@postgres.railway.internal:5432/railway",
            "postgresql+psycopg://u:p@postgres.railway.internal:5432/railway",
        ),
        ("postgres://u:p@host:5432/db", "postgresql+psycopg://u:p@host:5432/db"),
        # Already explicit: left alone.
        ("postgresql+psycopg://u:p@host/db", "postgresql+psycopg://u:p@host/db"),
    ],
)
def test_database_url_is_pointed_at_psycopg(given, expected):
    assert Settings(database_url=given, jwt_secret_key="x").database_url == expected


def test_only_the_scheme_changes():
    """A password containing the scheme text must not be rewritten."""
    url = "postgresql://user:postgresql%3A%2F%2Fx@host:5432/db"
    assert Settings(database_url=url, jwt_secret_key="x").database_url == (
        "postgresql+psycopg://user:postgresql%3A%2F%2Fx@host:5432/db"
    )


def test_cors_origins_are_a_comma_separated_list():
    raw = " https://app.up.railway.app , http://localhost:5173,"
    settings = Settings(cors_origins=raw, jwt_secret_key="x")
    assert settings.cors_origin_list == ["https://app.up.railway.app", "http://localhost:5173"]
