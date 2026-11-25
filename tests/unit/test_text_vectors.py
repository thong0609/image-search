"""Vector tên + mô tả theo record; encoder giả, Qdrant trong RAM."""

from contextlib import closing
from types import SimpleNamespace

import numpy as np
import pytest
from qdrant_client import QdrantClient

from image_search.adapters.qdrant.text_vectors import QdrantTextVectors
from image_search.adapters.qdrant.vectors import QdrantVectors
from image_search.embedding.text_index import build_text_index, load_text_store, text_documents
from image_search.retrieval.engine import RetrievalEngine
from image_search.retrieval.keyword import build_documents, prepare_bm25
from image_search.retrieval.settings import RetrievalSettings

pytestmark = [
    pytest.mark.filterwarnings("ignore:Payload indexes:UserWarning"),
    pytest.mark.filterwarnings("ignore:Local mode performs exact:UserWarning"),
]

RECORDS = [
    ("1", "a", "A", "Chợ A", "cổng đỏ"),
    ("2", "a", "B", "Chợ B", "bên trong"),
    ("3", "b", "B", "Chợ B", "cổng đỏ"),
    ("4", "c", "C", "Chợ C", "bãi xe"),
]
VECTORS = {
    "Chợ A. cổng đỏ": [1, 0],
    "Chợ B. bên trong": [0, 1],
    "Chợ B. cổng đỏ": [0.8, 0.6],
    "Chợ C. bãi xe": [-1, 0],
}


class FakeEncoder:
    def __init__(self, store, index):
        self.vector_store, self.index = store, index

    def encode_texts(self, texts):
        return np.array([VECTORS[t] for t in texts], dtype=np.float32), [
            {"truncated": False} for _ in texts
        ]


@pytest.fixture
def built():
    payloads = {}
    for rid, iid, eid, name, caption in RECORDS:
        row = {
            "record_id": rid,
            "image_id": iid,
            "entity_id": eid,
            "entity_name": name,
            "leaf_label": "Chợ",
            "mo_ta": caption,
            "download_status": "success",
        }
        payloads.setdefault(iid, {"records": []})["records"].append(row)
    index = {
        "config": {"model": "m", "revision": "r", "preprocessing": "p", "libraries": {}},
        "processor_sha256": "processor",
        "shape": [3, 2],
    }
    client = QdrantClient(":memory:")
    image_store = SimpleNamespace(client=client, collection="images", payloads=payloads)
    build_text_index(FakeEncoder(image_store, index))
    yield image_store, index
    client.close()


def test_documents_use_only_name_and_caption_of_one_record(built):
    assert [r["text"] for r in text_documents(built[0].payloads)] == list(VECTORS)


def test_image_score_is_its_best_record_and_images_are_not_repeated(built):
    store, _ = load_text_store(*built)
    results = store.search(np.array([1, 0]), 2)
    assert [r["image_id"] for r in results] == ["a", "b"]
    assert results[0]["score"] == pytest.approx(1)
    assert [r["image_id"] for r in store.search(np.array([0, 1]), 3)] == ["a", "b", "c"]


def test_scope_ignores_captions_of_other_places(built):
    store, _ = load_text_store(*built)
    # Ảnh a khớp nhờ record của A nhưng phạm vi B chỉ được dùng record của B.
    results = store.search(np.array([1, 0]), 2, entity_ids={"B"})
    assert [r["image_id"] for r in results] == ["b", "a"]
    assert results[1]["score"] == pytest.approx(0)
    assert [r["image_id"] for r in store.search(np.array([1, 0]), 2, {"b"}, {"B"})] == ["b"]
    assert store.search(np.array([1, 0]), 2, set(), {"B"}) == []
    assert store.search(np.array([1, 0]), 2, entity_ids=set()) == []


def test_rebuild_is_repeatable_and_changed_captions_are_refused(built):
    image_store, index = built
    build_text_index(FakeEncoder(image_store, index))
    assert image_store.client.count("images_text").count == len(RECORDS)
    image_store.payloads["c"]["records"][0]["mo_ta"] = "cổng đỏ"
    with pytest.raises(ValueError, match="--sync-text"):
        load_text_store(image_store, index)


def test_points_of_an_older_index_do_not_reach_results(built):
    image_store, index = built
    VECTORS["Chợ C. mái vòm"] = [0.6, 0.8]
    try:
        image_store.payloads["c"]["records"][0]["mo_ta"] = "mái vòm"
        build_text_index(FakeEncoder(image_store, index))
    finally:
        del VECTORS["Chợ C. mái vòm"]
    store, _ = load_text_store(image_store, index)
    scores = {r["image_id"]: r["score"] for r in store.search(np.array([0, 1]), 3)}
    assert scores["c"] == pytest.approx(0.8)


def test_missing_text_collection_is_not_hidden():
    client = QdrantClient(":memory:")
    image_store = SimpleNamespace(client=client, collection="images", payloads={})
    index = {
        "config": {"model": "m", "revision": "r", "preprocessing": "p", "libraries": {}},
        "processor_sha256": "processor",
        "shape": [0, 2],
    }
    with pytest.raises(ValueError, match="Thiếu metadata"):
        load_text_store(image_store, index)
    client.close()


@pytest.mark.parametrize("vectors", [[], [[1, 0, 0]], [[float("nan"), 0]], [[2, 0]]])
def test_invalid_vectors_are_rejected_before_creating_collection(vectors):
    with closing(QdrantClient(":memory:")) as client:
        store = QdrantTextVectors(client, "texts", "index", 2)
        with pytest.raises(ValueError, match="Vector text"):
            store.upload(
                [{"record_id": "r", "image_id": "a", "entity_id": "A"}],
                np.array(vectors),
            )
        assert not client.collection_exists("texts")


def test_duplicate_record_ids_are_rejected_before_upload():
    with closing(QdrantClient(":memory:")) as client:
        store = QdrantTextVectors(client, "texts", "index", 2)
        documents = [{"record_id": "r", "image_id": iid, "entity_id": "A"} for iid in ("a", "b")]
        with pytest.raises(ValueError, match="Record ID"):
            store.upload(documents, np.array([[1, 0], [0, 1]]))
        assert not client.collection_exists("texts")


def test_duplicate_images_do_not_consume_the_candidate_limit():
    with closing(QdrantClient(":memory:")) as client:
        store = QdrantTextVectors(client, "texts", "index", 2)
        documents = [
            {"record_id": str(n), "image_id": iid, "entity_id": "A"}
            for n, iid in enumerate(("a", "a", "a", "b", "c"))
        ]
        store.upload(documents, np.array([[1, 0]] * 3 + [[0.8, 0.6], [0, 1]]))
        results = store.search(np.array([1, 0]), 2)
        assert [r["image_id"] for r in results] == ["a", "b"]


def test_text_branch_votes_only_in_hybrid(built):
    image_store, _ = built
    text_store, _ = load_text_store(*built)
    rows = [r for p in image_store.payloads.values() for r in p["records"]]
    ids = ["a", "b", "c"]
    images = QdrantVectors(image_store.client, "images", "index", 2)
    catalog = SimpleNamespace(image_entities={i: {i.upper()} for i in ids})
    images.upload(ids, np.array([[0, 1], [0, 1], [1, 0]], np.float32), catalog, "m", "r")
    keyword = prepare_bm25(build_documents(rows, ids), 1.2, 0.75)
    settings = RetrievalSettings(_env_file=None)

    def run(method, store):
        engine = RetrievalEngine(ids, images, keyword, None, settings, None, store)
        return engine.search("bãi xe", np.array([1, 0]), method, 3)

    without = {r["image_id"]: r["score"] for r in run("hybrid", None)}
    ranks = {"a": 1, "b": 2, "c": 3}
    for row in run("hybrid", text_store):
        expected = without[row["image_id"]] + 1 / (settings.rrf_k + ranks[row["image_id"]])
        assert row["score"] == pytest.approx(expected)
    for method in ("vector", "keyword"):
        assert run(method, text_store) == run(method, None)
