from pathlib import Path

import numpy as np
import pytest
from qdrant_client import QdrantClient

from image_search.adapters.qdrant.metadata import read_payloads, sync_metadata
from image_search.adapters.qdrant.vectors import QdrantVectors, point_id
from image_search.baseline.vectors import PREPROCESSING, library_versions
from image_search.embedding.settings import EmbeddingSettings
from image_search.retrieval.catalog import Catalog
from image_search.retrieval.runtime import load_engine
from image_search.retrieval.settings import RetrievalSettings

pytestmark = [
    pytest.mark.filterwarnings("ignore:Payload indexes:UserWarning"),
    pytest.mark.filterwarnings("ignore:Local mode performs exact:UserWarning"),
]


@pytest.fixture
def snapshot():
    rows = [
        {
            "image_id": iid,
            "entity_id": eid,
            "entity_name": name,
            "mo_ta": caption,
            "download_status": "success",
            "record_id": str(i),
            "page_url": "https://example.com",
        }
        for i, (iid, eid, name, caption) in enumerate(
            [
                ("a", "A", "Cửa hàng A", "cổng đỏ"),
                ("a", "B", "Cửa hàng B", "ảnh liên quan"),
                ("b", "A", "Cửa hàng A", "bên trong"),
                ("c", "C", "Cửa hàng C", "cổng đỏ"),
            ]
        )
    ]
    ids = ["a", "b", "c"]
    vectors = np.array([[1, 0], [0, 1], [0.8, 0.6]], dtype=np.float32)
    client = QdrantClient(":memory:")
    store = QdrantVectors(client, "images", "index-v1", 2)
    catalog = Catalog(rows, ids)
    store.upload(ids, vectors, catalog, "test", "a" * 40)
    index = {
        "image_ids": ids,
        "index_sha256": "index-v1",
        "shape": [3, 2],
        "processor_sha256": "processor",
        "config": {
            "model": "test",
            "revision": "a" * 40,
            "preprocessing": PREPROCESSING,
            "libraries": library_versions(),
            "manifest_sha256": "manifest",
        },
    }
    images = [{"image_id": iid, "local_path": f"/missing/{iid}.jpg"} for iid in ids]
    index = sync_metadata(store, index, catalog, images, "records-v1")
    yield store, index, rows, images, vectors
    client.close()


def test_sync_keeps_vectors_and_every_source_record(snapshot):
    store, index, rows, images, vectors = snapshot
    payloads = read_payloads(store, index["image_ids"], index["search_metadata_sha256"])
    assert payloads["a"]["records"] == rows[:2]
    assert payloads["a"]["entity_names"] == ["Cửa hàng A", "Cửa hàng B"]
    for iid, vector in zip(index["image_ids"], vectors, strict=True):
        np.testing.assert_allclose(store.vector_for(iid), vector)
    repeated = sync_metadata(store, index, Catalog(rows, index["image_ids"]), images, "records-v1")
    assert repeated["search_metadata_sha256"] == index["search_metadata_sha256"]


def test_entity_filters_and_exclusions_apply_before_vector_top_k(snapshot):
    store, _, _, _, vectors = snapshot
    assert store.search(vectors[0], 1, entity_ids={"A"}, excluded={"a"})[0]["image_id"] == "b"
    assert store.search(vectors[0], 1, entity_ids={"missing"}) == []
    assert store.search(vectors[0], 1, entity_ids=set()) == []
    query_filter = store.query_filter(entity_ids={"A"})
    assert any(getattr(c, "key", None) == "entity_ids" for c in query_filter.must)
    assert not any(hasattr(c, "has_id") for c in query_filter.must)


def test_entity_name_lookup_does_not_mix_records_on_shared_image(snapshot):
    store, index, rows, _, _ = snapshot
    catalog = Catalog(rows, index["image_ids"], vector_store=store)
    assert catalog.resolve("CUA HANG A") == {"A"}
    assert catalog.resolve("Cửa hàng B") == {"B"}
    assert catalog.resolve("Cửa hàng không tồn tại") == set()


def test_runtime_does_not_read_source_files_and_bm25_uses_qdrant(snapshot, monkeypatch):
    store, index, _, _, _ = snapshot
    monkeypatch.setattr(
        "image_search.adapters.qdrant.client.create_qdrant_client", lambda _: store.client
    )
    monkeypatch.setattr(
        "image_search.baseline.vectors.load_manifest",
        lambda *_: pytest.fail("Không được đọc manifest lúc retrieval"),
    )
    monkeypatch.setattr(
        "image_search.baseline.utils.read_jsonl",
        lambda *_: pytest.fail("Không được đọc JSONL metadata"),
    )
    from image_search.adapters.qdrant.metadata import name_key

    class Graph:
        def resolve(self, name):
            return {r["entity_id"] for r in snapshot[2] if name_key(r["entity_name"]) == name}

        def images_for(self, ids):
            return {r["image_id"] for r in snapshot[2] if r["entity_id"] in ids}

    monkeypatch.setattr("image_search.retrieval.runtime.load_graph", lambda *_: Graph())
    engine, corpus, _ = load_engine(
        EmbeddingSettings(_env_file=None, manifest=Path("missing.json")),
        RetrievalSettings(_env_file=None, qdrant_collection="images"),
    )
    monkeypatch.setattr(
        engine.catalog,
        "images_for",
        lambda *_: pytest.fail("Phải lọc entity trực tiếp trong Qdrant"),
    )
    assert len(corpus["images"]) == len(index["image_ids"])
    assert engine.catalog.resolve("cửa hàng A") == {"A"}
    result = engine.search("bên trong", None, "keyword", 1, entity_ids={"A"})
    assert [r["image_id"] for r in result] == ["b"]
    assert engine.search("cổng đỏ", None, "keyword", 1, entity_ids={"missing"}) == []
    assert engine.keyword_metadata["source"] == "qdrant_payload"


def test_snapshot_refuses_missing_or_tampered_metadata(snapshot):
    store, index, _, _, _ = snapshot
    store.client.set_payload(store.collection, {"captions": ["đã bị thay đổi"]}, [point_id("a")])
    with pytest.raises(ValueError, match="không nhất quán"):
        read_payloads(store, index["image_ids"], index["search_metadata_sha256"])


def test_snapshot_refuses_an_unfinished_migration(snapshot):
    store, index, _, _, _ = snapshot
    store.client.set_payload(
        store.collection, {"search_metadata_sha256": "unfinished"}, [point_id("a")]
    )
    with pytest.raises(ValueError, match="không khớp"):
        read_payloads(store, index["image_ids"], index["search_metadata_sha256"])


def test_qdrant_failure_does_not_fall_back_to_local_catalog(snapshot, monkeypatch):
    store, index, rows, _, _ = snapshot
    catalog = Catalog(rows, index["image_ids"], vector_store=store)

    def unavailable(*args, **kwargs):
        raise ConnectionError("Qdrant unavailable")

    monkeypatch.setattr(store.client, "scroll", unavailable)
    with pytest.raises(ConnectionError, match="unavailable"):
        catalog.resolve("Cửa hàng A")
