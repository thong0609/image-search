"""Lưu vector SigLIP2 và tìm cosine trong Qdrant."""

from uuid import NAMESPACE_URL, uuid5

import numpy as np
from qdrant_client import models

from image_search.timing import timed


def point_id(image_id):
    return str(uuid5(NAMESPACE_URL, f"image-search:{image_id}"))


class QdrantVectors:
    def __init__(self, client, collection, index_hash, dimensions, metadata_hash=None):
        self.client = client
        self.collection = collection
        self.index_hash = index_hash
        self.dimensions = dimensions
        self.metadata_hash = metadata_hash

    def validate(self, image_ids, vectors=None, allow_partial=False):
        config = self.client.get_collection(self.collection).config.params.vectors
        if not isinstance(config, models.VectorParams) or (
            config.size != self.dimensions or config.distance != models.Distance.COSINE
        ):
            raise ValueError("Collection Qdrant sai số chiều hoặc distance")
        expected = {point_id(iid): i for i, iid in enumerate(image_ids)}
        seen, offset = set(), None
        while True:
            points, offset = self.client.scroll(
                self.collection,
                limit=256,
                offset=offset,
                with_payload=True,
                with_vectors=vectors is not None,
            )
            for point in points:
                payload = point.payload or {}
                if str(point.id) not in expected:
                    raise ValueError("Collection chứa point ngoài image index")
                position = expected[str(point.id)]
                if (
                    payload.get("index_sha256") != self.index_hash
                    or payload.get("image_id") != image_ids[position]
                ):
                    raise ValueError("Collection không khớp image index; hãy dùng collection mới")
                if vectors is not None and not np.allclose(
                    point.vector, vectors[position], atol=1e-6, rtol=1e-5
                ):
                    raise ValueError("Vector Qdrant khác vector nguồn")
                seen.add(str(point.id))
            if offset is None:
                break
        if not allow_partial and seen != set(expected):
            raise ValueError("Collection thiếu ảnh; chạy image-search-qdrant trước")
        return len(seen)

    def upload(self, image_ids, vectors, catalog, model, revision):
        if not self.client.collection_exists(self.collection):
            self.client.create_collection(
                self.collection,
                vectors_config=models.VectorParams(
                    size=self.dimensions, distance=models.Distance.COSINE
                ),
            )
        # Không xóa/ghi đè collection thuộc index khác; cho phép nạp tiếp cùng index.
        self.validate(image_ids, allow_partial=True)
        for field in ("image_id", "entity_ids", "index_sha256"):
            self.client.create_payload_index(
                self.collection, field, models.PayloadSchemaType.KEYWORD, wait=True
            )
        for start in range(0, len(image_ids), 64):
            points = []
            for i in range(start, min(start + 64, len(image_ids))):
                iid = image_ids[i]
                points.append(
                    models.PointStruct(
                        id=point_id(iid),
                        vector=vectors[i].tolist(),
                        payload={
                            "image_id": iid,
                            "entity_ids": sorted(catalog.image_entities[iid]),
                            "index_sha256": self.index_hash,
                            "model": model,
                            "revision": revision,
                        },
                    )
                )
            self.client.upsert(self.collection, points, wait=True)
        return self.validate(image_ids, vectors)

    def query_filter(self, eligible=None, entity_ids=None):
        must = [
            models.FieldCondition(
                key="index_sha256", match=models.MatchValue(value=self.index_hash)
            )
        ]
        if self.metadata_hash:
            must.append(
                models.FieldCondition(
                    key="search_metadata_sha256", match=models.MatchValue(value=self.metadata_hash)
                )
            )
        if eligible is not None:
            must.append(models.HasIdCondition(has_id=[point_id(iid) for iid in sorted(eligible)]))
        if entity_ids is not None:
            must.append(
                models.FieldCondition(
                    key="entity_ids", match=models.MatchAny(any=sorted(entity_ids))
                )
            )
        return models.Filter(must=must)

    @timed("qdrant_filter_ms")
    def filtered_ids(self, eligible=None, entity_ids=None):
        if eligible is not None and not eligible or entity_ids is not None and not entity_ids:
            return set()
        result, offset = set(), None
        while True:
            points, offset = self.client.scroll(
                self.collection,
                limit=256,
                offset=offset,
                scroll_filter=self.query_filter(eligible, entity_ids),
                with_payload=["image_id"],
                with_vectors=False,
            )
            result.update(p.payload["image_id"] for p in points)
            if offset is None:
                return result

    @timed("qdrant_ms")
    def search(self, vector, limit, eligible=None, entity_ids=None):
        if eligible is not None and not eligible or entity_ids is not None and not entity_ids:
            return []
        response = self.client.query_points(
            self.collection,
            query=vector.tolist(),
            limit=limit,
            query_filter=self.query_filter(eligible, entity_ids),
            search_params=models.SearchParams(exact=True),
            with_payload=["image_id"],
            with_vectors=False,
        )
        results = [{"image_id": p.payload["image_id"], "score": p.score} for p in response.points]
        return sorted(results, key=lambda r: (-r["score"], r["image_id"]))

    def vector_for(self, image_id):
        points = self.client.retrieve(self.collection, [point_id(image_id)], with_vectors=True)
        if not points or points[0].payload.get("index_sha256") != self.index_hash:
            raise ValueError("Thiếu vector hoặc index không khớp")
        return np.asarray(points[0].vector, dtype=np.float32)


def save_metadata(client, collection, index):
    name = collection + "_metadata"
    if not client.collection_exists(name):
        client.create_collection(
            name, vectors_config=models.VectorParams(size=1, distance=models.Distance.DOT)
        )
    client.upsert(
        name, [models.PointStruct(id=1, vector=[1.0], payload={"index": index})], wait=True
    )


def read_metadata(client, collection):
    if not client.collection_exists(collection + "_metadata"):
        raise ValueError("Thiếu metadata index trong Qdrant; cần index ảnh trước")
    points = client.retrieve(collection + "_metadata", [1])
    if not points or not points[0].payload.get("index"):
        raise ValueError("Thiếu metadata index trong Qdrant; cần index ảnh trước")
    return points[0].payload["index"]
