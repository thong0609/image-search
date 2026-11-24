"""Ghép các bước theo entity/path; không cộng ảnh của nhiều giả thuyết để đủ count."""

from itertools import islice, product
from math import prod

from image_search.planner.schemas import QueryPlan
from image_search.retrieval.evidence import inspect_evidence, metadata_supported


def join_paths(parents, limit, combination_limit=64):
    if not parents:
        return None, False
    common = set.intersection(*(set(p) for p in parents))
    joined, truncated = {}, False
    for eid in sorted(common):
        paths = []
        total = prod(len(p[eid]) for p in parents)
        truncated = truncated or total > combination_limit
        for combination in islice(product(*(p[eid] for p in parents)), combination_limit):
            steps, conflict = {}, False
            for path in combination:
                for evidence in path:
                    sid = evidence["step_id"]
                    if sid in steps and steps[sid]["image_id"] != evidence["image_id"]:
                        conflict = True
                    steps[sid] = evidence
            if not conflict:
                merged = list(steps.values())
                if merged not in paths:
                    paths.append(merged)
            if len(paths) >= limit:
                break
        if paths:
            joined[eid] = paths
    return joined, truncated


class PlanExecutor:
    def __init__(self, engine):
        self.engine = engine
        self.catalog = engine.catalog
        self.settings = engine.settings

    def resolve(self, step, scope, vector, method):
        search = self.engine.search
        entity_ids = None if scope is None else set(scope)
        found = search(
            step.search_text, vector, method, self.settings.bridge_candidates, entity_ids=entity_ids
        )
        options, rejected = {}, []
        for row in found:
            iid = row["image_id"]
            eid = self.catalog.bridge_entity(iid)
            if eid is None or (scope is not None and eid not in scope):
                rejected.append({**row, "reason": "identity_unverified_or_conflicting"})
                continue
            evidence = {
                "step_id": step.id,
                **inspect_evidence(self.catalog, iid, eid, step.conditions),
            }
            for parent_path in [[]] if scope is None else scope[eid]:
                if iid in {e["image_id"] for e in parent_path}:
                    continue
                options.setdefault(eid, []).append(parent_path + [evidence])
        # Metadata support chỉ chọn đường chứng cứ trong cùng entity.
        # Không thay score của retriever.
        paths = {}
        for eid, candidates in options.items():
            candidates.sort(key=lambda p: not all(metadata_supported(e) for e in p))
            paths[eid] = candidates[: self.settings.paths_per_entity]
            if len(paths) >= self.settings.bridge_entities:
                break
        return paths, found, rejected

    def retrieve(self, step, scope, vector, method):
        hypotheses = []
        count = step.count or self.settings.default_count
        for eid in [None] if scope is None else scope:
            paths = [[]] if scope is None else scope[eid]
            combined, rejected = {}, {}
            for path in paths:
                bridges = {e["image_id"] for e in path}
                found = self.engine.search(
                    step.search_text,
                    vector,
                    method,
                    max(self.settings.top_k, count),
                    entity_ids=None if eid is None else {eid},
                    excluded=bridges,
                )
                for row in found:
                    iid = row["image_id"]
                    evidence = inspect_evidence(self.catalog, iid, eid, step.conditions)
                    if eid is not None and evidence["identity_status"] != "supported_by_metadata":
                        rejected[iid] = {**row, "evidence": evidence}
                        continue
                    route = {
                        "bridge_steps": path,
                        "target_evidence": evidence,
                        "metadata_supported": all(metadata_supported(e) for e in path)
                        and metadata_supported(evidence),
                    }
                    if iid not in combined:
                        combined[iid] = {
                            **row,
                            "entity_ids": sorted(self.catalog.image_entities[iid]),
                            "record_ids": [r["record_id"] for r in self.catalog.records[iid]],
                            "bridge_image_ids": [],
                            "evidence_paths": [],
                            "metadata_ambiguous": evidence["identity_status"]
                            != "supported_by_metadata",
                        }
                    result = combined[iid]
                    result["score"] = max(result["score"], row["score"])
                    result["bridge_image_ids"] = sorted(set(result["bridge_image_ids"]) | bridges)
                    if route not in result["evidence_paths"]:
                        result["evidence_paths"].append(route)
            candidates = sorted(combined.values(), key=lambda r: (-r["score"], r["image_id"]))
            candidates = candidates[: max(self.settings.top_k, count)]
            selected = candidates[:count]
            verified = sum(
                any(p["metadata_supported"] for p in r["evidence_paths"]) for r in selected
            )
            cardinality = (
                "not_requested"
                if step.count is None
                else "insufficient_candidates"
                if len(selected) < count
                else "supported_by_metadata"
                if verified >= count
                else "unverified"
            )
            hypotheses.append(
                {
                    "entity_id": eid,
                    "bridge_paths": paths,
                    "candidates": candidates,
                    "results": selected,
                    "count_status": cardinality,
                    "metadata_supported_count": verified,
                    "rejected_candidates": list(rejected.values()),
                }
            )
        # Không tự bỏ giả thuyết chỉ vì caption thiếu điều kiện; thiếu bằng chứng không là nhãn âm.
        viable = [h for h in hypotheses if h["candidates"]]
        ambiguous = len(hypotheses) > 1
        chosen = hypotheses[0] if len(hypotheses) == 1 else None
        results = chosen["results"] if chosen else []
        candidates = [r for h in hypotheses for r in h["candidates"]]
        status = (
            "ambiguous_entity"
            if ambiguous
            else "no_candidates"
            if not viable
            else "insufficient_candidates"
            if step.count is not None and len(results) < count
            else "candidates"
        )
        return {
            "target_id": step.target_id,
            "step_id": step.id,
            "search_text": step.search_text,
            "requested_count": step.count,
            "selection_limit": count,
            "status": status,
            "entity_scope": sorted(scope) if scope is not None else None,
            "entity_hypotheses_unverified": bool(step.depends_on),
            "hypotheses": hypotheses,
            "candidates": candidates,
            "results": results,
            "count_status": "unresolved_entity"
            if ambiguous
            else chosen["count_status"]
            if chosen
            else "insufficient_candidates",
            "verification_status": "needs_entity_resolution"
            if ambiguous
            else "supported_by_metadata"
            if results
            and all(any(p["metadata_supported"] for p in r["evidence_paths"]) for r in results)
            else "unverified",
            "visual_verification": "not_performed",
        }

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
            scope, join_truncated = join_paths(
                [states[p] for p in step.depends_on],
                self.settings.paths_per_entity,
                self.settings.path_combination_limit,
            )
            reason = None
            if step.entity_mention is not None:
                named = self.catalog.resolve(step.entity_mention)
                scope = (
                    {eid: [[]] for eid in sorted(named)}
                    if scope is None
                    else {eid: paths for eid, paths in scope.items() if eid in named}
                )
                if not scope:
                    reason = "entity_not_found" if not named else "entity_scope_conflict"
            if step.depends_on and not scope:
                reason = reason or (
                    "path_budget_exceeded" if join_truncated else "dependency_unresolved"
                )
            vector = (vectors or {}).get(step.id)
            if step.action == "resolve_entity":
                paths, found, rejected = self.resolve(step, scope, vector, method)
                states[step.id] = paths
                trace.append(
                    {
                        "step_id": step.id,
                        "action": step.action,
                        "depends_on": step.depends_on,
                        "path_join_truncated": join_truncated,
                        "status": reason or ("entity_hypotheses" if paths else "no_candidates"),
                        "bridge_candidates": found,
                        "entity_hypotheses": {
                            eid: sorted({p[-1]["image_id"] for p in chains})
                            for eid, chains in paths.items()
                        },
                        "evidence_paths": paths,
                        "rejected_bridge_images": [r["image_id"] for r in rejected],
                        "rejected_evidence": rejected,
                    }
                )
            else:
                group = self.retrieve(step, scope, vector, method)
                group["path_join_truncated"] = join_truncated
                if reason:
                    group["status"] = reason
                groups.append(group)
                states[step.id] = {}
        blocked = [g for g in groups if not g["results"]]
        return {
            "status": "unresolved"
            if len(blocked) == len(groups)
            else "partial_results"
            if blocked
            else "candidate_results",
            "groups": groups,
            "trace": trace,
            "limitations": [
                "Metadata support không phải xác nhận thị giác.",
                "Ảnh của các entity giả thuyết không được trộn để đáp ứng count.",
                "Chưa rerank hoặc thực thi graph facts ngoài liên kết image–entity.",
            ],
        }
