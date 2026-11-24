# ruff: noqa: E501
# Report prose and Markdown table rows keep long lines.
"""Chấm known positives và so baseline với cùng ngân sách top-K; không đổi output."""

import argparse
from collections import Counter, defaultdict, deque
from pathlib import Path

import numpy as np

from image_search.baseline.evaluate import score_query
from image_search.baseline.utils import file_hash, read_json, read_jsonl, write_json, write_jsonl
from image_search.retrieval.cli import write_gallery


def merge_rankings(rankings, limit):
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


def separate_group_complete(answer, groups, served_ids):
    edges = [
        [
            i
            for i, group in enumerate(groups)
            if len(
                {r["image_id"] for r in group["results"]} & served_ids & set(target["image_ids"])
            )
            >= target["required"]
        ]
        for target in answer["targets"]
    ]
    matched = {}

    def assign(target, seen):
        for group in edges[target]:
            if group in seen:
                continue
            seen.add(group)
            if group not in matched or assign(matched[group], seen):
                matched[group] = target
                return True
        return False

    return float(all(assign(i, set()) for i in range(len(edges))))


def score_pipeline_case(query, answer, prediction):
    if query["answerable"] is None:
        raise ValueError("Unknown answerability không được chấm retrieval hoặc coi là câu âm")
    groups = prediction.get("groups", [])
    served = merge_rankings([g["results"] for g in groups], 10)
    score = score_query(query, answer, served)
    score.update(
        intent_id=query["intent_id"],
        report_group=query["report_group"],
        evaluation_suite=query["evaluation_suite"],
    )
    if query["answerable"] is True:
        per_group = [
            merge_rankings([h["candidates"] for h in group.get("hypotheses", [])], 100)
            for group in groups
        ]
        candidate_pool = merge_rankings(per_group, 100)
        for k in (50, 100):
            ids = {r["image_id"] for r in candidate_pool[:k]}
            score[f"candidate_known_recall@{k}"] = sum(
                len(ids & set(t["image_ids"])) / len(t["image_ids"]) for t in answer["targets"]
            ) / len(answer["targets"])
        candidate_score = score_query(query, answer, candidate_pool)
        score["candidate_known_ndcg@10"] = candidate_score["known_ndcg@10"]
        score["candidate_all_targets_complete@10"] = candidate_score["all_targets_complete@10"]
        score["separate_group_matching_complete@10"] = separate_group_complete(
            answer, groups, {r["image_id"] for r in served}
        )
    return score


def aggregate(queries, scores):
    by_id = {s["query_id"]: s for s in scores}
    groups = defaultdict(list)
    for q in queries:
        if q["answerable"] is not True:
            continue
        groups[f"{q['split']}/{q['type']}/{q['report_group']}"].append(q)
    output = {}
    for name, cases in groups.items():
        families = defaultdict(list)
        for case in cases:
            families[case["intent_id"]].append(by_id[case["query_id"]])
        metrics = [
            k
            for k in by_id[cases[0]["query_id"]]
            if k.startswith(
                ("known_", "hit@", "target_", "all_targets_", "candidate_", "separate_")
            )
        ]
        output[name] = {"queries": len(cases), "families": len(families)}
        for metric in metrics:
            output[name][metric] = float(
                np.mean([np.mean([r[metric] for r in rows]) for rows in families.values()])
            )
    return output


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("output", type=Path, nargs="?", default=Path("var/pipeline-v1"))
    args = parser.parse_args()
    root = args.output
    run = read_json(root / "run.json")["configuration"]
    done = read_json(root / "completed.json")
    queries, answers = read_jsonl(run["queries"]), read_jsonl(run["answers"])
    assert file_hash(root / "executed-runner.py") == run["runner_sha256"]
    assert file_hash(run["queries"]) == run["queries_sha256"]
    assert file_hash(run["answers"]) == run["answers_sha256"]
    assert file_hash(root / "predictions.jsonl") == done["predictions_sha256"]
    assert file_hash(root / "plans.jsonl") == done["plans_sha256"]
    for path, digest in run["sources"].items():
        assert file_hash(path) == digest, path
    plans = {p["query_id"]: p for p in read_jsonl(root / "plans.jsonl")}
    predictions = read_jsonl(root / "predictions.jsonl")
    pred = {p["query_id"]: p for p in predictions}
    answer_map = {a["query_id"]: a for a in answers}
    assert len(pred) == len(predictions) == len(queries) == done["queries"]
    assert set(pred) == set(plans) == {q["query_id"] for q in queries}
    source_manifest = read_json(run["embedding"]["manifest"])
    valid_ids = {r["image_id"] for r in source_manifest["images"]}
    for row in predictions:
        for group in row.get("groups", []):
            assert all(r["image_id"] in valid_ids for r in group["candidates"])
            if group["status"] == "ambiguous_entity":
                assert not group["results"]
    positive = [q for q in queries if q["answerable"] is True]
    scored = [
        score_pipeline_case(q, answer_map[q["query_id"]], pred[q["query_id"]]) for q in positive
    ]
    write_jsonl(root / "query-scores.jsonl", scored)
    # Baseline reference input/hash phải khớp hoàn toàn. Không đọc benchmark labels để retrieval.
    baseline_root = Path("var/evaluation-v2-all")
    reference_run = read_json(baseline_root / "experiment.json")
    reference_manifest = read_json("var/benchmark-v2/evaluation-manifest.json")
    assert reference_run["manifest_sha256"] == file_hash(
        "var/benchmark-v2/evaluation-manifest.json"
    )
    assert reference_manifest["files"]["queries.jsonl"]["sha256"] == run["queries_sha256"]
    assert reference_manifest["files"]["answers.jsonl"]["sha256"] == run["answers_sha256"]
    assert reference_run["vector_index_sha256"] == run["image_index_sha256"]
    assert reference_run["keyword_index_sha256"] == file_hash(
        Path(run["retrieval"]["keyword_dir"]) / "index.json"
    )
    assert reference_run["config"]["rrf_k"] == run["retrieval"]["rrf_k"]
    assert reference_run["config"]["candidates"] == run["retrieval"]["candidates"]
    baseline_rows = read_jsonl(baseline_root / "hybrid/predictions.jsonl")
    baseline = {p["query_id"]: p for p in baseline_rows}
    assert set(baseline) == set(pred)
    baseline_scores = [
        score_query(q, answer_map[q["query_id"]], baseline[q["query_id"]]["results"])
        for q in positive
    ]
    comparison = {
        "pipeline": aggregate(positive, scored),
        "baseline_rrf": aggregate(positive, baseline_scores),
    }
    keyword_rows = read_jsonl(baseline_root / "keyword/predictions.jsonl")
    keyword_map = {p["query_id"]: p for p in keyword_rows}
    assert set(keyword_map) == set(pred)
    keyword_scores = [
        score_query(q, answer_map[q["query_id"]], keyword_map[q["query_id"]]["results"])
        for q in positive
    ]
    comparison["baseline_keyword"] = aggregate(positive, keyword_scores)
    write_json(root / "comparison.json", comparison)
    write_jsonl(root / "baseline-query-scores.jsonl", baseline_scores)
    operational = {}
    for label, selected in [("all", queries)] + [
        (
            f"{split}/{kind}/{group}",
            [
                q
                for q in queries
                if q["split"] == split and q["type"] == kind and q["report_group"] == group
            ],
        )
        for split in ("dev", "test", "unassigned")
        for kind in ("single", "multi-target", "multi-hop")
        for group in ("canonical", "robustness")
    ]:
        if not selected:
            continue
        rows = [pred[q["query_id"]] for q in selected]
        operational[label] = {
            "queries": len(rows),
            "statuses": dict(Counter(r["status"] for r in rows)),
            "group_statuses": dict(Counter(g["status"] for r in rows for g in r.get("groups", []))),
            "latency_ms": {
                key: {
                    f"p{p}": float(np.percentile([r["timing_ms"][key] for r in rows], p))
                    for p in (50, 90, 95, 99)
                }
                for key in ("planner", "cpu_queue", "embedding", "executor", "end_to_end")
            },
        }
    write_json(root / "operational.json", operational)
    usage = {
        key: {
            "known_sum": sum(p[key] for p in plans.values() if p.get(key) is not None),
            "missing": sum(p.get(key) is None for p in plans.values()),
        }
        for key in ("input_tokens", "output_tokens", "cached_input_tokens", "estimated_cost_usd")
    }
    write_json(root / "usage.json", usage)
    negatives = [
        {
            "query_id": q["query_id"],
            "status": pred[q["query_id"]]["status"],
            "empty_output": not any(g["results"] for g in pred[q["query_id"]].get("groups", [])),
        }
        for q in queries
        if q["answerable"] is False
    ]
    write_json(root / "catalog-negatives.json", negatives)
    lines = [
        "# Đánh giá pipeline RRF v1",
        "",
        f"{len(queries)} câu; {len(positive)} dương có nhãn; 42 unknown không chấm retrieval; 2 âm catalog báo riêng.",
        "Model và dữ liệu được giữ theo run.json. Không rerank hoặc tune theo kết quả.",
        "Labels v2 là ứng viên, chưa duyệt độc lập; test/corpus đã từng được xem.",
        "",
        "| Nhóm | Phương pháp | Câu | Known Recall@10 | Known nDCG@10 | Đủ mọi mục tiêu@10 |",
        "|---|---|---:|---:|---:|---:|",
    ]
    for group in sorted(comparison["pipeline"]):
        for method in ("baseline_keyword", "baseline_rrf", "pipeline"):
            r = comparison[method][group]
            lines.append(
                f"| {group} | {method} | {r['queries']} | {r['known_recall@10']:.3f} | "
                f"{r['known_ndcg@10']:.3f} | {r['all_targets_complete@10']:.3f} |"
            )
    latency = operational["all"]["latency_ms"]
    lines += [
        "",
        "## Độ trễ thực tế",
        "",
        f"Tối đa {run['workers']} yêu cầu đồng thời; CPU encoder/executor dùng lock.",
        "Đo từng yêu cầu từ submit đến hoàn thành, gồm OpenAI/client, CPU queue, embedding, executor và serialize JSON.",
        "Không gồm nạp model/index ban đầu, ghi artifact hoặc dựng báo cáo. Không cộng các p90 thành p90 tổng.",
        "",
        "| Thành phần | p50 ms | p90 ms | p95 ms |",
        "|---|---:|---:|---:|",
    ]
    for key, values in latency.items():
        lines.append(f"| {key} | {values['p50']:.1f} | {values['p90']:.1f} | {values['p95']:.1f} |")
    lines += [
        "",
        f"**SLO p90 < 300 ms: {'ĐẠT' if latency['end_to_end']['p90'] < 300 else 'KHÔNG ĐẠT'}.**",
        "",
        "## Cách chấm và giới hạn",
        "",
        "- Hai phương pháp dùng cùng labels và ngân sách 10 ảnh. Pipeline hợp nhất group.results bằng round-robin, bỏ trùng.",
        "- Nhánh ambiguous không được phục vụ ảnh; shortlist giả thuyết chỉ dùng chẩn đoán candidate Recall@50/100.",
        "- separate_group_matching_complete dùng matching một-một theo overlap known positives: alignment lạc quan, chưa có target ID gold.",
        "- API/schema/execution errors và câu dương bị hỏi lại vẫn chấm retrieval bằng kết quả rỗng; không loại lỗi để tăng điểm.",
        "- Chưa có điều kiện thị giác gold đầy đủ; unjudged không mặc nhiên là ảnh sai.",
        "- Chất lượng lấy trung bình theo intent_id trong từng split/type/canonical/robustness; latency đo trên từng request.",
        "- 400 câu tổng hợp và test đã xem, không phải holdout mới độc lập. Mẫu âm chỉ vắng tên catalog, không là âm thị giác tự nhiên.",
        "- Chi phí null nếu chưa cấu hình giá; known_sum=0 với missing không có nghĩa miễn phí. SDK retry có thể có chi phí ngoài usage nhận được.",
    ]
    (root / "report.md").write_text("\n".join(lines) + "\n")
    links = []
    for kind in ("single", "multi-target", "multi-hop"):
        selected = [
            {**pred[q["query_id"]], "query_id": q["query_id"]} for q in queries if q["type"] == kind
        ]
        write_gallery(root / f"results-{kind}.html", selected, source_manifest)
        links.append(f'<li><a href="results-{kind}.html">{kind}</a></li>')
    (root / "index.html").write_text(
        '<meta charset="utf-8"><h1>Pipeline RRF v1</h1><p>Kết quả 400 câu; nhãn còn là ứng viên.</p><ul>'
        + "".join(links)
        + "</ul>"
    )
    write_json(
        root / "verification.json",
        {
            "status": "passed",
            "queries": len(pred),
            "scored_positive_queries": len(scored),
            "input_source_and_prediction_hashes_match": True,
            "baseline_reference_matches_same_labels": True,
            "baseline_predictions_sha256": file_hash(baseline_root / "hybrid/predictions.jsonl"),
            "ambiguous_results_withheld": True,
            "report_sha256": file_hash(root / "report.md"),
        },
    )
    print("Saved", root / "report.md")


if __name__ == "__main__":
    main()
