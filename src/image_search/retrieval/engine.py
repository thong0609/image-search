"""Tìm ứng viên trong đúng phạm vi trước top-K; bridge chỉ là giả thuyết có nguồn."""

from collections import defaultdict

import numpy as np

from image_search.baseline.keyword import fuse_rankings, keyword_search
from image_search.baseline.vectors import rank_images
from image_search.planner.schemas import QueryPlan


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
        plan = QueryPlan.model_validate(plan)
        if plan.needs_clarification:
            return {
                "status": "needs_clarification",
                "question": plan.clarification_question,
                "groups": [],
                "trace": [],
            }
        if method not in ("vector", "keyword", "hybrid"):
            raise ValueError("Phương pháp không hợp lệ")
        if method != "keyword" and set(vectors or {}) != {s.id for s in plan.steps}:
            raise ValueError("Vector không khớp toàn bộ step ID của kế hoạch")
        states, groups, trace = {}, [], []
        for step in plan.steps:
            parents = [states[parent] for parent in step.depends_on]
            scope = None
            if parents:
                scope = set.intersection(*(set(p["entities"]) for p in parents))
            reason = None
            if step.entity_mention is not None:
                named = self.catalog.resolve(step.entity_mention)
                scope = named if scope is None else scope & named
                if not scope:
                    reason = "entity_not_found" if not named else "entity_scope_conflict"
            if parents and not scope:
                reason = reason or "dependency_unresolved"
            allowed = None if scope is None else self.catalog.images_for(scope)
            excluded = set().union(*(p["used_images"] for p in parents)) if parents else set()
            limit = (
                self.settings.bridge_candidates
                if step.action == "resolve_entity"
                else max(self.settings.top_k, step.count or self.settings.default_count)
            )
            found = self.search(
                step.search_text,
                (vectors or {}).get(step.id),
                method,
                limit,
                allowed=allowed,
                excluded=excluded,
            )
            if step.action == "resolve_entity":
                entities = defaultdict(list)
                rejected = []
                for row in found:
                    iid = row["image_id"]
                    eid = self.catalog.bridge_entity(iid)
                    if eid is None:
                        rejected.append(iid)
                        continue
                    if scope is not None and eid not in scope:
                        continue
                    if eid not in entities and len(entities) >= self.settings.bridge_entities:
                        continue
                    if eid not in entities:
                        entities[eid].append(
                            iid
                        )  # Một bridge đại diện tốt nhất mỗi entity ứng viên.
                states[step.id] = {
                    "entities": dict(entities),
                    "used_images": excluded | {i for ids in entities.values() for i in ids},
                }
                trace.append(
                    {
                        "step_id": step.id,
                        "action": step.action,
                        "depends_on": step.depends_on,
                        "bridge_candidates": [
                            {
                                **r,
                                "record_ids": [
                                    x["record_id"] for x in self.catalog.records[r["image_id"]]
                                ],
                            }
                            for r in found
                        ],
                        "status": reason or ("entity_hypotheses" if entities else "no_candidates"),
                        "entity_hypotheses": dict(entities),
                        "rejected_bridge_images": rejected,
                        "evidence_level": "retrieval_candidates_not_verified_identity",
                    }
                )
                continue
            candidates = []
            for row in found:
                iid = row["image_id"]
                eids = self.catalog.image_entities[iid]
                supporting = sorted(
                    {
                        bridge
                        for p in parents
                        for eid, ids in p["entities"].items()
                        if eid in eids
                        for bridge in ids
                    }
                )
                candidates.append(
                    {
                        **row,
                        "entity_ids": sorted(eids),
                        "bridge_image_ids": supporting,
                        "record_ids": [r["record_id"] for r in self.catalog.records[iid]],
                        "metadata_ambiguous": len(eids) != 1 or iid in self.catalog.uncertain,
                    }
                )
            count = step.count or self.settings.default_count
            status = reason or (
                "no_candidates"
                if not candidates
                else "insufficient_candidates"
                if step.count is not None and len(candidates) < step.count
                else "candidates"
            )
            groups.append(
                {
                    "target_id": step.target_id,
                    "step_id": step.id,
                    "search_text": step.search_text,
                    "requested_count": step.count,
                    "selection_limit": count,
                    "status": status,
                    "entity_scope": sorted(scope) if scope is not None else None,
                    "entity_hypotheses_unverified": bool(parents),
                    "results": candidates[:count],
                    "candidates": candidates,
                }
            )
            states[step.id] = {"entities": {}, "used_images": excluded}
        return {
            "status": "candidate_results",
            "groups": groups,
            "trace": trace,
            "limitations": [
                "Scores không phải xác suất; chưa rerank hoặc xác minh điều kiện thị giác.",
                "Multi-hop truyền giả thuyết entity từ bridge; chưa phải graph facts đã duyệt.",
            ],
        }
