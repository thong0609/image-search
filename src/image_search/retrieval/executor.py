"""Thực thi điều kiện graph trước retrieval; không suy bridge từ top ảnh."""

from image_search.adapters.qdrant.metadata import name_key
from image_search.modules.graph.query import GraphQuery
from image_search.planner.schemas import QueryPlan
from image_search.retrieval.evidence import inspect_evidence, metadata_supported


def direct_steps(plan):
    # Giữ tên hàm để tương thích caller cũ; gồm cả retrieval sau graph resolve.
    supported, result = set(), []
    for step in plan.steps:
        parents_ok = all(parent in supported for parent in step.depends_on)
        if step.action == "resolve_entity":
            if parents_ok and step.graph is not None and not step.conditions:
                supported.add(step.id)
        elif parents_ok:
            result.append(step)
    return result


class PlanExecutor:
    def __init__(self, engine):
        self.engine = engine
        self.catalog = engine.catalog
        self.settings = engine.settings

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

    def retrieve_graph(self, step, entity_ids, vector, method):
        source_ids = self.engine.graph_store.source_ids(entity_ids)
        count = step.count or self.settings.default_count
        found = self.engine.search(
            step.search_text, vector, method, max(self.settings.top_k, count), entity_ids=source_ids
        )
        selected = found[:count]
        status = "candidates" if selected else "no_candidates"
        if step.count is not None and len(selected) < count:
            status = "insufficient_candidates"
        group = self.empty_group(step, status)
        group.update(
            entity_scope=sorted(source_ids),
            graph_entity_ids=sorted(entity_ids),
            candidates=found,
            results=selected,
            entity_hypotheses_unverified=False,
            count_status="not_requested"
            if step.count is None
            else "satisfied"
            if len(selected) >= count
            else "insufficient_candidates",
            verification_status="trusted_metadata_scope",
            hypotheses=[
                {
                    "entity_id": None,
                    "bridge_paths": [],
                    "candidates": found,
                    "results": selected,
                    "count_status": "not_requested",
                }
            ],
        )
        # Quan hệ đã lọc bằng graph; điều kiện thị giác còn do retrieval xếp hạng.
        group["image_conditions"] = step.conditions
        return group

    def empty_group(self, step, status):
        return {
            "target_id": step.target_id,
            "step_id": step.id,
            "search_text": step.search_text,
            "requested_count": step.count,
            "selection_limit": step.count or self.settings.default_count,
            "status": status,
            "entity_scope": None,
            "entity_hypotheses_unverified": False,
            "hypotheses": [],
            "candidates": [],
            "results": [],
            "count_status": "unresolved",
            "verification_status": status,
            "visual_verification": "not_performed",
        }

    def named_scope(self, mention):
        graph = self.engine.graph_store
        query = GraphQuery(
            target_name=mention, target_kind=None, target_category=None, match="all", conditions=[]
        )
        selection = graph.select(query, {})
        if selection["status"] == "ambiguous_entity":
            return selection
        ids = set(selection["entity_ids"])
        for alias, sources in self.catalog.aliases.items():
            if name_key(alias) == name_key(mention):
                ids.update(graph.canonical_ids(sources))
        status = "ambiguous_entity" if len(ids) > 1 else "resolved" if ids else "no_graph_match"
        return {"status": status, "entity_ids": sorted(ids) if status == "resolved" else []}

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
        if method != "keyword" and set(vectors or {}) != {s.id for s in direct_steps(plan)}:
            raise ValueError("Vector không khớp step ID được hỗ trợ của kế hoạch")
        groups, trace, resolved, states = [], [], {}, {}
        graph = self.engine.graph_store
        for step in plan.steps:
            failed = next(
                (
                    states.get(p, "unsupported_graph_relation")
                    for p in step.depends_on
                    if states.get(p) != "resolved"
                ),
                None,
            )
            selection = None
            if failed:
                selection = {"status": failed, "entity_ids": []}
            elif step.action == "resolve_entity" and (step.graph is None or step.conditions):
                selection = {"status": "unsupported_graph_relation", "entity_ids": []}
            elif step.graph is not None:
                selection = (
                    graph.select(step.graph, resolved)
                    if graph
                    else {"status": "unsupported_graph_relation", "entity_ids": []}
                )
            elif step.depends_on:
                ids = set.intersection(*(resolved[p] for p in step.depends_on))
                selection = {
                    "status": "resolved" if ids else "no_graph_match",
                    "entity_ids": sorted(ids),
                }
            elif step.entity_mention and graph is not None:
                selection = self.named_scope(step.entity_mention)
            if (
                selection is not None
                and selection["status"] == "resolved"
                and step.graph is not None
                and step.entity_mention
            ):
                named = self.named_scope(step.entity_mention)
                ids = set(selection["entity_ids"]) & set(named["entity_ids"])
                selection = {
                    "status": named["status"]
                    if named["status"] != "resolved"
                    else "resolved"
                    if ids
                    else "no_graph_match",
                    "entity_ids": sorted(ids),
                }
            if step.action == "resolve_entity":
                resolved[step.id] = set(selection["entity_ids"])
                states[step.id] = selection["status"]
                trace.append(
                    {
                        "step_id": step.id,
                        **selection,
                        "graph": step.graph.model_dump() if step.graph else None,
                    }
                )
                continue
            if selection is not None:
                if selection["status"] != "resolved":
                    group = self.empty_group(step, selection["status"])
                else:
                    group = self.retrieve_graph(
                        step, set(selection["entity_ids"]), (vectors or {}).get(step.id), method
                    )
            else:
                scope = None
                if step.entity_mention is not None:
                    scope = {eid: [[]] for eid in sorted(self.catalog.resolve(step.entity_mention))}
                group = self.retrieve(step, scope, (vectors or {}).get(step.id), method)
                if scope == {}:
                    group["status"] = "entity_not_found"
            groups.append(group)
        blocked = [g for g in groups if not g["results"]]
        unsupported = all(g["status"] == "unsupported_graph_relation" for g in groups)
        return {
            "status": "unsupported_graph_relation"
            if unsupported
            else "unresolved"
            if len(blocked) == len(groups)
            else "partial_results"
            if blocked
            else "candidate_results",
            "groups": groups,
            "trace": trace,
            "limitations": [
                "Chỉ hỗ trợ LOCATED_IN/PART_OF/BRANCH_OF có trong metadata.",
                "Nhận diện entity bằng đặc điểm thị giác qua ảnh khác chưa hỗ trợ.",
                "Điều kiện ảnh được xếp hạng bằng RRF; chưa rerank.",
            ],
        }
