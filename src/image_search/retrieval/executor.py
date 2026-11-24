"""Thực thi điều kiện graph, nhận diện entity qua ảnh (visual bridge) rồi tìm ảnh đích."""

import re

from image_search.adapters.qdrant.metadata import name_key
from image_search.graph.query import GraphQuery
from image_search.planner.schemas import QueryPlan

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
        self.graph = engine.graph_store
        self.catalog = engine.catalog
        self.settings = engine.settings

    def retrieve(self, step, entity_ids, vector, method):
        """entity_ids=None: không có phạm vi nơi chứa, tìm toàn kho."""
        source_ids = None if entity_ids is None else self.graph.source_ids(entity_ids)
        count = step.count or self.settings.default_count
        found = self.engine.search(
            step.search_text, vector, method, max(self.settings.top_k, count), source_ids
        )
        status = "candidates" if found else "no_candidates"
        if step.count is not None and len(found) < count:
            status = "insufficient_candidates"
        group = self.empty_group(step, status)
        group.update(
            entity_scope=None if source_ids is None else sorted(source_ids),
            graph_entity_ids=[] if entity_ids is None else sorted(entity_ids),
            candidates=found,
            results=found[:count],
            verification_status="unscoped" if entity_ids is None else "trusted_metadata_scope",
        )
        return group

    def unmatched_anchors(self, query):
        """Tên anchor không có entity nào trong graph."""
        names = [c.anchor_name for c in query.conditions if c.anchor_name] if query else []
        return [n for n in names if not self.graph.named(n)]

    def resolve_visual(self, step, resolved, vector, method, unmatched=(), query=None):
        """Tìm ảnh khớp đặc điểm nhận diện, xếp hạng entity theo ảnh điểm cao nhất.

        unmatched: tên graph không có. Tên vẫn nằm trong câu tìm kiếm nhưng không lọc được.
        """
        scope, confirmed = None, None
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
            selection = self.graph.select(query, resolved, for_visual=True, allow_unknown=True)
            if selection["status"] != "resolved":
                return {**unresolved, "status": selection["status"]}
            scope = set(selection["entity_ids"])
            confirmed = set(self.graph.select(query, resolved, for_visual=True)["entity_ids"])
        elif step.depends_on:
            scope = set.intersection(*(resolved[p] for p in step.depends_on))
        found = self.engine.search(
            step.search_text,
            vector,
            method,
            self.settings.top_k,
            entity_ids=None if scope is None else self.graph.source_ids(scope),
        )
        links = self.graph.entity_links({r["image_id"] for r in found})
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
        if step.action != "retrieve_images" or not step.identity_text:
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
            "image_conditions": step.conditions,
            "requested_count": step.count,
            "selection_limit": step.count or self.settings.default_count,
            "status": status,
            "entity_scope": None,
            "graph_entity_ids": [],
            "candidates": [],
            "results": [],
            "verification_status": status,
        }

    def named_scope(self, mention):
        query = GraphQuery(
            target_name=mention, target_kind=None, target_category=None, match="all", conditions=[]
        )
        selection = self.graph.select(query, {})
        if selection["status"] == "ambiguous_entity":
            return selection
        ids = set(selection["entity_ids"])
        for alias, sources in self.catalog.aliases.items():
            if name_key(alias) == name_key(mention):
                ids.update(self.graph.canonical_ids(sources))
        status = "ambiguous_entity" if len(ids) > 1 else "resolved" if ids else "no_graph_match"
        return {"status": status, "entity_ids": sorted(ids) if status == "resolved" else []}

    def select_scope(self, step, resolved, states, vectors, method):
        """Entity của bước; None khi bước không giới hạn nơi chứa."""
        failed = next(
            (
                states.get(p, "unsupported_graph_relation")
                for p in step.depends_on
                if states.get(p) != "resolved"
            ),
            None,
        )
        if failed:
            return {"status": failed, "entity_ids": []}
        if step.action == "resolve_entity" and (step.graph is None or step.conditions):
            if not visual_bridge(step):
                return {"status": "unsupported_graph_relation", "entity_ids": []}
            return self.resolve_visual(
                step,
                resolved,
                vectors.get(step.id),
                method,
                self.unmatched_anchors(step.graph),
                step.graph,
            )
        if step.graph is not None:
            selection = self.graph.select(step.graph, resolved)
            if selection["status"] == "resolved" and step.entity_mention:
                named = self.named_scope(step.entity_mention)
                ids = set(selection["entity_ids"]) & set(named["entity_ids"])
                status = named["status"]
                if status == "resolved" and not ids:
                    status = "no_graph_match"
                selection = {"status": status, "entity_ids": sorted(ids)}
        elif step.depends_on:
            ids = set.intersection(*(resolved[p] for p in step.depends_on))
            selection = {
                "status": "resolved" if ids else "no_graph_match",
                "entity_ids": sorted(ids),
            }
        elif step.entity_mention:
            selection = self.named_scope(step.entity_mention)
        else:
            return None
        if selection["status"] == "no_graph_match":
            return self.identify_unknown_name(step, selection, vectors, method)
        return selection

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
        vectors = vectors or {}
        if method != "keyword" and set(vectors) != {s.id for s in direct_steps(plan)}:
            raise ValueError("Vector không khớp step ID được hỗ trợ của kế hoạch")
        groups, trace, resolved, states, guessed = [], [], {}, {}, set()
        target_of = {s.id: s.target_id for s in plan.steps}
        for step in plan.steps:
            selection = self.select_scope(step, resolved, states, vectors, method)
            visual = selection is not None and "method" in selection
            if visual or guessed & set(step.depends_on):
                guessed.add(step.id)
            if step.action == "resolve_entity":
                resolved[step.id] = set(selection["entity_ids"])
                states[step.id] = selection["status"]
            if step.action == "resolve_entity" or visual:
                graph = step.graph.model_dump() if step.graph else None
                trace.append({"step_id": step.id, **selection, "graph": graph})
            if step.action == "resolve_entity":
                continue
            if selection is None:
                group = self.retrieve(step, None, vectors.get(step.id), method)
            elif selection["status"] != "resolved":
                group = self.empty_group(step, selection["status"])
            else:
                entity_ids = set(selection["entity_ids"])
                group = self.retrieve(step, entity_ids, vectors.get(step.id), method)
                if step.id in guessed:
                    # Nơi chứa suy từ ảnh tương tự, chưa được xác minh.
                    group["verification_status"] = "visual_bridge_unverified"
                    group["unmatched_names"] = sorted(
                        {
                            name
                            for item in trace
                            if target_of[item["step_id"]] == step.target_id
                            for name in item.get("unmatched_names", [])
                        }
                    )
            groups.append(group)
        blocked = [g for g in groups if not g["results"]]
        if all(g["status"] == "unsupported_graph_relation" for g in groups):
            status = "unsupported_graph_relation"
        elif len(blocked) == len(groups):
            status = "unresolved"
        else:
            status = "partial_results" if blocked else "candidate_results"
        return {"status": status, "groups": groups, "trace": trace}
