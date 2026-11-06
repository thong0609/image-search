from collections.abc import Callable

from qdrant_client import QdrantClient
from sqlalchemy import text
from sqlalchemy.engine import Engine

from image_search.adapters.object_storage.local import LocalObjectStorage
from image_search.adapters.postgres.schema import metadata


class Readiness:
    def __init__(self, engine: Engine, qdrant: QdrantClient, storage: LocalObjectStorage):
        self.engine, self.qdrant, self.storage = engine, qdrant, storage

    def check(self) -> dict[str, bool]:
        def database() -> None:
            with self.engine.connect() as connection:
                for name in metadata.tables:
                    if connection.scalar(text("SELECT to_regclass(:name)"), {"name": name}) is None:
                        raise RuntimeError("Schema migration is missing")

        probes: dict[str, Callable] = {
            "postgres": database,
            "qdrant": self.qdrant.get_collections,
            "storage": self.storage.probe,
        }
        result = {}
        for name, probe in probes.items():
            try:
                probe()
                result[name] = True
            except Exception:
                result[name] = False
        return result
