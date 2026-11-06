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


@lru_cache
def get_settings() -> Settings:
    return Settings()
