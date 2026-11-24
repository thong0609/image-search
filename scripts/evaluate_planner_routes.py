"""Đo route của planner nhiều lượt; báo cả bỏ sót và nhận nhầm multi-hop. Gọi API có phí."""

import argparse
import hashlib
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from image_search.files import file_hash, read_jsonl, write_json, write_jsonl
from image_search.planner.evaluate import normalize, percentile
from image_search.planner.router import PROMPT, PROMPT_VERSION, make_client, route_query
from image_search.planner.settings import PlannerSettings

PRICE = {"input_price": 0.25, "cached_input_price": 0.025, "output_price": 2.0}


def label(row):
    return row["type"] if "type" in row else row["expected"]["query_type"]


def route(prediction):
    return prediction["plan"]["query_type"] if prediction["status"] == "ok" else "ERROR"


def roles_ok(row, prediction):
    """Đặc điểm nhận diện chỉ ở resolve_entity, nội dung ảnh đích chỉ ở retrieve_images."""
    if "bridge" not in row:
        return None
    if prediction["status"] != "ok":
        return False
    texts = defaultdict(str)
    for step in prediction["plan"]["steps"]:
        texts[step["action"]] += " " + normalize(
            " ".join([step["search_text"], *step["conditions"]])
        )
    bridge, target = normalize(row["bridge"]), normalize(row["target"])
    found, shown = texts["resolve_entity"], texts["retrieve_images"]
    return bridge in found and bridge not in shown and target in shown and target not in found


def summarize(rows, predictions):
    clean = []
    routes, confusion, roles = defaultdict(list), defaultdict(Counter), []
    by_id = {r["query_id"]: r for r in rows}
    for prediction in predictions:
        row = by_id[prediction["query_id"]]
        routes[row["query_id"]].append(route(prediction))
        confusion[label(row)][route(prediction)] += 1
        ok = roles_ok(row, prediction)
        if ok is not None:
            roles.append((row["query_id"], ok))
        if not row.get("contested"):
            clean.append(route(prediction) == label(row))
    correct = sum(c[t] for t, c in confusion.items())
    hops = confusion.get("multi-hop", Counter())
    others = [(t, c) for t, c in confusion.items() if t != "multi-hop"]
    latency = [p["latency_ms"] for p in predictions]
    return {
        "predictions": len(predictions),
        "route_correct": correct,
        "confusion": {t: dict(c) for t, c in confusion.items()},
        "missed_multi_hop": sum(hops.values()) - hops["multi-hop"],
        "false_multi_hop": sum(c["multi-hop"] for _, c in others),
        "route_correct_without_contested": [sum(clean), len(clean)],
        "roles_correct": [sum(ok for _, ok in roles), len(roles)],
        "roles_wrong": dict(Counter(q for q, ok in roles if not ok)),
        "unstable_queries": sorted(q for q, values in routes.items() if len(set(values)) > 1),
        "errors": dict(Counter(p["error_code"] for p in predictions if p["error_code"])),
        "estimated_cost_usd": sum(p["estimated_cost_usd"] or 0 for p in predictions),
        "latency_ms": {f"p{p}": percentile(latency, p) for p in (50, 90, 95)},
        "routes": {q: {"label": label(by_id[q]), "routes": v} for q, v in sorted(routes.items())},
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("queries", type=Path)
    parser.add_argument("--split", choices=("dev", "test"))
    parser.add_argument("--rounds", type=int, default=1)
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    if args.rounds < 1 or not 1 <= args.workers <= 8:
        parser.error("rounds >= 1; workers trong 1..8")
    if args.output_dir.exists():
        parser.error("Output đã tồn tại; dùng thư mục mới")
    rows = [r for r in read_jsonl(args.queries) if args.split in (None, r["split"])]
    if not rows:
        parser.error("Không có query")
    settings = PlannerSettings(**PRICE)
    args.output_dir.mkdir(parents=True)
    (args.output_dir / "system-prompt.txt").write_text(PROMPT)
    write_json(
        args.output_dir / "run.json",
        {
            "queries": str(args.queries),
            "queries_sha256": file_hash(args.queries),
            "split": args.split,
            "rounds": args.rounds,
            "prompt_version": PROMPT_VERSION,
            "prompt_sha256": hashlib.sha256(PROMPT.encode()).hexdigest(),
            "settings": settings.model_dump(mode="json", exclude={"api_key"}),
            "labels_sent_to_model": False,
        },
    )

    def execute(job):
        number, row = job
        # Chỉ gửi text; nhãn, bridge và split không rời máy.
        return {
            "query_id": row["query_id"],
            "round": number,
            **route_query(row["text"], settings, client),
        }

    jobs = [(n, r) for n in range(1, args.rounds + 1) for r in rows]
    predictions = []
    with make_client(settings) as client, ThreadPoolExecutor(args.workers) as pool:
        for prediction in pool.map(execute, jobs):
            predictions.append(prediction)
            write_jsonl(args.output_dir / "predictions.jsonl", predictions)
    report = summarize(rows, predictions)
    write_json(args.output_dir / "report.json", report)
    for key, value in report.items():
        if key != "routes":
            print(key, value)
    for qid, item in report["routes"].items():
        if any(r != item["label"] for r in item["routes"]):
            print(qid, item["label"], "->", item["routes"])


if __name__ == "__main__":
    main()
