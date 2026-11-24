from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class GraphSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="IMAGE_SEARCH_GRAPH_", env_file=".env", extra="ignore"
    )

    uri: str = "bolt://localhost:7687"
    username: str = "neo4j"
    password: SecretStr
    database: str = "neo4j"
    dataset_id: str = Field(default="image-search", min_length=1)
    timeout: float = Field(default=10, gt=0)
    batch_size: int = Field(default=200, ge=1, le=1000)

    workers: int = Field(default=4, ge=1, le=8)
    max_input_chars: int = Field(default=24000, ge=2000, le=100000)
    max_output_tokens: int = Field(default=8192, ge=1024, le=16384)
    extraction_timeout: float = Field(default=120, gt=0)
