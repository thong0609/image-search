"""Báo cáo retrieval replay; labels chỉ dùng chấm sau khi đã có kết quả."""

import argparse
from collections import Counter
from pathlib import Path

import numpy as np
from report_pipeline_evaluation import aggregate, score_pipeline_case

from image_search.baseline.utils import file_hash, read_json, read_jsonl, write_json, write_jsonl


def main():
    parser = argparse.ArgumentParser(
        description="Chấm lại retrieval bằng kế hoạch đã lưu, không gọi API"
    )
    parser.add_argument("output", type=Path)
    parser.add_argument("--queries", type=Path, default=Path("var/benchmark-v2/queries.jsonl"))
    parser.add_argument("--answers", type=Path, default=Path("var/benchmark-v2/answers.jsonl"))
    parser.add_argument("--reference", type=Path, default=Path("var/pipeline-v1"))
    args = parser.parse_args()
    root = args.output
    run = read_json(root / "run.json")
    assert run["planner_called"] is False
    assert run["plans_sha256"] == file_hash(args.reference / "plans.jsonl")
    queries = read_jsonl(args.queries)
    answers = {r["query_id"]: r for r in read_jsonl(args.answers)}
    positive = [q for q in queries if q["answerable"] is True]
    old = {r["query_id"]: r for r in read_jsonl(args.reference / "predictions.jsonl")}
    old_scores = [
        score_pipeline_case(q, answers[q["query_id"]], old[q["query_id"]]) for q in positive
    ]
    quality = {"previous_pipeline_v1": aggregate(positive, old_scores)}
    operational = {}
    for method in ("vector", "keyword", "hybrid"):
        predictions = read_jsonl(root / method / "predictions.jsonl")
        pred = {r["query_id"]: r for r in predictions}
        assert len(pred) == len(predictions) == len(queries)
        assert set(pred) == {q["query_id"] for q in queries}
        assert (
            file_hash(root / method / "predictions.jsonl")
            == read_json(root / method / "report.json")["predictions_sha256"]
        )
        scores = [
            score_pipeline_case(q, answers[q["query_id"]], pred[q["query_id"]]) for q in positive
        ]
        quality[method] = aggregate(positive, scores)
        write_jsonl(root / method / "query-scores.jsonl", scores)
        timings = read_jsonl(root / method / "timings.jsonl")
        operational[method] = {}
        for kind in ("single", "multi-target", "multi-hop"):
            ids = {q["query_id"] for q in queries if q["type"] == kind}
            ts = [t["latency_ms"] for t in timings if t["query_id"] in ids]
            operational[method][kind] = {
                "queries": len(ids),
                "statuses": dict(Counter(pred[i]["status"] for i in ids)),
                "p50_ms": float(np.percentile(ts, 50)),
                "p90_ms": float(np.percentile(ts, 90)),
                "p95_ms": float(np.percentile(ts, 95)),
            }
    write_json(root / "quality.json", quality)
    write_json(root / "operational.json", operational)
    lines = [
        f"# Replay retrieval bằng {len(queries)} kế hoạch đã lưu",
        "",
        "Graph được khóa trước khi chấm; không dùng golden queries/answers để dựng graph.",
        "Không gọi API. Đây không phải đánh giá planner v3 mới hoặc toàn pipeline mới.",
        "Độ trễ gồm embedding + executor; không gồm planner/startup. Số round theo run.json.",
        "Nhãn là known positives v2, chưa đại diện toàn nhu cầu người dùng.",
        "",
        "| Test canonical | Phương pháp | Số câu | Recall@10 | nDCG@10 |",
        "|---|---|---:|---:|---:|",
    ]
    for kind in ("single", "multi-target", "multi-hop"):
        for method in quality:
            s = quality[method][f"test/{kind}/canonical"]
            lines.append(
                f"| {kind} | {method} | {s['queries']} | "
                f"{s['known_recall@10']:.4f} | {s['known_ndcg@10']:.4f} |"
            )
    lines += [
        "",
        "| Phương pháp | Loại câu | p50 ms | p90 ms | p95 ms |",
        "|---|---|---:|---:|---:|",
    ]
    for method, kinds in operational.items():
        for kind, row in kinds.items():
            lines.append(
                f"| {method} | {kind} | {row['p50_ms']:.1f} | "
                f"{row['p90_ms']:.1f} | {row['p95_ms']:.1f} |"
            )
    lines += [
        "",
        "Latency trên toàn bộ câu, gồm cả lỗi/unsupported/hỏi lại; không chứng minh SLO.",
        "Phân bố trạng thái từng loại nằm trong operational.json.",
    ]
    lines += [
        "",
        "Kế hoạch v2 không có predicate graph: các dependency cũ vẫn báo unsupported.",
        "Các truy vấn quan hệ mới được kiểm tra riêng trong ../functional-checks.json.",
        "Replay không chứng minh chất lượng multi-hop mới đã đạt yêu cầu.",
    ]
    (root / "report.md").write_text("\n".join(lines) + "\n")
    write_json(
        root / "verification.json",
        {
            "queries": len(queries),
            "api_calls": 0,
            "planner_version": "cached-v2",
            "graph_sha256": read_json(root / "run.json")["graph_sha256"],
            "plans_sha256": file_hash(args.reference / "plans.jsonl"),
            "queries_sha256": file_hash(args.queries),
            "answers_sha256": file_hash(args.answers),
            "reference_predictions_sha256": file_hash(args.reference / "predictions.jsonl"),
            "label_scope": "known positives only",
            "reporter_sha256": file_hash(Path(__file__)),
            "full_pipeline_slo_evaluated": False,
            "methods": ["vector", "keyword", "hybrid"],
        },
    )
    print("\n".join(lines))


if __name__ == "__main__":
    main()
