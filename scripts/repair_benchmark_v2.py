"""Sửa draft v2 từ snapshot; không tự duyệt nhãn hoặc chạy benchmark."""

import copy
import hashlib
import json
import re
import unicodedata
from collections import Counter, defaultdict
from pathlib import Path

from image_search.baseline.utils import file_hash, read_jsonl, write_json, write_jsonl

SOURCE = Path("var/benchmark-v2-before-fixes")
DEST = Path("var/benchmark-v2")


def target(rows):
    return {"image_ids": sorted({r["image_id"] for r in rows}), "required": 1}


def main():
    if (DEST / "label-cleanup-summary.json").exists():
        raise SystemExit("Đã sửa chất lượng nhãn; không ghi đè bằng bước sửa cấu trúc.")
    queries = read_jsonl(SOURCE / "queries.jsonl")
    answers = read_jsonl(SOURCE / "answers.jsonl")
    records = read_jsonl(SOURCE / "downloaded-records.jsonl")
    if any(q["reviewed"] for q in read_jsonl(DEST / "queries.jsonl")):
        raise SystemExit("Đã có nhãn được duyệt; không ghi đè.")
    rows = [r for r in records if r.get("download_status") == "success"]
    by_record = {r["record_id"]: r for r in rows}
    by_image = defaultdict(list)
    entities = defaultdict(list)
    for r in rows:
        entities[r["entity_id"]].append(r)
        by_image[r["image_id"]].append(r)
    group_splits = {}
    for q, a in zip(queries, answers, strict=True):
        if q["split"] not in ("dev", "test"):
            continue
        for t in a["targets"]:
            for iid in t["image_ids"]:
                for r in by_image[iid]:
                    group = r["split_group"]
                    assert group_splits.get(group, q["split"]) == q["split"]
                    group_splits[group] = q["split"]
    aliases = {
        "Ga Hà Nội cửa hàng Lê Duẩn": "Ga Hà Nội trên đường Lê Duẩn",
        "An táng tại Nghĩa trang Liệt sĩ Quốc gia Vị Xuyên Hà Giang": (
            "Nghĩa trang Liệt sĩ Quốc gia Vị Xuyên, Hà Giang"
        ),
    }
    for q in queries:
        if q["category"] == "entity_lookup":
            q["text"] = q["text"].replace("vài tấm", "một ảnh")
        if "corpus" in q["tags"]:
            q["text"] = q["text"].replace("vài tấm", "một ảnh")
        for raw, name in aliases.items():
            q["text"] = q["text"].replace(raw, name)

    # Mở rộng ứng viên đúng với phép OR trong câu hỏi, không coi caption là gold.
    rail = next(q for q in queries if q["query_id"] == "v2-q0136")
    rail_rows = [r for r in rows if re.search(r"đường ray|sân ga", r["mo_ta"].lower())]
    a = answers[queries.index(rail)]
    a["targets"] = [target(rail_rows)]
    a["source_record_ids"] = [r["record_id"] for r in rail_rows]
    a["verification"] = "Pool đường ray HOẶC sân ga; còn cần xem ảnh và tìm ảnh thiếu caption."
    assert "csv-175" in a["source_record_ids"]

    # Quota riêng, không để nhóm đầu lấy hết 24 chỗ. Ngày/đêm có ít nhóm hơn.
    pairs = [
        ("front_interior", "mặt tiền", "bên trong", 7),
        ("day_night", "ban ngày", "ban đêm", 4),
        ("wide_close", "toàn cảnh", "cận cảnh", 7),
        ("render_construction", "phối cảnh", "thi công", 6),
    ]
    slots = [i for i, q in enumerate(queries) if q["category"] == "multiple_conditions"]
    replacements = []
    for name, left, right, quota in pairs:
        seen = set()
        for _entity, rs in sorted(entities.items()):
            group = rs[0]["split_group"]
            if group in seen or group not in group_splits:
                continue
            left_rows = [r for r in rs if left in r["mo_ta"].lower()]
            rr = [r for r in rs if right in r["mo_ta"].lower()]
            common = {r["image_id"] for r in left_rows} & {r["image_id"] for r in rr}
            left_rows = [r for r in left_rows if r["image_id"] not in common]
            rr = [r for r in rr if r["image_id"] not in common]
            if not left_rows or not rr:
                continue
            seen.add(group)
            replacements.append((name, left, right, rs, left_rows, rr))
            if len(seen) == quota:
                break
        assert len(seen) == quota, (name, len(seen), quota)
    for i, (name, left, right, rs, left_rows, rr) in zip(slots, replacements, strict=True):
        q, a = queries[i], answers[i]
        display = aliases.get(rs[0]["entity_name"], rs[0]["entity_name"])
        q.update(
            text=f"Với {display}, tìm một ảnh {left} và một ảnh {right}.",
            split=group_splits[rs[0]["split_group"]],
            intent_id=f"views-{rs[0]['split_group']}-{name}",
            tags=["2_targets", "same_entity", "view_or_condition", name],
        )
        a.update(
            targets=[target(left_rows), target(rr)],
            evidence=[],
            source_record_ids=[r["record_id"] for r in left_rows + rr],
            verification="Ứng viên theo hai điều kiện; cần kiểm tra ảnh từng mục tiêu.",
        )

    # 4 họ mỗi loại mỗi split, 2 biến thể/họ => 24 dev và 24 test.
    slots = [i for i, q in enumerate(queries) if q["category"] == "robustness"]
    selected = []
    for kind in ("single", "multi-target", "multi-hop"):
        for split in ("dev", "test"):
            seen = set()
            for q, a in zip(queries, answers, strict=True):
                if (
                    q["category"] == "robustness"
                    or q["type"] != kind
                    or q["split"] != split
                    or q["answerable"] is not True
                ):
                    continue
                if q["intent_id"] in seen:
                    continue
                seen.add(q["intent_id"])
                selected.append((q, a))
                if len(seen) == 4:
                    break
            assert len(seen) == 4
    slot_index = 0
    for number, (base, base_answer) in enumerate(selected):
        plain = unicodedata.normalize("NFKD", base["text"].replace("đ", "d").replace("Đ", "D"))
        plain = "".join(c for c in plain if not unicodedata.combining(c))
        text = base["text"]
        variant = "synonym"
        changed = (
            text.replace("ảnh", "hình", 1) if "ảnh" in text else text.replace("hình", "ảnh", 1)
        )
        # Biến thể viết tắt và lỗi gõ tên, bên cạnh không dấu/từ đồng nghĩa.
        if number % 3 == 0:
            for word, short in [
                ("Thành phố", "TP."),
                ("thành phố", "TP."),
                ("Sân vận động", "SVĐ"),
                ("sân vận động", "SVĐ"),
                ("Công viên", "CV"),
                ("công viên", "CV"),
            ]:
                if word in text:
                    changed, variant = text.replace(word, short, 1), "abbreviation"
                    break
        elif number % 3 == 1:
            words = re.findall(r"\b[A-ZĐ][a-zà-ỹ]{3,}\b", text)
            words = [w for w in words if w not in ("Cho", "Tìm", "Mình", "Giúp")]
            if words:
                word = words[-1]
                changed = text.replace(word, word[:1] + word[2:3] + word[1:2] + word[3:], 1)
                variant = "entity_typo"
        if changed == text:
            changed = "Bạn giúp mình nhé: " + text
            variant = "conversational"
        for form, value in [("no_accents", plain), (variant, changed)]:
            i = slots[slot_index]
            qid = queries[i]["query_id"]
            queries[i] = dict(
                copy.deepcopy(base),
                query_id=qid,
                text=value,
                category="robustness",
                variant=form,
                origin="paraphrase",
                canonical_query_id=base["query_id"],
                tags=["robustness", form],
            )
            answers[i] = dict(copy.deepcopy(base_answer), query_id=qid)
            slot_index += 1

    # Tách mục đích đánh giá; chưa xác nhận multi-hop chỉ là relational candidate.
    for q, a in zip(queries, answers, strict=True):
        q["evaluation_ready"] = False
        q["reviewed"] = False
        q["test_exposure"] = "previously_inspected_corpus"
        q["retrieval_track"] = "named_or_metadata"
        if q["type"] == "multi-hop" and q["category"] != "exploratory":
            q["reasoning_status"] = "unverified_bridge_necessity"
            q["evaluation_suite"] = "relational_review"
        elif q["answerable"] is False:
            q["evaluation_suite"] = "catalog_absence"
        elif q["category"] == "exploratory":
            behavior = q["expected_behavior"]
            if behavior in ("clarify_criteria", "ask_clarification", "review_ambiguity"):
                q["evaluation_suite"] = "clarification"
            elif behavior.startswith("needs_"):
                q["evaluation_suite"] = "missing_context"
            elif behavior in ("metadata_not_available", "relation_not_in_catalog"):
                q["evaluation_suite"] = "unsupported_information"
            else:
                q["evaluation_suite"] = "answerability_review"
        elif "corpus" in q["tags"]:
            q["evaluation_suite"] = "global_visual"
            q["split"] = "unassigned"
            q["proposed_split"] = None
        else:
            q["evaluation_suite"] = "entity_retrieval"
        if q["category"] in ("visual_description", "multiple_conditions"):
            q["retrieval_track"] = "visual_from_metadata_needs_blind_rewrite"
        if q["category"] == "robustness":
            q["report_group"] = "robustness"
        else:
            q["report_group"] = "canonical"
        q["label_status"] = "unresolved" if q["answerable"] is None else "candidate"
        a["exhaustive"] = False
        a["label_basis"] = "approved_metadata_candidate"
        a["known_recall_at_10_ceiling"] = [min(10 / len(t["image_ids"]), 1) for t in a["targets"]]
    # Hai shortcut rõ ràng: bỏ bridge dư thừa, chấm như truy vấn một mục tiêu.
    edits = {
        "v2-q0316": "Tìm bản đồ mặt bằng có các tòa Ruby tại Vinhomes Ocean Park.",
        "v2-q0318": "Tìm ảnh máy cắt cỏ đang làm việc trên sân Thống Nhất.",
    }
    for q, a in zip(queries, answers, strict=True):
        if q["query_id"] in edits:
            # Dùng tên nguồn cho bản đồ, tránh thêm danh tính ngoài bằng chứng.
            if q["query_id"] == "v2-q0316":
                row = by_record[a["source_record_ids"][0]]
                edits[q["query_id"]] = (
                    f"Tìm bản đồ mặt bằng có các tòa Ruby tại {row['entity_name']}."
                )
            q.update(
                text=edits[q["query_id"]],
                type="single",
                reasoning_status="reclassified_direct_lookup",
                evaluation_suite="entity_retrieval",
            )
            q["tags"] = ["direct_lookup", "bridge_removed"]
            a["evidence"] = [e for e in a["evidence"] if e["role"] == "target"]
            a["verification"] += " Đã bỏ bridge không cần thiết; còn phải pool các ảnh đích khác."

    # Mỗi họ có tổng trọng số 1 trong từng bộ/nhóm báo cáo.
    counts = Counter((q["evaluation_suite"], q["report_group"], q["intent_id"]) for q in queries)
    by_query = {q["query_id"]: (q, a) for q, a in zip(queries, answers, strict=True)}
    for q, a in zip(queries, answers, strict=True):
        key = (q["evaluation_suite"], q["report_group"], q["intent_id"])
        q["family_weight"] = 1 / counts[key]
        if q["category"] == "robustness":
            base, base_answer = by_query[q["canonical_query_id"]]
            assert q["split"] == base["split"]
            assert a["targets"] == base_answer["targets"]
        if q["query_id"] == "v2-q0136":
            a["visual_checks"] = [
                {
                    "record_id": "csv-175",
                    "reviewer": "assistant_visual_inspection",
                    "matches": True,
                    "note": "Ảnh có sân ga, đường ray và đoàn tàu xanh.",
                    "independent_review": False,
                }
            ]
    write_json(
        DEST / "evaluation-policy.json",
        {
            "status": "draft_policy_not_implemented_in_v1_evaluator",
            "aggregate_by": ["evaluation_suite", "report_group", "intent_id"],
            "weight_field": "family_weight",
            "primary_metrics": ["known_ndcg@10", "all_targets_complete@10"],
            "secondary_metric": "known_recall@10_with_ceiling",
            "unjudged_is_negative": False,
            "precision_requires_all_top_k_judged": True,
            "global_visual": "Separate shared-corpus suite; no entity-disjoint claim.",
            "relational_review": "Excluded from reasoning claims until bridge audit.",
            "unknown_answerability": "Exclude from retrieval metrics; never count as negative.",
            "freeze_requires": ["independent_review", "pool_labels", "resolve_final_splits"],
        },
    )

    # Kiểm tra mọi alias của một ảnh, cả bridge và target, không chỉ một record đại diện.
    splits = defaultdict(set)
    families = defaultdict(set)
    for q, a in zip(queries, answers, strict=True):
        assert q["query_id"] == a["query_id"]
        families[q["intent_id"]].add(q["split"])
        for t in a["targets"]:
            assert 1 <= t["required"] <= len(set(t["image_ids"]))
        if q["split"] not in ("dev", "test"):
            continue
        ids = {iid for t in a["targets"] for iid in t["image_ids"]}
        ids.update(by_record[e["record_id"]]["image_id"] for e in a["evidence"])
        for iid in ids:
            for r in by_image[iid]:
                splits[r["split_group"]].add(q["split"])
    assert all(len(s) == 1 for s in splits.values())
    assert all(len(s) == 1 for s in families.values())
    assert len({q["text"].casefold() for q in queries}) == len(queries) == 400
    write_jsonl(DEST / "queries.jsonl", queries)
    write_jsonl(DEST / "answers.jsonl", answers)
    coverage = {
        "status": "repaired_draft_not_gold",
        "total_queries": len(queries),
        "intent_families": len(families),
        "reviewed_queries": 0,
        "source_records_sha256": file_hash(SOURCE / "downloaded-records.jsonl"),
        "v1_queries_sha256": file_hash("var/benchmark-v1/queries.jsonl"),
    }
    for field in ("category", "type", "split", "evaluation_suite", "variant"):
        coverage[field + "_counts"] = dict(Counter(q[field] for q in queries))
    coverage["condition_counts"] = dict(
        Counter(q["tags"][-1] for q in queries if q["category"] == "multiple_conditions")
    )
    coverage["robustness_counts"] = dict(
        Counter(f"{q['split']}/{q['type']}" for q in queries if q["category"] == "robustness")
    )
    coverage["entities_with_source_evidence"] = len(
        {by_record[rid]["entity_id"] for a in answers for rid in a["source_record_ids"]}
    )
    write_json(DEST / "coverage.json", coverage)
    changes = []
    for old, new, old_a, new_a in zip(
        read_jsonl(SOURCE / "queries.jsonl"),
        queries,
        read_jsonl(SOURCE / "answers.jsonl"),
        answers,
        strict=True,
    ):
        changes.append(
            {
                "query_id": new["query_id"],
                "old_text": old["text"],
                "new_text": new["text"],
                "targets_changed": old_a["targets"] != new_a["targets"],
            }
        )
    write_jsonl(DEST / "repair-changes.jsonl", changes)
    write_json(
        DEST / "repair-provenance.json",
        {
            "source": str(SOURCE),
            "source_queries_sha256": file_hash(SOURCE / "queries.jsonl"),
            "source_answers_sha256": file_hash(SOURCE / "answers.jsonl"),
            "queries_sha256": file_hash(DEST / "queries.jsonl"),
            "answers_sha256": file_hash(DEST / "answers.jsonl"),
            "repair_script_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
            "independent_review": False,
        },
    )
    print(json.dumps(coverage, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
