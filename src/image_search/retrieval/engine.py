"""Tìm ứng viên trong đúng phạm vi trước top-K; bridge chỉ là giả thuyết có nguồn."""

import numpy as np

from image_search.baseline.keyword import fuse_rankings, keyword_search
from image_search.baseline.vectors import rank_images
from image_search.retrieval.executor import PlanExecutor


class RetrievalEngine:
    def __init__(self, image_ids, image_vectors, keyword_index, catalog, settings):
        if len(image_ids) != len(set(image_ids)) or len(image_ids) != len(image_vectors):
            raise ValueError("Image index bị trùng hoặc sai số hàng")
        self.image_ids = image_ids
        self.image_vectors = image_vectors
        self.positions = {iid: i for i, iid in enumerate(image_ids)}
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
                or vector.shape != (self.image_vectors.shape[1],)
                or not np.isfinite(vector).all()
                or not np.isclose(np.linalg.norm(vector), 1, atol=1e-5)
            ):
                raise ValueError("Thiếu vector chuẩn hóa hoặc sai số chiều")
            positions = [i for i, iid in enumerate(self.image_ids) if iid in eligible]
            ids = [self.image_ids[i] for i in positions]
            dense = rank_images(vector, self.image_vectors[positions], ids, count)
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
