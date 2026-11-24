"""Chấm kết quả image-search-retrieval bằng nhãn đã biết; không gọi model hoặc API."""

import argparse
from collections import Counter, defaultdict, deque
from pathlib import Path

import numpy as np

from image_search.baseline.evaluate import score_query
from image_search.files import read_jsonl, write_json

METRICS = {
    "R@10": "known_recall@10",
    "nDCG@10": "known_ndcg@10",
    "đủ@10": "all_targets_complete@10",
    "đích@1": "first@1",
    "đích@10": "first@10",
    "đích@20": "first@20",
}


def merge_rankings(rankings, limit):
    """Gộp các nhóm mục tiêu bằng round-robin, bỏ ảnh trùng."""
    queues = deque(iter(rows) for rows in rankings)
    seen, result = set(), []
    while queues and len(result) < limit:
        queue = queues.popleft()
        row = next(queue, None)
        if row is None:
            continue
        queues.append(queue)
        if row["image_id"] not in seen:
            result.append(row)
            seen.add(row["image_id"])
    return result


def score_case(query, answer, prediction):
    if query["answerable"] is None:
        raise ValueError("Câu chưa rõ đáp án không được chấm")
    ranked = merge_rankings([g["results"] for g in prediction["groups"]], 20)
    score = score_query({"synthetic": True, **query}, answer, ranked[:10])
    gold = {iid for target in answer["targets"] for iid in target["image_ids"]}
    rank = next((n for n, row in enumerate(ranked, 1) if row["image_id"] in gold), None)
    for k in (1, 10, 20):
        score[f"first@{k}"] = float(rank is not None and rank <= k)
    return score


def summarize(queries, answers, predictions):
    """Trung bình theo họ ý định trong từng split/loại/nhóm; câu âm và unknown không chấm."""
    families = defaultdict(lambda: defaultdict(list))
    for query in queries:
        qid = query["query_id"]
        if query["answerable"] is not True or qid not in predictions:
            continue
        group = "/".join(str(query.get(k, "-")) for k in ("split", "type", "report_group"))
        score = score_case(query, answers[qid], predictions[qid])
        families[group][query.get("intent_id", qid)].append(score)
    report = {}
    for group, rows in sorted(families.items()):
        report[group] = {"queries": sum(map(len, rows.values()))}
        for name, key in METRICS.items():
            report[group][name] = float(
                np.mean([np.mean([r[key] for r in family]) for family in rows.values()])
            )
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run", type=Path, help="Thư mục output của image-search-retrieval")
    parser.add_argument("--queries", type=Path, default=Path("var/benchmark-v2/queries.jsonl"))
    parser.add_argument("--answers", type=Path, default=Path("var/benchmark-v2/answers.jsonl"))
    parser.add_argument("--plans", type=Path, help="Plan đã chạy, để cộng độ trễ planner")
    args = parser.parse_args()
    queries = read_jsonl(args.queries)
    answers = {a["query_id"]: a for a in read_jsonl(args.answers)}
    planner = {p["query_id"]: p["latency_ms"] for p in read_jsonl(args.plans)} if args.plans else {}
    output = {}
    for folder in sorted(p.parent for p in args.run.glob("*/predictions.jsonl")):
        predictions = {p["query_id"]: p for p in read_jsonl(folder / "predictions.jsonl")}
        timings = read_jsonl(folder / "timings.jsonl")
        latency = {"retrieval": [t["latency_ms"] for t in timings]}
        if planner:
            latency["planner+retrieval"] = [
                t["latency_ms"] + planner[t["query_id"]] for t in timings
            ]
        output[folder.name] = {
            "quality": summarize(queries, answers, predictions),
            "statuses": dict(Counter(p["status"] for p in predictions.values())),
            "latency_ms": {
                name: {f"p{p}": float(np.percentile(values, p)) for p in (50, 90, 95)}
                for name, values in latency.items()
            },
        }
    if not output:
        parser.error("Không có predictions.jsonl trong thư mục")
    write_json(args.run / "quality.json", output)
    print("| Phương pháp | Nhóm | Câu | " + " | ".join(METRICS) + " |")
    print("|---|---|---:|" + "---:|" * len(METRICS))
    for method, item in output.items():
        for group, row in item["quality"].items():
            values = " | ".join(f"{row[m]:.3f}" for m in METRICS)
            print(f"| {method} | {group} | {row['queries']} | {values} |")
    for method, item in output.items():
        print(method, item["statuses"], item["latency_ms"])


if __name__ == "__main__":
    main()
