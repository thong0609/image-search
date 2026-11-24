"""Tìm trong phạm vi graph nguồn và Qdrant trước top-K, gộp RRF chuẩn 1:1."""

import numpy as np

from image_search.baseline.keyword import fuse_rankings, keyword_search
from image_search.retrieval.executor import PlanExecutor


class RetrievalEngine:
    def __init__(self, image_ids, vector_store, keyword_index, catalog, settings, graph_store=None):
        self.graph_store = graph_store
        if len(image_ids) != len(set(image_ids)):
            raise ValueError("Image index bị trùng")
        self.image_ids = image_ids
        self.vector_store = vector_store
        self.keyword = keyword_index
        self.catalog = catalog
        self.settings = settings

    def search(self, text, vector, method, limit, allowed=None, excluded=None, entity_ids=None):
        if method not in ("vector", "keyword", "hybrid"):
            raise ValueError("Phương pháp không hợp lệ")
        if self.graph_store is not None and entity_ids is not None:
            graph_ids = self.graph_store.images_for(entity_ids)
            allowed = graph_ids if allowed is None else set(allowed) & graph_ids
        if allowed is not None and not allowed or entity_ids is not None and not entity_ids:
            return []
        dense, sparse = [], []
        count = max(limit, self.settings.candidates) if method == "hybrid" else limit
        if method != "keyword":
            if (
                vector is None
                or vector.shape != (self.vector_store.dimensions,)
                or not np.isfinite(vector).all()
                or not np.isclose(np.linalg.norm(vector), 1, atol=1e-5)
            ):
                raise ValueError("Thiếu vector chuẩn hóa hoặc sai số chiều")
            dense = self.vector_store.search(vector, count, allowed, entity_ids, excluded)
        if method != "vector":
            # Qdrant xác định tập ảnh hợp lệ; BM25 giữ IDF toàn corpus, lọc trước top-K.
            eligible = {
                p["image_id"]
                for p in self.vector_store.filtered_payloads(
                    allowed, entity_ids, excluded, fields=["image_id"]
                )
            }
            sparse = [
                r
                for r in keyword_search(text, self.keyword, len(self.image_ids))
                if r["image_id"] in eligible
            ][:count]
        if method == "hybrid":
            return fuse_rankings(dense, sparse, limit, self.settings.rrf_k)
        return (sparse if method == "keyword" else dense)[:limit]

    def execute(self, plan, method="hybrid", vectors=None):
        return PlanExecutor(self).execute(plan, method, vectors)
