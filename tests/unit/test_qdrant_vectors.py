from types import SimpleNamespace

import numpy as np
import pytest
from qdrant_client import QdrantClient, models

from image_search.adapters.qdrant.vectors import QdrantVectors, point_id


@pytest.mark.filterwarnings("ignore:Payload indexes:UserWarning")
@pytest.mark.filterwarnings("ignore:Local mode performs exact:UserWarning")
def test_import_retry_filter_and_source_validation():
    client = QdrantClient(":memory:")
    store = QdrantVectors(client, "images", "source-v1", 2)
    ids = ["a", "b", "c"]
    vectors = np.array([[1, 0], [0.8, 0.6], [0, 1]], dtype=np.float32)
    catalog = SimpleNamespace(image_entities={iid: {"entity"} for iid in ids})
    # Qdrant local ignores payload indexes; they matter only on the real server.
    assert store.upload(ids, vectors, catalog, "model", "revision") == 3
    assert store.upload(ids, vectors, catalog, "model", "revision") == 3
    result = store.search(vectors[0], 1, {"b", "c"})
    assert result[0]["image_id"] == "b"
    assert result[0]["score"] == pytest.approx(0.8)
    assert store.search(vectors[0], 1, set()) == []
    with pytest.raises(ValueError, match="thiếu ảnh"):
        store.validate([*ids, "d"])
    with pytest.raises(ValueError, match="không khớp"):
        QdrantVectors(client, "images", "other-source", 2).validate(ids)
    client.set_payload("images", {"image_id": "wrong"}, [point_id("a")])
    with pytest.raises(ValueError, match="không khớp"):
        store.validate(ids)
    client.close()


def test_reject_wrong_dimension_without_overwriting_collection():
    client = QdrantClient(":memory:")
    client.create_collection(
        "images", vectors_config=models.VectorParams(size=3, distance=models.Distance.COSINE)
    )
    with pytest.raises(ValueError, match="số chiều"):
        QdrantVectors(client, "images", "source", 2).validate([])
    assert client.get_collection("images").config.params.vectors.size == 3
    client.close()


def test_index_metadata_is_stored_in_qdrant():
    from image_search.adapters.qdrant.vectors import read_metadata, save_metadata

    client = QdrantClient(":memory:")
    with pytest.raises(ValueError, match="Thiếu metadata"):
        read_metadata(client, "images")
    index = {
        "config": {"model": "test", "revision": "abc"},
        "image_ids": ["a"],
        "shape": [1, 2],
        "processor_sha256": "processor",
    }
    save_metadata(client, "images", index)
    assert read_metadata(client, "images") == index
    client.close()
