from functools import lru_cache

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings, read from the environment (or backend/.env)."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    database_url: str = "postgresql+psycopg://collabspace:collabspace@localhost:5432/collabspace"

    @field_validator("database_url")
    @classmethod
    def use_psycopg_driver(cls, url: str) -> str:
        """Accept the URLs hosting providers hand out.

        Railway (and Heroku-style hosts) give ``postgresql://...`` or the older
        ``postgres://...``. SQLAlchemy reads a bare ``postgresql://`` as the
        psycopg2 driver, which is not installed, and does not know
        ``postgres://`` at all, so both are pointed at psycopg (v3).
        """
        for prefix in ("postgres://", "postgresql://"):
            if url.startswith(prefix):
                return "postgresql+psycopg://" + url[len(prefix):]
        return url

    # Pub/sub that fans realtime events out across backend instances. Set it
    # empty (REDIS_URL=) to run a single instance on in-memory delivery only.
    redis_url: str | None = "redis://localhost:6379/0"

    # Browser origins allowed to call the API cross-origin, comma-separated.
    # Not needed behind the Docker stack's nginx, which serves the frontend and
    # proxies the API from one origin.
    cors_origins: str = "http://localhost:5173"

    # Connection pool, per worker process. With the defaults, 2 workers can hold
    # at most 2 * (5 + 10) = 30 connections, well under Postgres's default 100.
    db_pool_size: int = 5
    db_max_overflow: int = 10
    # Fail fast with a 503 rather than letting requests queue for a connection.
    db_pool_timeout: int = 10
    # Recycle connections before any proxy or firewall idles them out.
    db_pool_recycle: int = 1800

    # INFO, DEBUG, WARNING...; json (one object per line) or text.
    log_level: str = "INFO"
    log_format: str = "json"

    # Echo every SQL statement to stdout. Useful while learning the ORM.
    sql_echo: bool = False

    # Signing key for access tokens. Deliberately has no default: the app
    # should refuse to start rather than run on a secret that is public
    # knowledge. Generate one with `python -c "import secrets;
    # print(secrets.token_urlsafe(48))"`.
    jwt_secret_key: str
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 60


    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
