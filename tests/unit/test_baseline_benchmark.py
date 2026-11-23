import copy

import pytest

from image_search.baseline.benchmark import (
    draft_benchmark,
    load_manifest,
    validate_benchmark,
)
from image_search.baseline.utils import read_jsonl, write_json, write_jsonl


def sample_benchmark():
    records, queries, answers = [], [], []
    for split in ["dev", "test"]:
        for entity in ["a", "b"]:
            for index in [1, 2]:
                name = f"{split}-{entity}-{index}"
                records.append(
                    {
                        "record_id": name,
                        "entity_id": f"{split}-{entity}",
                        "entity_name": name,
                        "image_id": name,
                        "download_status": "success",
                        "local_path": "/tmp/unused",
                        "mo_ta": "Mô tả nguồn",
                    }
                )
        for kind in ["single", "multi-target", "multi-hop"]:
            qid = f"{split}-{kind}"
            queries.append(
                {
                    "query_id": qid,
                    "text": "Câu hỏi đã kiểm tra",
                    "type": kind,
                    "split": split,
                    "answerable": True,
                    "synthetic": False,
                    "reviewed": True,
                }
            )
            targets = [{"image_ids": [f"{split}-a-2"], "required": 1}]
            if kind == "multi-target":
                targets.append({"image_ids": [f"{split}-b-1"], "required": 1})
            evidence = [
                {"record_id": f"{split}-a-1", "role": "bridge", "description": "Gợi ý"},
                {"record_id": f"{split}-a-2", "role": "target", "description": "Đích"},
            ]
            answers.append(
                {
                    "query_id": qid,
                    "targets": targets,
                    "evidence": evidence if kind == "multi-hop" else [],
                }
            )
    queries.append(
        {
            "query_id": "none",
            "text": "Không có trong kho",
            "type": "single",
            "split": "dev",
            "answerable": False,
            "synthetic": True,
            "reviewed": True,
        }
    )
    answers.append({"query_id": "none", "targets": [], "verification": "Đã xem toàn kho"})
    return records, queries, answers


def test_valid_benchmark_has_all_types_and_verified_no_answer():
    validate_benchmark(*sample_benchmark())


@pytest.mark.parametrize(
    "problem",
    [
        "unknown-image",
        "leakage",
        "missing-target",
        "draft",
        "missing-evidence",
        "duplicate-id",
        "unverified-no-answer",
    ],
)
def test_invalid_benchmark_is_rejected(problem):
    records, queries, answers = copy.deepcopy(sample_benchmark())
    if problem == "unknown-image":
        answers[0]["targets"][0]["image_ids"] = ["unknown"]
    elif problem == "leakage":
        records[4]["entity_id"] = "dev-a"
    elif problem == "missing-target":
        answers[1]["targets"] = []
    elif problem == "draft":
        queries[0]["reviewed"] = False
    elif problem == "missing-evidence":
        answers[2]["evidence"] = []
    elif problem == "duplicate-id":
        queries.append(queries[0])
    else:
        answers[-1]["verification"] = ""
    with pytest.raises(ValueError):
        validate_benchmark(records, queries, answers)


def test_draft_requires_manual_review_and_never_overwrites_labels(tmp_path):
    records, _, _ = sample_benchmark()
    source = tmp_path / "records.jsonl"
    write_jsonl(source, records)
    draft_benchmark(source, tmp_path, per_type=1)
    queries = read_jsonl(tmp_path / "queries.jsonl")
    assert all(q["reviewed"] is False for q in queries)
    assert {q["type"] for q in queries} == {"single", "multi-target", "multi-hop"}
    assert (tmp_path / "catalog.html").exists()
    with pytest.raises(ValueError, match="Đã có file nhãn"):
        draft_benchmark(source, tmp_path)


def test_manifest_detects_changed_source(tmp_path):
    source = tmp_path / "source.csv"
    source.write_text("changed")
    manifest = tmp_path / "benchmark.json"
    from image_search.baseline.benchmark import RULES

    write_json(
        manifest,
        {
            "version": 1,
            "rules": RULES,
            "images": [],
            "files": {"csv": {"path": str(source), "sha256": "old"}},
        },
    )
    with pytest.raises(ValueError, match="Benchmark đã thay đổi"):
        load_manifest(manifest)
