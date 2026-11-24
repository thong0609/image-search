"""Trả danh sách ảnh kiểu công cụ tìm ảnh: luôn có kết quả, mỗi mục tiêu một danh sách."""

import time

from image_search.planner.schemas import QueryPlan
from image_search.retrieval.executor import direct_steps


def target_texts(plan, text):
    """Câu tìm dự phòng: nguyên câu nếu một mục tiêu, nếu không thì phần riêng của mục tiêu."""
    if plan is None:
        return {"t1": text}
    targets = list(dict.fromkeys(step.target_id for step in plan.steps))
    if len(targets) == 1:
        return {targets[0]: text}
    return {
        target: " ".join(s.search_text for s in plan.steps if s.target_id == target)
        for target in targets
    }


def interleave(first, second):
    """Xen kẽ hai danh sách, giữ hạng 1 của danh sách đầu, bỏ ảnh trùng."""
    rows, seen = [], set()
    for n in range(max(len(first), len(second))):
        for source in (first, second):
            if n < len(source) and source[n]["image_id"] not in seen:
                seen.add(source[n]["image_id"])
                rows.append(source[n])
    return rows


def append(first, second):
    seen = {row["image_id"] for row in first}
    return first + [row for row in second if row["image_id"] not in seen]


def tied_places(result, plan, target_id):
    """Các nơi bằng điểm của bước nhận diện; không chọn được một thì lấy ảnh của tất cả."""
    steps = {s.id: s for s in plan.steps} if plan else {}
    for item in result["trace"]:
        if item["status"] == "ambiguous_entity" and steps[item["step_id"]].target_id == target_id:
            return set(item.get("tied_entity_ids", []))
    return set()


def search_list(engine, encoder, text, plan, method="hybrid"):
    """plan=None khi planner lỗi: tìm bằng nguyên câu. Câu cần làm rõ vẫn hỏi lại."""
    plan = None if plan is None else QueryPlan.model_validate(plan)
    if plan is not None and plan.needs_clarification:
        return {**engine.execute(plan), "timing_ms": {"embedding": 0, "retrieval": 0}}
    steps = direct_steps(plan) if plan else []
    texts = target_texts(plan, text)
    vectors, fallback_vectors, started = {}, {}, time.perf_counter()
    if method != "keyword":
        array, details = encoder.encode_texts([s.search_text for s in steps] + list(texts.values()))
        if any(d["truncated"] for d in details[: len(steps)]):
            raise ValueError("Query bị cắt token; không tiếp tục retrieval")
        vectors = {s.id: v for s, v in zip(steps, array, strict=False)}
        # Câu dự phòng quá dài cho encoder thì chỉ dùng BM25, không dùng vector bị cắt.
        fallback_vectors = {
            target: vector
            for target, vector, detail in zip(
                texts, array[len(steps) :], details[len(steps) :], strict=True
            )
            if not detail["truncated"]
        }
    embedded = time.perf_counter()
    result = (
        engine.execute(plan, method, vectors)
        if plan
        else {"status": "planner_error", "groups": [], "trace": [], "limitations": []}
    )
    groups = {group["target_id"]: group for group in result["groups"]}
    size, output = engine.settings.list_size, []
    for target, query in texts.items():
        vector = fallback_vectors.get(target)
        whole = engine.search(
            query, vector, "keyword" if vector is None else method, engine.settings.top_k
        )
        whole = [{**row, "source": "query"} for row in whole]
        group = groups.get(target) or {
            "target_id": target,
            "step_id": None,
            "search_text": query,
            "requested_count": None,
            "status": "planner_error",
            "entity_scope": None,
            "candidates": [],
            "results": [],
            "verification_status": "unverified",
        }
        found = group["candidates"] if group["results"] else []
        guessed = group["verification_status"] == "visual_bridge_unverified"
        tied = tied_places(result, plan, target)
        if not found and tied:
            step = next(
                s for s in plan.steps if s.target_id == target and s.action == "retrieve_images"
            )
            found, guessed = (
                engine.search(
                    step.search_text,
                    vectors.get(step.id),
                    method,
                    engine.settings.top_k,
                    entity_ids=engine.graph_store.source_ids(tied),
                ),
                True,
            )
        found = [{**row, "source": "place"} for row in found]
        # Nơi suy đoán có thể sai nên xen kẽ; phạm vi chắc chắn đứng trước, phần sau chỉ lấp.
        rows = interleave(found, whole) if guessed else append(found, whole)
        output.append(
            {
                **group,
                "status": group["status"] if found else "fallback_results",
                "resolution_status": group["status"],
                "selection_limit": size,
                "results": rows[:size],
            }
        )
    fallback = all(g["status"] == "fallback_results" for g in output)
    return {
        **result,
        "status": "fallback_results" if fallback else "candidate_results",
        "groups": output,
        "timing_ms": {
            "embedding": (embedded - started) * 1000,
            "retrieval": (time.perf_counter() - embedded) * 1000,
        },
    }
