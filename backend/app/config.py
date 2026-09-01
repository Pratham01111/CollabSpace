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


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
