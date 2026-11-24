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
    bridge_candidates: int = Field(default=20, ge=1)
    bridge_entities: int = Field(default=3, ge=1)
    path_combination_limit: int = Field(default=64, ge=1, le=256)
    paths_per_entity: int = Field(default=2, ge=1, le=5)
    default_count: int = Field(default=10, ge=1, le=100)
