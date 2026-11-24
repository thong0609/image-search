from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class RetrievalSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="IMAGE_SEARCH_RETRIEVAL_", env_file=".env", extra="ignore"
    )

    qdrant_collection: str = "image_search_siglip2_v1"

    top_k: int = Field(default=100, ge=1)
    candidates: int = Field(default=100, ge=1)
    rrf_k: int = Field(default=60, ge=1)
    default_count: int = Field(default=10, ge=1, le=100)
