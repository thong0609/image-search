from qdrant_client import QdrantClient

from image_search.config import Settings


def create_qdrant_client(settings: Settings) -> QdrantClient:
    return QdrantClient(url=settings.qdrant_url, timeout=3, check_compatibility=False)
