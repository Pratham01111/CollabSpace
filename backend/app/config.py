from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings, read from the environment (or backend/.env)."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    database_url: str = "postgresql+psycopg://collabspace:collabspace@localhost:5432/collabspace"

    # Echo every SQL statement to stdout. Useful while learning the ORM.
    sql_echo: bool = False

    # Signing key for access tokens. Deliberately has no default: the app
    # should refuse to start rather than run on a secret that is public
    # knowledge. Generate one with `python -c "import secrets;
    # print(secrets.token_urlsafe(48))"`.
    jwt_secret_key: str
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 60


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
