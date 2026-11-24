"""Chấm nhãn đã biết; lấy trung bình mục tiêu rồi trung bình query."""

import json
import math
from collections import defaultdict
from pathlib import Path

from image_search.baseline.benchmark import load_manifest
from image_search.files import (
    file_hash,
    read_json,
    read_jsonl,
    unique_by,
    write_json,
    write_jsonl,
)


def score_query(query, answer, results):
    # Bỏ trùng trước khi cắt K, giữ lần xuất hiện đầu tiên.
    ranked = list(dict.fromkeys(row["image_id"] for row in results))
    score = {
        "query_id": query["query_id"],
        "split": query["split"],
        "type": query["type"],
        "synthetic": query["synthetic"],
        "answerable": query["answerable"],
    }
    if not query["answerable"]:
        score["rejected"] = not ranked
        return score
    if not answer["targets"]:
        raise ValueError(f"{query['query_id']}: thiếu mục tiêu")
    for k in [1, 5, 10]:
        recalls, ndcgs, hits, complete = [], [], [], []
        for target in answer["targets"]:
            truth = set(target["image_ids"])
            if not truth or not 1 <= target["required"] <= len(truth):
                raise ValueError(f"{query['query_id']}: mục tiêu không hợp lệ")
            relevant = [image_id in truth for image_id in ranked[:k]]
            count = sum(relevant)
            dcg = sum(1 / math.log2(i + 2) for i, found in enumerate(relevant) if found)
            ideal = sum(1 / math.log2(i + 2) for i in range(min(k, len(truth))))
            recalls.append(count / len(truth))
            ndcgs.append(dcg / ideal)
            hits.append(float(count > 0))
            complete.append(float(count >= target["required"]))
        score[f"known_recall@{k}"] = sum(recalls) / len(recalls)
        score[f"known_ndcg@{k}"] = sum(ndcgs) / len(ndcgs)
        score[f"hit@{k}"] = sum(hits) / len(hits)
        score[f"target_complete@{k}"] = sum(complete) / len(complete)
        score[f"all_targets_complete@{k}"] = float(all(complete))
    return score


def evaluate_predictions(manifest_path, predictions_path, split="dev"):
    manifest = load_manifest(manifest_path)
    queries = [q for q in read_jsonl(manifest["files"]["queries"]["path"]) if q["split"] == split]
    answers = unique_by(read_jsonl(manifest["files"]["answers"]["path"]), "query_id")
    predictions = unique_by(read_jsonl(predictions_path), "query_id")
    if predictions.keys() != {q["query_id"] for q in queries}:
        raise ValueError("Dự đoán thiếu hoặc thừa query so với split")
    valid_ids = {row["image_id"] for row in manifest["images"]}
    scores = []
    for query in queries:
        results = predictions[query["query_id"]]["results"]
        for row in results:
            if row["image_id"] not in valid_ids or not math.isfinite(row["score"]):
                raise ValueError("Dự đoán có ID lạ hoặc điểm không hợp lệ")
        scores.append(score_query(query, answers[query["query_id"]], results))
    groups = defaultdict(list)
    for score in scores:
        category = "answerable" if score["answerable"] else "no-answer"
        source = "synthetic" if score["synthetic"] else "authored"
        for group in [
            f"{split}/{category}",
            f"{split}/{score['type']}/{category}",
            f"{split}/{source}/{category}",
            f"{split}/{score['type']}/{source}/{category}",
        ]:
            groups[group].append(score)
    summary = {}
    for name, rows in groups.items():
        summary[name] = {"queries": len(rows)}
        for key in rows[0]:
            if key.startswith(("known_", "hit@", "target_", "all_targets_")) or key == "rejected":
                summary[name][key] = sum(row[key] for row in rows) / len(rows)
    output_dir = Path(predictions_path).parent
    run_path = output_dir / "run.json"
    run = None
    if run_path.exists():
        run = read_json(run_path)
        if (
            run["manifest_sha256"] != file_hash(manifest_path)
            or run["split"] != split
            or run["predictions_sha256"] != file_hash(predictions_path)
        ):
            raise ValueError("Thông tin lần chạy không khớp dự đoán/benchmark/split")
        if run["top_k"] < 10:
            raise ValueError("Chấm baseline cần dự đoán ít nhất top-10")
    write_jsonl(output_dir / "query-scores.jsonl", scores)
    errors = [
        row
        for row in scores
        if (row.get("all_targets_complete@10") == 0 or row.get("rejected") is False)
    ]
    report = {
        "summary": summary,
        "run": run,
        "error_query_ids": [s["query_id"] for s in errors],
        "limitations": [
            "Chỉ chấm nhãn đã biết, không phải Recall thị giác đầy đủ.",
            "Baseline nhận nguyên câu; không trả đường suy luận, không có ngưỡng từ chối.",
            "Split dựa trên entity/ảnh trùng; cần gán split_group cho ảnh gần trùng đã nhận diện.",
        ],
    }
    write_json(output_dir / "report.json", report)
    lines = [f"# Báo cáo baseline — {split}", "", *report["limitations"], ""]
    if run:
        lines.extend(
            [
                "## Hiệu năng",
                "",
                f"Phương pháp: {run.get('method', 'vector')}.",
                f"p50: {run['p50_ms']:.2f} ms; p95: {run['p95_ms']:.2f} ms.",
                f"RAM đỉnh process: {run['runtime']['peak_ram_mb']:.1f} MiB.",
                f"Nạp model tìm kiếm: {run['model_load_seconds']:.2f} giây.",
                (
                    f"Vector trong Qdrant: {run['index']['shape'][0]} ảnh, "
                    f"{run['index']['shape'][1]} chiều."
                    if run.get("method", "vector") != "keyword"
                    else "Keyword chỉ dùng metadata, không nạp encoder khi truy vấn."
                ),
                f"Nạp/lập keyword index: {run.get('keyword_load_seconds', 0):.2f} giây.",
                "Cấu hình, phần cứng và từng lần đo: xem run.json/timings.jsonl.",
                "",
            ]
        )
    for name, values in summary.items():
        lines.extend([f"## {name}", "", "```json", json.dumps(values, indent=2), "```", ""])
    lines.extend(["## Query cần xem lại", "", ", ".join(report["error_query_ids"]) or "Không có"])
    (output_dir / "report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"Đã lưu báo cáo: {output_dir / 'report.md'}")
    return report
