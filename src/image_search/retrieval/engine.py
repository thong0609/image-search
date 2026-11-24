"""Tìm ứng viên trong đúng phạm vi trước top-K; bridge chỉ là giả thuyết có nguồn."""

import numpy as np

from image_search.baseline.keyword import fuse_rankings, keyword_search
from image_search.retrieval.executor import PlanExecutor


class RetrievalEngine:
    def __init__(self, image_ids, vector_store, keyword_index, catalog, settings):
        if len(image_ids) != len(set(image_ids)):
            raise ValueError("Image index bị trùng")
        self.image_ids = image_ids
        self.vector_store = vector_store
        self.keyword = keyword_index
        self.catalog = catalog
        self.settings = settings

    def search(self, text, vector, method, limit, allowed=None, excluded=None):
        if method not in ("vector", "keyword", "hybrid"):
            raise ValueError("Phương pháp không hợp lệ")
        eligible = set(self.image_ids) if allowed is None else set(allowed)
        eligible.difference_update(excluded or ())
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
            dense = self.vector_store.search(vector, count, eligible)
        if method != "vector":
            # Dùng IDF toàn corpus; lọc trước cắt K để không mất ảnh đúng phạm vi entity.
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
