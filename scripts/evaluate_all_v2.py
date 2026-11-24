# ruff: noqa: E501
# HTML templates retain long lines.
"""Chạy baseline hiện tại trên tập tham chiếu đã duyệt, không sửa/tune nhãn."""

import html
import random
import time
from collections import defaultdict
from pathlib import Path

import numpy as np

from image_search.baseline.evaluate import score_query
from image_search.baseline.keyword import fuse_rankings, keyword_search, load_keyword_index
from image_search.baseline.utils import file_hash, read_json, read_jsonl, write_json, write_jsonl
from image_search.baseline.vectors import (
    encode_text,
    load_encoder,
    load_index,
    processor_hash,
)

ROOT = Path("var/benchmark-v2")
OUTPUT = Path("var/evaluation-v2-all")
METRICS = ["known_recall@10", "known_ndcg@10", "all_targets_complete@10"]


def main():
    if (OUTPUT / "experiment.json").exists():
        raise SystemExit("Đã có lần chạy; dùng thư mục mới để giữ kết quả.")
    manifest = read_json(ROOT / "evaluation-manifest.json")
    for item in manifest["files"].values():
        assert file_hash(item["path"]) == item["sha256"]
    source_path = manifest["source_manifest"]
    assert file_hash(source_path) == manifest["source_manifest_sha256"]
    corpus, index, store = load_index(source_path)
    queries = read_jsonl(ROOT / "queries.jsonl")
    answers = {a["query_id"]: a for a in read_jsonl(ROOT / "answers.jsonl")}
    valid_ids = set(index["image_ids"])
    records = read_jsonl(corpus["files"]["records"]["path"])
    groups = defaultdict(set)
    image_groups = defaultdict(set)
    for r in records:
        if r.get("download_status") == "success":
            image_groups[r["image_id"]].add(r["split_group"])
    assert len(answers) == len(queries) == len({q["query_id"] for q in queries})
    for q in queries:
        assert q["answerable"] in (True, False, None)
        assert q["type"] in ("single", "multi-target", "multi-hop")
        for target in answers[q["query_id"]]["targets"]:
            assert set(target["image_ids"]) <= valid_ids
            assert 1 <= target["required"] <= len(set(target["image_ids"]))
            for iid in target["image_ids"]:
                for group in image_groups[iid]:
                    if q["split"] in ("dev", "test"):
                        groups[group].add(q["split"])
    assert all(len(splits) == 1 for splits in groups.values())
    options = manifest["evaluation"]
    model, processor = load_encoder(
        index["config"]["model"],
        index["config"]["revision"],
        Path("var/models"),
        options["threads"],
    )
    assert processor_hash(processor) == index["processor_sha256"]
    keyword, _ = load_keyword_index(corpus, "var/hybrid-v1/keyword-index", 1.2, 0.75)
    write_json(
        OUTPUT / "experiment.json",
        {
            "manifest_sha256": file_hash(ROOT / "evaluation-manifest.json"),
            "vector_index_sha256": index["index_sha256"],
            "keyword_index_sha256": file_hash("var/hybrid-v1/keyword-index/index.json"),
            "script_sha256": file_hash(Path(__file__)),
            "config": options,
            "quality_tier": manifest["quality_tier"],
            "index_reuse": (
                "Same source corpus, image order, hashes, model and preprocessing verified."
            ),
            "caches": False,
            "timing_excludes_model_and_index_loading": True,
        },
    )

    def retrieve(text, method):
        count = options["candidates"] if method == "hybrid" else options["top_k"]
        dense, sparse = [], []
        if method != "keyword":
            encoded = encode_text(text, model, processor)
            dense = store.search(encoded, count, set(index["image_ids"]))
        if method != "vector":
            sparse = keyword_search(text, keyword, count)
        if method == "hybrid":
            return fuse_rankings(dense, sparse, options["top_k"], options["rrf_k"])
        return sparse if method == "keyword" else dense

    summary = {}
    for method in options["methods"]:
        print("Running", method, flush=True)
        retrieve(queries[0]["text"], method)
        timings, predictions = [], {}
        rng = random.Random(options["seed"])
        for round_number in range(options["rounds"]):
            order = list(queries)
            rng.shuffle(order)
            for q in order:
                start = time.perf_counter()
                results = retrieve(q["text"], method)
                timings.append(
                    {
                        "query_id": q["query_id"],
                        "round": round_number + 1,
                        "latency_ms": (time.perf_counter() - start) * 1000,
                    }
                )
                if q["query_id"] in predictions:
                    assert predictions[q["query_id"]]["results"] == results
                predictions[q["query_id"]] = {"query_id": q["query_id"], "results": results}
        scores = []
        for q in queries:
            if q["answerable"] is not True:
                continue
            row = score_query(q, answers[q["query_id"]], predictions[q["query_id"]]["results"])
            row["intent_id"] = q["intent_id"]
            row["report_group"] = q["report_group"]
            row["evaluation_suite"] = q["evaluation_suite"]
            scores.append(row)
        grouped = defaultdict(list)
        for row in scores:
            grouped[f"{row['split']}/{row['type']}/{row['report_group']}"].append(row)
        report = {}
        for key, rows in grouped.items():
            families = defaultdict(list)
            for row in rows:
                families[row["intent_id"]].append(row)
            report[key] = {"queries": len(rows), "families": len(families)}
            for metric in METRICS:
                report[key][metric] = float(
                    np.mean([np.mean([r[metric] for r in family]) for family in families.values()])
                )
            ids = {r["query_id"] for r in rows}
            ms = [t["latency_ms"] for t in timings if t["query_id"] in ids]
            report[key]["p50_ms"] = float(np.percentile(ms, 50))
            report[key]["p95_ms"] = float(np.percentile(ms, 95))
        destination = OUTPUT / method
        write_jsonl(
            destination / "predictions.jsonl", [predictions[q["query_id"]] for q in queries]
        )
        write_jsonl(destination / "query-scores.jsonl", scores)
        write_jsonl(destination / "timings.jsonl", timings)
        write_json(destination / "report.json", report)
        paths = {r["image_id"]: r["local_path"] for r in corpus["images"]}
        for kind in ("single", "multi-target", "multi-hop"):
            sections = []
            for q in queries:
                if q["type"] != kind:
                    continue
                truth = {i for t in answers[q["query_id"]]["targets"] for i in t["image_ids"]}
                cards = []
                for rank, result in enumerate(predictions[q["query_id"]]["results"], 1):
                    iid = result["image_id"]
                    label = "Nhãn dương đã biết" if iid in truth else "Chưa có nhãn dương"
                    uri = Path(paths[iid]).resolve().as_uri()
                    cards.append(
                        f'<figure><img loading="lazy" src="{uri}"><figcaption>#{rank} · {label}<br>{iid}</figcaption></figure>'
                    )
                sections.append(
                    f'<section id="{q["query_id"]}"><h2>{q["query_id"]} · {q["split"]} · {q["report_group"]}</h2><p>{html.escape(q["text"])}</p><p>answerable={q["answerable"]}</p><div>'
                    + "".join(cards)
                    + "</div></section>"
                )
            page = '<meta charset="utf-8"><style>body{font:16px system-ui}section{border-bottom:2px solid #aaa;padding:20px}section div{display:flex;flex-wrap:wrap}figure{width:210px;margin:8px}img{width:210px;height:160px;object-fit:contain}figcaption{overflow-wrap:anywhere;font-size:12px}</style>'
            (destination / f"results-{kind}.html").write_text(page + "".join(sections))
        summary[method] = report
        print(method, report, flush=True)
    write_json(OUTPUT / "comparison.json", summary)
    lines = [
        "# Baseline trên toàn bộ v2 — nhãn ứng viên",
        "",
        "400 câu được truy vấn; 356 câu có nhãn dương được chấm, 42 unknown không chấm.",
        "Corpus 1.886 ảnh; test đã từng được xem. Chấm known positives, không chấm precision.",
        "Không dùng kết quả để chọn câu hoặc tune RRF. RRF chuẩn 1:1, k=60, candidates=100.",
        "",
        (
            "| Split/loại | Phương pháp | Số câu | Known Recall@10 | "
            "Known nDCG@10 | Đủ mục tiêu@10 | p50 ms |"
        ),
        "|---|---|---:|---:|---:|---:|---:|",
    ]
    for key in sorted(summary["vector"]):
        for method, report in summary.items():
            r = report[key]
            lines.append(
                f"| {key} | {method} | {r['queries']} | "
                f"{r[METRICS[0]]:.3f} | {r[METRICS[1]]:.3f} | "
                f"{r[METRICS[2]]:.3f} | {r['p50_ms']:.1f} |"
            )
    lines += ["", "## Giới hạn", "", *["- " + x for x in manifest["limitations"]]]
    (OUTPUT / "comparison.md").write_text("\n".join(lines) + "\n")
    print("Saved", OUTPUT / "comparison.md", flush=True)


if __name__ == "__main__":
    main()
