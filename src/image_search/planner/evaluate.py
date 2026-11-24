"""Chấm route/slot/đồ thị; không dùng LLM tự chấm chính nó."""

import math
import unicodedata
from collections import Counter, defaultdict

from image_search.planner.schemas import QueryPlan


def normalize(value):
    if value is None:
        return ""
    return " ".join(unicodedata.normalize("NFKC", value).casefold().split())


def step_signatures(plan):
    signatures = {}
    for step in plan.steps:
        signatures[step.id] = (
            step.action,
            normalize(step.entity_mention),
            tuple(sorted(map(normalize, step.conditions))),
            step.count,
            tuple(sorted((signatures[parent] for parent in step.depends_on), key=repr)),
        )
    return Counter(repr(signatures[s.id]) for s in plan.steps if s.action == "retrieve_images")


def dependency_shape(plan):
    shapes = {}
    for step in plan.steps:
        shapes[step.id] = (
            step.action,
            tuple(sorted((shapes[parent] for parent in step.depends_on), key=repr)),
        )
    return Counter(repr(shapes[s.id]) for s in plan.steps if s.action == "retrieve_images")


def percentile(values, percent):
    if not values:
        return None
    ordered = sorted(values)
    index = (len(ordered) - 1) * percent / 100
    low, high = math.floor(index), math.ceil(index)
    return ordered[low] + (ordered[high] - ordered[low]) * (index - low)


def score_case(expected, prediction):
    truth = QueryPlan.model_validate(expected)
    keys = [
        "route_correct",
        "clarification_correct",
        "targets_correct",
        "counts_correct",
        "conditions_correct",
        "dependencies_correct",
        "plan_correct",
    ]
    if prediction["status"] != "ok":
        result = dict.fromkeys(keys, False)
        if truth.needs_clarification:
            for key in (
                "targets_correct",
                "counts_correct",
                "conditions_correct",
                "dependencies_correct",
            ):
                result[key] = None
        return result
    actual = QueryPlan.model_validate(prediction["plan"])
    result = {
        "route_correct": actual.query_type == truth.query_type,
        "clarification_correct": actual.needs_clarification == truth.needs_clarification,
    }
    if truth.needs_clarification:
        for key in (
            "targets_correct",
            "counts_correct",
            "conditions_correct",
            "dependencies_correct",
        ):
            result[key] = None  # Không chấm slot retrieval của câu cần làm rõ.
        result["plan_correct"] = all(result[k] for k in result if result[k] is not None)
        return result

    def final(plan):
        return [s for s in plan.steps if s.action == "retrieve_images"]

    result["targets_correct"] = Counter(
        normalize(s.entity_mention) for s in final(actual)
    ) == Counter(normalize(s.entity_mention) for s in final(truth))
    result["counts_correct"] = Counter(
        (normalize(s.entity_mention), s.count) for s in final(actual)
    ) == Counter((normalize(s.entity_mention), s.count) for s in final(truth))
    result["conditions_correct"] = Counter(
        (s.action, normalize(s.entity_mention), tuple(sorted(map(normalize, s.conditions))))
        for s in actual.steps
    ) == Counter(
        (s.action, normalize(s.entity_mention), tuple(sorted(map(normalize, s.conditions))))
        for s in truth.steps
    )
    result["dependencies_correct"] = dependency_shape(actual) == dependency_shape(truth)
    result["plan_correct"] = all(result.values()) and step_signatures(actual) == step_signatures(
        truth
    )
    return result


def evaluate_cases(cases, predictions):
    by_id = {p["query_id"]: p for p in predictions}
    if len(by_id) != len(predictions) or set(by_id) != {c["query_id"] for c in cases}:
        raise ValueError("Prediction thiếu/thừa/trùng query ID")
    scored, confusion, groups = [], defaultdict(Counter), defaultdict(list)
    for case in cases:
        prediction = by_id[case["query_id"]]
        row = {"query_id": case["query_id"], **score_case(case["expected"], prediction)}
        scored.append(row)
        truth = case["expected"]["query_type"]
        predicted = prediction["plan"]["query_type"] if prediction["status"] == "ok" else "ERROR"
        confusion[truth][predicted] += 1
        groups[truth].append(row)
    groups["overall"] = scored
    accuracy = {}
    for name, rows in groups.items():
        accuracy[name] = {"queries": len(rows)}
        for metric in scored[0]:
            if metric == "query_id":
                continue
            values = [r[metric] for r in rows if r[metric] is not None]
            accuracy[name][metric] = sum(values) / len(values) if values else None
    tokens = {}
    for key in ("input_tokens", "output_tokens", "cached_input_tokens", "estimated_cost_usd"):
        values = [p[key] for p in predictions if p.get(key) is not None]
        tokens[key] = {"known_sum": sum(values), "missing_queries": len(predictions) - len(values)}
    latency = [p["latency_ms"] for p in predictions]
    return {
        "accuracy": accuracy,
        "confusion_matrix": dict(confusion),
        "usage": tokens,
        "errors": dict(Counter(p["error_code"] for p in predictions if p["status"] != "ok")),
        "latency_ms": {f"p{p}": percentile(latency, p) for p in (50, 90, 95)},
        "case_scores": scored,
        "limitations": [
            "Nhãn planner do tác giả biên soạn, chưa có reviewer độc lập.",
            "Slot chấm khớp sau chuẩn hóa hoa/thường/khoảng trắng, không chấm ngữ nghĩa.",
            "Không chấm chất lượng search_text hoặc câu hỏi làm rõ bằng so chuỗi.",
            "Độ trễ một lượt/câu, gồm retry; chưa phải load benchmark.",
            "Chi phí là ước tính theo giá tự cấu hình; retry lỗi có thể phát sinh thêm.",
        ],
    }
