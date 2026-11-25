"""Vector tên + mô tả của từng record trong Qdrant; tách collection với vector ảnh."""

from uuid import NAMESPACE_URL, uuid5

import numpy as np
from qdrant_client import models


def text_collection(collection):
    return collection + "_text"


class QdrantTextVectors:
    def __init__(self, client, collection, index_hash, dimensions):
        self.client = client
        self.collection = collection
        self.index_hash = index_hash
        self.dimensions = dimensions
        # Số point tối đa phải lấy thêm để đủ ảnh khác nhau (một ảnh có thể nhiều record).
        self.extra = 0

    def query_filter(self, eligible=None, entity_ids=None):
        must = [
            models.FieldCondition(
                key="text_index_sha256", match=models.MatchValue(value=self.index_hash)
            )
        ]
        for key, values in (("image_id", eligible), ("entity_id", entity_ids)):
            if values is not None:
                must.append(
                    models.FieldCondition(key=key, match=models.MatchAny(any=sorted(values)))
                )
        return models.Filter(must=must)

    def upload(self, documents, vectors):
        if len({row["record_id"] for row in documents}) != len(documents):
            raise ValueError("Record ID của vector text bị trùng")
        if (
            vectors.shape != (len(documents), self.dimensions)
            or not np.isfinite(vectors).all()
            or not np.allclose(np.linalg.norm(vectors, axis=1), 1, atol=1e-5)
        ):
            raise ValueError("Vector text thiếu, sai số chiều hoặc chưa chuẩn hóa")
        if not self.client.collection_exists(self.collection):
            self.client.create_collection(
                self.collection,
                vectors_config=models.VectorParams(
                    size=self.dimensions, distance=models.Distance.COSINE
                ),
            )
        self.validate_config()
        for field in ("image_id", "entity_id", "text_index_sha256"):
            self.client.create_payload_index(
                self.collection, field, models.PayloadSchemaType.KEYWORD, wait=True
            )
        for start in range(0, len(documents), 64):
            # Point ID gắn với index: bản cũ không bị ghi đè và không lọt vào kết quả.
            points = [
                models.PointStruct(
                    id=str(uuid5(NAMESPACE_URL, f"{self.index_hash}:{row['record_id']}")),
                    vector=vector.tolist(),
                    payload={
                        "record_id": row["record_id"],
                        "image_id": row["image_id"],
                        "entity_id": row["entity_id"],
                        "text_index_sha256": self.index_hash,
                    },
                )
                for row, vector in zip(
                    documents[start : start + 64], vectors[start : start + 64], strict=True
                )
            ]
            self.client.upsert(self.collection, points, wait=True)
        self.validate(documents)

    def validate_config(self):
        config = self.client.get_collection(self.collection).config.params.vectors
        if not isinstance(config, models.VectorParams) or (
            config.size != self.dimensions or config.distance != models.Distance.COSINE
        ):
            raise ValueError("Collection text Qdrant sai số chiều hoặc distance")

    def validate(self, documents):
        self.validate_config()
        seen, offset = set(), None
        while True:
            points, offset = self.client.scroll(
                self.collection,
                limit=256,
                offset=offset,
                scroll_filter=self.query_filter(),
                with_payload=True,
                with_vectors=False,
            )
            seen.update(
                tuple(p.payload[k] for k in ("record_id", "image_id", "entity_id")) for p in points
            )
            if offset is None:
                break
        expected = {(r["record_id"], r["image_id"], r["entity_id"]) for r in documents}
        if seen != expected or len(expected) != len(documents):
            raise ValueError(
                "Vector text không khớp metadata; chạy image-search-qdrant --sync-text"
            )
        self.extra = len(documents) - len({r["image_id"] for r in documents})

    def search(self, vector, limit, eligible=None, entity_ids=None):
        """Điểm mỗi ảnh là record khớp nhất; trong phạm vi chỉ tính record của nơi đó."""
        if eligible is not None and not eligible or entity_ids is not None and not entity_ids:
            return []
        response = self.client.query_points(
            self.collection,
            query=vector.tolist(),
            limit=limit + self.extra,
            query_filter=self.query_filter(eligible, entity_ids),
            search_params=models.SearchParams(exact=True),
            with_payload=["image_id"],
            with_vectors=False,
        )
        best = {}
        for point in response.points:
            iid = point.payload["image_id"]
            best[iid] = max(point.score, best.get(iid, point.score))
        order = sorted(best, key=lambda iid: (-best[iid], iid))
        return [{"image_id": iid, "score": best[iid]} for iid in order[:limit]]
