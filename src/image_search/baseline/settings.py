"""Cấu hình baseline: mặc định trong code, có thể đổi qua .env hoặc CLI."""

from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class BaselineSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="IMAGE_SEARCH_BASELINE_", env_file=".env", extra="ignore"
    )

    # Tải ảnh
    timeout: float = Field(default=15, gt=0)
    retries: int = Field(default=2, ge=0)
    workers: int = Field(default=1, ge=1)
    max_bytes: int = Field(default=10 * 1024 * 1024, ge=1)
    max_pixels: int = Field(default=40_000_000, ge=1)

    # Model mã hóa ảnh và văn bản
    model_name: str = Field(default="google/siglip2-base-patch16-224", min_length=1)
    model_revision: str = Field(
        default="75de2d55ec2d0b4efc50b3e9ad70dba96a7b2fa2", pattern=r"^[0-9a-f]{40}$"
    )

    # Keyword và hybrid
    keyword_k1: float = Field(default=1.2, gt=0)
    keyword_b: float = Field(default=0.75, ge=0, le=1)
    hybrid_rrf_k: int = Field(default=60, ge=1)
    hybrid_candidates: int = Field(default=100, ge=10)


@lru_cache
def get_baseline_settings() -> BaselineSettings:
    return BaselineSettings()
