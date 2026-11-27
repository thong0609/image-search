"""Real PostgreSQL transactions in a disposable schema; no production rows touched."""

import os
from uuid import uuid4

import pytest
import sqlalchemy as sa
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

from image_search.adapters.postgres.database import create_database_engine
from image_search.adapters.postgres.schema import metadata
from image_search.auth.service import AuthService
from image_search.config import Settings

pytestmark = pytest.mark.skipif(
    os.getenv("RUN_AUTH_INTEGRATION") != "1", reason="Requires local PostgreSQL"
)
PASSWORD = "test-only-password-1234"


@pytest.fixture
def accounts(tmp_path):
    settings = Settings(auth_private_key=tmp_path / "private.pem")
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    settings.auth_private_key.write_bytes(
        key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        )
    )
    base = create_database_engine(settings)
    schema = "test_auth_" + uuid4().hex
    with base.begin() as conn:
        conn.execute(sa.text(f'CREATE SCHEMA "{schema}"'))
    engine = sa.create_engine(
        settings.database_url.get_secret_value(),
        connect_args={"options": f"-csearch_path={schema}"},
    )
    metadata.create_all(engine)
    service = AuthService(engine, settings)
    try:
        yield service, settings
    finally:
        engine.dispose()
        with base.begin() as conn:
            conn.execute(sa.text(f'DROP SCHEMA "{schema}" CASCADE'))
        base.dispose()


def add(service, email="user@example.com", role="user"):
    return service.create_user(email, "Test", PASSWORD, role)


def test_csv_publisher_switches_only_after_graph_ready(accounts, monkeypatch):
    import numpy as np
    from qdrant_client import QdrantClient, models

    from image_search.adapters.neo4j.store import validate_mapping
    from image_search.adapters.postgres.schema import jobs, search_configs
    from image_search.adapters.qdrant.metadata import metadata_payload, sync_metadata
    from image_search.adapters.qdrant.vectors import QdrantVectors, point_id
    from image_search.ingestion.publish import Publisher
    from image_search.ingestion.service import Imports
    from image_search.library import COLLECTION, Library
    from image_search.retrieval.catalog import Catalog

    service, settings = accounts
    client = QdrantClient(":memory:")
    record = {
        "record_id": "csv-1",
        "image_id": "old",
        "entity_id": "A",
        "entity_name": "Place A",
        "image_url": "https://example.com/old.jpg",
        "download_status": "success",
        "leaf_label": "Place",
    }
    index = {
        "index_sha256": "old-index",
        "image_ids": ["old"],
        "shape": [1, 2],
        "processor_sha256": "processor",
        "config": {"model": "test", "revision": "r"},
    }
    store = QdrantVectors(client, "base", "old-index", 2)
    catalog = Catalog([record], ["old"])
    store.upload(["old"], np.array([[1, 0]], dtype=np.float32), catalog, "test", "r")
    index = sync_metadata(
        store, index, catalog, [{"image_id": "old", "local_path": "/old"}], "records"
    )
    store.payloads = {"old": metadata_payload([record], {"image_id": "old", "local_path": "/old"})}
    library = Library(service.engine, settings.auth_private_key)
    library.bootstrap(index)
    with service.engine.begin() as conn:
        conn.execute(search_configs.update().values(vector_index={"collection": "base"}))
    graph = Publisher.extend_graph(
        {
            "entities": [],
            "relations": [],
            "image_links": [],
            "image_ids": [],
            "metadata_sha256": "",
        },
        index,
        [record],
    )

    class Driver:
        def close(self):
            pass

    class Graph:
        broken = True

        def __init__(self, *args):
            pass

        def export(self):
            return graph

        def import_graph(self, graph, index, payloads):
            validate_mapping(graph, index, payloads)
            if self.broken:
                raise ConnectionError("graph unavailable")

        def validate(self, index, payloads):
            pass

    monkeypatch.setattr("image_search.ingestion.publish.create_graph_driver", lambda _: Driver())
    monkeypatch.setattr("image_search.ingestion.publish.GraphStore", Graph)

    # Source client must stay alive throughout both attempts.
    class Source:
        payloads = store.payloads
        client = Driver()

        def vector_for(self, iid):
            return store.vector_for(iid)

    monkeypatch.setattr(
        "image_search.ingestion.publish.load_index", lambda **_: (None, index, Source())
    )
    root_id, item_id = uuid4(), uuid4()
    with service.engine.begin() as conn:
        conn.execute(
            jobs.insert().values(
                id=root_id,
                type="csv_import",
                status="running",
                dedupe_key=str(root_id),
                payload={"collection_id": str(COLLECTION)},
            )
        )
        conn.execute(
            jobs.insert().values(
                id=item_id,
                parent_id=root_id,
                type="csv_item",
                status="running",
                dedupe_key=str(item_id),
                payload={"line": 1, "record": {}},
            )
        )
    new = {
        **record,
        "record_id": "import-new",
        "image_id": "new",
        "entity_id": "B",
        "entity_name": "Place B",
        "image_url": "https://example.com/new.jpg",
    }
    client.create_collection(
        "stage", vectors_config=models.VectorParams(size=2, distance=models.Distance.COSINE)
    )
    client.upsert(
        "stage",
        [
            models.PointStruct(
                id=point_id(str(item_id)),
                vector=[0.0, 1.0],
                payload={
                    "record": new,
                    "image": {"image_id": "new", "local_path": "/new"},
                    "collection_id": str(COLLECTION),
                },
            )
        ],
    )
    publisher = Publisher(service.engine, client, settings, {"id": root_id})
    with pytest.raises(ConnectionError):
        publisher.publish("stage")
    assert library.visible() == {"old"}
    Graph.broken = False
    publisher.publish("stage")
    assert library.visible() == {"old", "new"}
    assert Imports(service.engine).report(root_id)["counts"] == {"succeeded": 1}
    publisher.publish("stage")  # crash after commit is safe to replay
    client.close()
