"""Cách ly nhãn địa điểm thiếu tin cậy, giữ nguyên bằng chứng để duyệt lại."""

import copy
from collections import Counter, defaultdict
from pathlib import Path

from image_search.baseline.utils import file_hash, read_json, read_jsonl, write_json, write_jsonl

SOURCE = Path("var/benchmark-v2-before-label-cleanup")
DEST = Path("var/benchmark-v2")
UNCERTAIN = ("có thể là", "có lẽ", "dường như", "chưa xác định", "không rõ")
# Cùng địa điểm nhưng khác cách đặt tên/phạm vi. Không suy ra từ split_group:
# nhóm split có thể đã gộp các địa điểm khác nhau vì dùng lại cùng ảnh.
SAME_PLACE_NAMES = (
    ("Bến xe Miền Tây",),
    ("Vinhomes Smart City",),
    ("Nghĩa trang Liệt sĩ Quốc gia Vị Xuyên",),
    ("Phát Diệm",),
    ("Cái Răng",),
    ("Lạch Tray",),
    ("Mỹ Đình",),
    ("Thống Nhất",),
)


def image_issues(rows):
    issues = []
    if any(any(term in r["mo_ta"].lower() for term in UNCERTAIN) for r in rows):
        issues.append("uncertain_source_identity")
    names = {r["entity_name"] for r in rows}
    same_place = any(
        all(any(term in name for term in terms) for name in names) for terms in SAME_PLACE_NAMES
    )
    if len({r["entity_id"] for r in rows}) > 1 and not same_place:
        issues.append("unresolved_cross_entity_image")
    return issues


def main():
    queries = read_jsonl(SOURCE / "queries.jsonl")
    answers = read_jsonl(SOURCE / "answers.jsonl")
    records = read_jsonl(SOURCE / "downloaded-records.jsonl")
    if any(q["reviewed"] for q in read_jsonl(DEST / "queries.jsonl")):
        raise SystemExit("Đã có nhãn được duyệt; không ghi đè.")
    rows = [r for r in records if r.get("download_status") == "success"]
    by_record = {r["record_id"]: r for r in rows}
    by_image = defaultdict(list)
    for r in rows:
        by_image[r["image_id"]].append(r)
    risks = {iid: image_issues(rs) for iid, rs in by_image.items()}
    risks = {iid: reasons for iid, reasons in risks.items() if reasons}
    changes = []
    for q, a in zip(queries, answers, strict=True):
        qid = q["query_id"]
        scoped = q["evaluation_suite"] != "global_visual"
        original = copy.deepcopy(a["targets"])
        excluded = []
        for index, t in enumerate(a["targets"]):
            for iid in t["image_ids"]:
                if iid in risks:
                    excluded.append(
                        {
                            "target_index": index,
                            "image_id": iid,
                            "reasons": risks[iid],
                            "quarantined": scoped,
                        }
                    )
            if scoped:
                t["image_ids"] = [iid for iid in t["image_ids"] if iid not in risks]
        bad_evidence = [e for e in a["evidence"] if by_record[e["record_id"]]["image_id"] in risks]
        insufficient = any(len(t["image_ids"]) < t["required"] for t in a["targets"])
        if scoped and (insufficient or bad_evidence):
            # Không hạ required, bỏ một mục tiêu hay gọi thiếu nhãn là câu âm.
            a["pending_targets"] = copy.deepcopy(a["targets"])
            a["pending_evidence"] = a["evidence"]
            a["targets"] = []
            a["evidence"] = []
            q["answerable"] = None
            q["label_status"] = "unresolved"
            q["expected_behavior"] = "verify_source_identity_and_relabel"
            q["label_review_reason"] = "insufficient_reliable_targets_or_evidence"
        if excluded or bad_evidence:
            a["label_quality_issues"] = excluded
            a["quarantined_evidence"] = bad_evidence
            a["verification"] += (
                " Đã cách ly ứng viên địa điểm thiếu tin cậy; ảnh bị cách ly chưa bị gán âm."
                if scoped
                else " Có ảnh chưa rõ địa điểm; giữ ứng viên thị giác toàn kho, cần duyệt nội dung."
            )
            changes.append(
                {
                    "query_id": qid,
                    "scoped": scoped,
                    "removed": excluded,
                    "answerable_after": q["answerable"],
                    "targets_before": original,
                    "targets_after": a["targets"],
                }
            )
        a["known_recall_at_10_ceiling"] = [min(10 / len(t["image_ids"]), 1) for t in a["targets"]]
        q["reviewed"] = False
        q["evaluation_ready"] = False
    # Câu gốc và biến thể phải cùng trạng thái/đáp án sau khi loại nhãn.
    lookup = {q["query_id"]: (q, a) for q, a in zip(queries, answers, strict=True)}
    for q, a in zip(queries, answers, strict=True):
        if q["category"] == "robustness":
            base, base_a = lookup[q["canonical_query_id"]]
            assert q["answerable"] == base["answerable"]
            assert a["targets"] == base_a["targets"]
        if q["answerable"] is True:
            assert a["targets"] and all(len(t["image_ids"]) >= t["required"] for t in a["targets"])
        if q["answerable"] is None:
            assert not a["targets"]
        if q["evaluation_suite"] != "global_visual":
            assert not any(iid in risks for t in a["targets"] for iid in t["image_ids"])
            assert not any(by_record[e["record_id"]]["image_id"] in risks for e in a["evidence"])
    write_jsonl(DEST / "queries.jsonl", queries)
    write_jsonl(DEST / "answers.jsonl", answers)
    write_jsonl(DEST / "label-cleanup-changes.jsonl", changes)
    write_jsonl(
        DEST / "image-label-issues.jsonl",
        [
            {
                "image_id": iid,
                "reasons": reasons,
                "records": [
                    {
                        "record_id": r["record_id"],
                        "entity_name": r["entity_name"],
                        "caption": r["mo_ta"],
                    }
                    for r in by_image[iid]
                ],
            }
            for iid, reasons in risks.items()
        ],
    )
    summary = {
        "status": "candidate_labels_cleaned_not_independently_verified",
        "flagged_images": len(risks),
        "affected_queries": len(changes),
        "removed_target_memberships": sum(x["quarantined"] for c in changes for x in c["removed"]),
        "newly_unresolved_queries": [
            q["query_id"]
            for old, q in zip(read_jsonl(SOURCE / "queries.jsonl"), queries, strict=True)
            if old["answerable"] is True and q["answerable"] is None
        ],
        "answerability_counts": dict(Counter(str(q["answerable"]) for q in queries)),
        "source_queries_sha256": file_hash(SOURCE / "queries.jsonl"),
        "source_answers_sha256": file_hash(SOURCE / "answers.jsonl"),
        "queries_sha256": file_hash(DEST / "queries.jsonl"),
        "answers_sha256": file_hash(DEST / "answers.jsonl"),
        "script_sha256": file_hash(Path(__file__)),
        "policy": "Quarantine is unjudged, not negative. Same-place aliases remain candidates.",
    }
    coverage = read_json(DEST / "coverage.json")
    coverage["status"] = summary["status"]
    coverage["answerability_counts"] = summary["answerability_counts"]
    coverage["newly_unresolved_queries"] = summary["newly_unresolved_queries"]
    coverage["source_evidence_includes_quarantined_records"] = True
    write_json(DEST / "coverage.json", coverage)
    write_json(DEST / "label-cleanup-summary.json", summary)
    print(summary)


if __name__ == "__main__":
    main()
