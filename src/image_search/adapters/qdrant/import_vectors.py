"""Index ảnh trực tiếp vào Qdrant, không tạo file vector."""

from image_search.baseline.vectors import build_index
from image_search.embedding.settings import EmbeddingSettings
from image_search.retrieval.settings import RetrievalSettings


def main():
    settings = EmbeddingSettings()
    build_index(
        settings.manifest,
        RetrievalSettings().qdrant_collection,
        batch_size=settings.batch_size,
        threads=settings.threads,
    )


if __name__ == "__main__":
    main()
