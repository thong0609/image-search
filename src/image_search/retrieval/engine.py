"""Tìm trong phạm vi graph và Qdrant trước top-K, gộp RRF chuẩn 1:1."""

import numpy as np

from image_search.retrieval.executor import PlanExecutor
from image_search.retrieval.keyword import fuse_rankings, keyword_search


class RetrievalEngine:
    def __init__(self, image_ids, vector_store, keyword_index, catalog, settings, graph_store):
        if len(image_ids) != len(set(image_ids)):
            raise ValueError("Image index bị trùng")
        self.image_ids = image_ids
        self.vector_store = vector_store
        self.keyword = keyword_index
        self.catalog = catalog
        self.settings = settings
        self.graph_store = graph_store

    def search(self, text, vector, method, limit, entity_ids=None):
        """entity_ids=None: toàn kho; tập rỗng: không có phạm vi hợp lệ."""
        if method not in ("vector", "keyword", "hybrid"):
            raise ValueError("Phương pháp không hợp lệ")
        eligible = None
        if entity_ids is not None:
            eligible = self.graph_store.images_for(entity_ids) if entity_ids else set()
            if not eligible:
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
            dense = self.vector_store.search(vector, count, eligible, entity_ids)
        if method != "vector":
            sparse = keyword_search(text, self.keyword, len(self.image_ids))
            # Qdrant xác định tập ảnh hợp lệ; BM25 giữ IDF toàn corpus, lọc trước top-K.
            if eligible is not None:
                allowed = self.vector_store.filtered_ids(eligible, entity_ids)
                sparse = [r for r in sparse if r["image_id"] in allowed]
            sparse = sparse[:count]
        if method == "hybrid":
            return fuse_rankings(dense, sparse, limit, self.settings.rrf_k)
        return (sparse if method == "keyword" else dense)[:limit]

    def execute(self, plan, method="hybrid", vectors=None):
        return PlanExecutor(self).execute(plan, method, vectors)
