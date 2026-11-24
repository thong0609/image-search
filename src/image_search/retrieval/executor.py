"""Thực thi điều kiện graph, nhận diện entity qua ảnh (visual bridge) rồi tìm ảnh đích."""

import re

from image_search.adapters.qdrant.metadata import name_key
from image_search.modules.graph.query import GraphQuery
from image_search.planner.schemas import QueryPlan
from image_search.retrieval.evidence import inspect_evidence, metadata_supported

# Quan hệ không nhìn thấy trong ảnh và không có trong graph; không giả làm đặc điểm thị giác.
UNSUPPORTED_RELATION = re.compile(
    r"^(cùng (thành phố|tỉnh|quận|huyện|phường|xã|tuyến)|cách\s|chủ đầu tư|do .+ (đầu tư|xây))",
    re.IGNORECASE,
)


def visual_bridge(step):
    """Bước nhận diện entity cần nhìn ảnh, có thể kèm phạm vi graph."""
    return (
        step.action == "resolve_entity"
        and (step.graph is None or bool(step.conditions))
        and not any(UNSUPPORTED_RELATION.match(c) for c in step.conditions)
    )


def identity_step(step):
    """Bước nhận diện dự phòng khi tên trong câu không có trong graph."""
    return step.model_copy(update={"id": step.id + ":identity", "search_text": step.identity_text})


def direct_steps(plan):
    # Các bước cần vector: tìm ảnh đích, nhận diện entity qua ảnh và nhận diện dự phòng.
    supported, result = set(), []
    for step in plan.steps:
        parents_ok = all(parent in supported for parent in step.depends_on)
        if not parents_ok:
            continue
        if step.action == "resolve_entity":
            visual = visual_bridge(step)
            if visual:
                result.append(step)
            if visual or (step.graph is not None and not step.conditions):
                supported.add(step.id)
        else:
            result.append(step)
            if step.identity_text:
                result.append(identity_step(step))
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

    def unmatched_anchors(self, query):
        """Tên anchor không có entity nào trong graph."""
        names = [c.anchor_name for c in query.conditions if c.anchor_name] if query else []
        return [n for n in names if not self.engine.graph_store.named(n)]

    def resolve_visual(self, step, resolved, vector, method, unmatched=(), query=None):
        """Tìm ảnh khớp đặc điểm nhận diện, xếp hạng entity theo ảnh điểm cao nhất.

        unmatched: tên graph không có. Tên vẫn nằm trong câu tìm kiếm nhưng không lọc được.
        """
        graph, scope, confirmed = self.engine.graph_store, None, None
        unresolved = {
            "entity_ids": [],
            "method": "visual_bridge",
            "hypotheses": [],
            "unmatched_names": list(unmatched),
        }
        if query is not None and unmatched:
            known = [c for c in query.conditions if c.anchor_name not in unmatched]
            # OR với một vế không kiểm tra được thì không lọc được; AND vẫn lọc phần còn lại.
            usable = query.match == "all" and (known or query.within_step_id)
            query = query.model_copy(update={"conditions": known}) if usable else None
        if query is not None:
            selection = graph.select(query, resolved, for_visual=True, allow_unknown=True)
            if selection["status"] != "resolved":
                return {**unresolved, "status": selection["status"]}
            scope = set(selection["entity_ids"])
            confirmed = set(graph.select(query, resolved, for_visual=True)["entity_ids"])
        elif step.depends_on:
            scope = set.intersection(*(resolved[p] for p in step.depends_on))
        found = self.engine.search(
            step.search_text,
            vector,
            method,
            self.settings.top_k,
            entity_ids=None if scope is None else graph.source_ids(scope),
        )
        links = graph.entity_links({r["image_id"] for r in found})
        ranked = {}
        for row in found:
            for entity_id, name in links.get(row["image_id"], {}).items():
                if scope is None or entity_id in scope:
                    item = ranked.setdefault(
                        entity_id,
                        {
                            "entity_id": entity_id,
                            "name": name,
                            "score": row["score"],
                            "graph_confirmed": None
                            if confirmed is None
                            else entity_id in confirmed,
                            "images": [],
                        },
                    )
                    if len(item["images"]) < self.settings.bridge_images:
                        item["images"].append({"image_id": row["image_id"], "score": row["score"]})

        # Điểm sát nhau: ưu tiên nơi graph xác nhận hơn nơi chưa rõ vị trí, rồi so các ảnh sau.
        best = max((h["score"] for h in ranked.values()), default=0)
        floor = best - self.settings.bridge_margin * abs(best)

        def strength(item):
            scores = [-image["score"] for image in item["images"]]
            scores += [0.0] * (self.settings.bridge_images - len(scores))
            return not (item["graph_confirmed"] and item["score"] >= floor), scores

        hypotheses = sorted(ranked.values(), key=lambda h: (strength(h), h["entity_id"]))
        # Bằng nhau hoàn toàn thì không tự chọn một nơi; gồm ảnh chung của nhiều nơi.
        tied = [h for h in hypotheses if strength(h) == strength(hypotheses[0])]
        status = (
            "no_candidates"
            if not hypotheses
            else "ambiguous_entity"
            if len(tied) > 1
            else "resolved"
        )
        kept = max(self.settings.bridge_hypotheses, len(tied))
        return {
            "status": status,
            "entity_ids": [hypotheses[0]["entity_id"]] if status == "resolved" else [],
            "method": "visual_bridge",
            "unmatched_names": list(unmatched),
            "scope_entities": None if scope is None else len(scope),
            "hypotheses": hypotheses[:kept],
            "tied_entity_ids": [h["entity_id"] for h in tied] if len(tied) > 1 else [],
        }

    def identify_unknown_name(self, step, selection, vectors, method):
        """Tên không có trong graph nhưng câu có mô tả: nhận diện qua ảnh, tên là mô tả mềm."""
        graph = self.engine.graph_store
        if graph is None or step.action != "retrieve_images" or not step.identity_text:
            return selection
        unmatched = self.unmatched_anchors(step.graph)
        if (
            step.entity_mention
            and self.named_scope(step.entity_mention)["status"] == "no_graph_match"
        ):
            unmatched.append(step.entity_mention)
        if not unmatched:
            return selection  # Tên có thật, chỉ là không thỏa quan hệ: không được nới.
        fallback = identity_step(step).model_copy(update={"depends_on": []})
        vector = (vectors or {}).get(fallback.id)
        return self.resolve_visual(fallback, {}, vector, method, unmatched)

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
        groups, trace, resolved, states, guessed = [], [], {}, {}, set()
        target_of = {s.id: s.target_id for s in plan.steps}
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
                if graph is not None and visual_bridge(step):
                    selection = self.resolve_visual(
                        step,
                        resolved,
                        (vectors or {}).get(step.id),
                        method,
                        self.unmatched_anchors(step.graph),
                        step.graph,
                    )
                    guessed.add(step.id)
                else:
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
            if selection is not None and selection["status"] == "no_graph_match":
                selection = self.identify_unknown_name(step, selection, vectors, method)
                if selection.get("method"):
                    guessed.add(step.id)
                    trace.append({"step_id": step.id, **selection, "graph": None})
            if guessed & set(step.depends_on):
                guessed.add(step.id)
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
                    if step.id in guessed:
                        # Nơi chứa suy từ ảnh tương tự, chưa được xác minh.
                        group["entity_hypotheses_unverified"] = True
                        group["verification_status"] = "visual_bridge_unverified"
                        group["unmatched_names"] = sorted(
                            {
                                n
                                for t in trace
                                if target_of[t["step_id"]] == step.target_id
                                for n in t.get("unmatched_names", [])
                            }
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
                "Entity nhận diện qua ảnh khác là suy đoán theo điểm tìm kiếm, chưa xác minh.",
                "Điều kiện ảnh được xếp hạng bằng RRF; chưa rerank.",
            ],
        }
