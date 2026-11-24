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
    # Số ảnh mỗi mục tiêu ở chế độ danh sách; số lượng trong câu không cắt danh sách.
    list_size: int = Field(default=20, ge=1, le=100)
    default_count: int = Field(default=10, ge=1, le=100)
    # Số nơi ứng viên giữ lại làm bằng chứng; ảnh chỉ lấy từ nơi đứng đầu.
    bridge_hypotheses: int = Field(default=3, ge=1, le=10)
    bridge_images: int = Field(default=3, ge=1, le=10)
    # Nơi graph xác nhận thắng nơi chưa rõ vị trí nếu kém điểm đầu không quá tỷ lệ này.
    bridge_margin: float = Field(default=0.1, ge=0, le=1)
