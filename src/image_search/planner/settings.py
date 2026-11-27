"""Cấu hình riêng cho planner; API key không được xuất ra log."""

from typing import Literal

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class PlannerSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="IMAGE_SEARCH_PLANNER_", env_file=".env", extra="ignore"
    )

    api_key: SecretStr | None = Field(default=None, validation_alias="OPENAI_API_KEY")
    model: str = Field(default="gpt-5-mini-2025-08-07", min_length=1)
    timeout: float = Field(default=60, gt=0)
    retries: int = Field(default=1, ge=0, le=3)
    max_output_tokens: int = Field(default=4096, ge=256, le=16384)
    # None: mặc định của model. 'low' giảm độ trễ và nguy cơ hết token vì suy luận dài.
    reasoning_effort: Literal["minimal", "low", "medium", "high"] | None = "low"
    # Số kế hoạch giữ trong RAM cho màn hình tìm ảnh; 0 là tắt.
    cache_size: int = Field(default=1000, ge=0, le=100_000)
    max_query_chars: int = Field(default=4000, ge=1, le=20000)
    # Giá USD / 1M tokens do người chạy cung cấp; không hard-code giá nhà cung cấp.
    input_price: float | None = Field(default=None, ge=0)
    cached_input_price: float | None = Field(default=None, ge=0)
    output_price: float | None = Field(default=None, ge=0)
