"""Kiểm tra kết quả v2 và tạo trang vào xem theo phương pháp/loại câu."""

from collections import Counter
from pathlib import Path

from image_search.baseline.evaluate import score_query
from image_search.baseline.utils import file_hash, read_json, read_jsonl, write_json

ROOT = Path("var/evaluation-v2-all")
SOURCE = Path("var/benchmark-v2")


def main():
    queries = read_jsonl(SOURCE / "queries.jsonl")
    answers = {a["query_id"]: a for a in read_jsonl(SOURCE / "answers.jsonl")}
    experiment = read_json(ROOT / "experiment.json")
    manifest = read_json(SOURCE / "evaluation-manifest.json")
    assert file_hash(SOURCE / "evaluation-manifest.json") == experiment["manifest_sha256"]
    assert file_hash(ROOT / "executed-script.py") == experiment["script_sha256"]
    for item in manifest["files"].values():
        assert file_hash(item["path"]) == item["sha256"]
    links, negatives = [], {}
    for method in ("vector", "keyword", "hybrid"):
        preds = read_jsonl(ROOT / method / "predictions.jsonl")
        prediction = {p["query_id"]: p for p in preds}
        scores = {s["query_id"]: s for s in read_jsonl(ROOT / method / "query-scores.jsonl")}
        timings = read_jsonl(ROOT / method / "timings.jsonl")
        assert len(prediction) == len(preds) == 400
        assert set(prediction) == {q["query_id"] for q in queries}
        assert len(scores) == 356 and len(timings) == 1200
        assert all(n == 3 for n in Counter(t["query_id"] for t in timings).values())
        for q in queries:
            if q["answerable"] is True:
                actual = score_query(
                    q, answers[q["query_id"]], prediction[q["query_id"]]["results"]
                )
                assert all(scores[q["query_id"]][k] == v for k, v in actual.items())
        negatives[method] = [
            {"query_id": q["query_id"], "rejected": not prediction[q["query_id"]]["results"]}
            for q in queries
            if q["answerable"] is False
        ]
        for kind in ("single", "multi-target", "multi-hop"):
            page = ROOT / method / f"results-{kind}.html"
            text = page.read_text()
            assert text.count("<section id=") == sum(q["type"] == kind for q in queries)
            links.append(f'<li><a href="{method}/results-{kind}.html">{method} — {kind}</a></li>')
    (ROOT / "index.html").write_text(
        '<meta charset="utf-8"><h1>Kết quả tìm kiếm toàn bộ v2</h1>'
        "<p>400 câu, top-10 của 3 phương pháp. Nhãn ứng viên; ảnh chưa có nhãn dương "
        "không mặc nhiên sai. Multi-hop chấm tìm ảnh đích, chưa chứng minh suy luận.</p>"
        "<ul>" + "".join(links) + "</ul>"
    )
    write_json(ROOT / "negative-results.json", negatives)
    write_json(
        ROOT / "verification.json",
        {
            "status": "passed",
            "queries_per_method": 400,
            "scored_positives_per_method": 356,
            "unknown_not_scored": 42,
            "catalog_negatives_reported_separately": 2,
            "timings_per_method": 1200,
            "gallery_pages": 9,
            "hashes_match": True,
            "all_scores_recomputed": True,
        },
    )
    print("PASS: 1200 predictions, 3600 timings, 1068 scores, 9 galleries.")


if __name__ == "__main__":
    main()
