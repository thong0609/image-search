from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class EmbeddingSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="IMAGE_SEARCH_EMBEDDING_", env_file=".env", extra="ignore"
    )

    manifest: Path = Path("var/benchmark-v1/benchmark.json")
    cache_dir: Path = Path("var/models")
    threads: int = Field(default=4, ge=1)
    batch_size: int = Field(default=8, ge=1, le=64)
