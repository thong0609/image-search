import logging
from functools import lru_cache
from pathlib import Path

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="IMAGE_SEARCH_", env_file=".env", extra="ignore")
    database_url: SecretStr = SecretStr(
        "postgresql+psycopg://image_search:change-me@localhost:5432/image_search"
    )
    qdrant_url: str = "http://localhost:6333"
    storage_root: Path = Path("var/objects")
    log_level: str = "INFO"
    auth_private_key: Path = Path("var/auth/private.pem")
    auth_cookie_secure: bool = False
    auth_origins: list[str] = ["http://127.0.0.1:3000", "http://localhost:3000"]


def configure_logging(level: str) -> None:
    logging.basicConfig(
        level=level.upper(), format="%(asctime)s %(levelname)s %(name)s %(message)s"
    )


@lru_cache
def get_settings() -> Settings:
    return Settings()
