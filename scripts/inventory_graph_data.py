"""Kiểm kê toàn bộ dữ liệu nguồn/Qdrant để đề xuất graph; không đọc golden queries."""

import argparse
import csv
import re
import statistics
from collections import Counter, defaultdict
from pathlib import Path

from image_search.adapters.qdrant.metadata import name_key
from image_search.baseline.records import read_approved_records
from image_search.baseline.utils import file_hash, read_json, read_jsonl, write_json, write_jsonl
from image_search.baseline.vectors import load_index
from image_search.embedding.settings import EmbeddingSettings
from image_search.retrieval.settings import RetrievalSettings

# Chỉ đánh dấu chỗ cần đọc/duyệt, không biến từ khóa thành quan hệ graph.
CUES = {
    "location": r"tọa lạc|nằm tại|nằm ở|đặt tại|địa chỉ",
    "part_of": r"thuộc|nằm trong|một phần|khuôn viên",
    "brand": r"thương hiệu|nhãn hiệu|chuỗi cửa hàng",
    "near": r"gần|bên cạnh|đối diện|liền kề|giáp",
}
UNCERTAIN = r"có thể là|có lẽ|chưa xác định|không rõ"
ILLUSTRATION = r"phối cảnh|mô phỏng|minh họa"


def group_rows(rows, field):
    grouped = defaultdict(list)
    for row in rows:
        grouped[row[field]].append(row)
    return grouped


def find_relation_hints(rows, entities):
    hints, mentions = [], []
    names = {
        eid: [(name_key(name), name) for name in item["names"]] for eid, item in entities.items()
    }
    for row in rows:
        for field in ("entity_name", "mo_ta", "page_title"):
            value = row.get(field, "") or ""
            for kind, pattern in CUES.items():
                matches = list(re.finditer(r"\b(?:" + pattern + r")\b", value, re.I))
                if matches:
                    hints.append(
                        {
                            "record_id": row["record_id"],
                            "image_id": row.get("image_id"),
                            "entity_id": row["entity_id"],
                            "field": field,
                            "family": kind,
                            "matched_phrases": sorted({m.group() for m in matches}),
                            "source_text": value,
                            "page_url": row.get("page_url"),
                            "status": "text_cue_not_extracted_relation",
                        }
                    )
            normalized = " " + name_key(value) + " "
            for eid, variants in names.items():
                if eid == row["entity_id"]:
                    continue
                for key, name in variants:
                    if key and " " + key + " " in normalized:
                        mentions.append(
                            {
                                "record_id": row["record_id"],
                                "image_id": row.get("image_id"),
                                "subject_entity_id": row["entity_id"],
                                "mentioned_entity_id": eid,
                                "mentioned_name": name,
                                "field": field,
                                "source_text": value,
                                "page_url": row.get("page_url"),
                                "status": "name_match_not_extracted_relation",
                            }
                        )
                        break
    return hints, mentions


def summarize(payloads, rows, approved, downloaded):
    by_entity = group_rows(rows, "entity_id")
    by_image = group_rows(rows, "image_id")
    entities = {
        eid: {
            "entity_id": eid,
            "names": sorted({r["entity_name"] for r in rs}),
            "source_labels": sorted({r["leaf_label"] for r in rs}),
            "records": len(rs),
            "images": len({r["image_id"] for r in rs}),
            "source_pages": len({r["page_url"] for r in rs if r.get("page_url")}),
        }
        for eid, rs in sorted(by_entity.items())
    }
    normalized_names = defaultdict(set)
    for eid, item in entities.items():
        for name in item["names"]:
            normalized_names[name_key(name)].add(eid)
    fields = sorted({key for row in rows for key in row})
    field_profile = {
        field: {
            "missing": sum(row.get(field) in (None, "") for row in rows),
            "distinct_nonempty": len(
                {str(row[field]) for row in rows if row.get(field) not in (None, "")}
            ),
        }
        for field in fields
    }
    labels = [
        {
            "source_label": label,
            "records": len(rs),
            "entities": len({r["entity_id"] for r in rs}),
            "images": len({r["image_id"] for r in rs}),
        }
        for label, rs in sorted(group_rows(rows, "leaf_label").items())
    ]
    shared = [
        {
            "image_id": iid,
            "entity_ids": sorted({r["entity_id"] for r in rs}),
            "record_ids": [r["record_id"] for r in rs],
            "entity_names": sorted({r["entity_name"] for r in rs}),
            "captions": sorted({r["mo_ta"] for r in rs}),
        }
        for iid, rs in sorted(by_image.items())
        if len({r["entity_id"] for r in rs}) > 1
    ]
    hints, mentions = find_relation_hints(rows, entities)
    approved_entities = {r["entity_id"] for r in approved}
    missing_entities = sorted(approved_entities - set(entities))
    missing_records = [r for r in approved if r["record_id"] not in {x["record_id"] for x in rows}]
    sizes = [item["images"] for item in entities.values()]
    summary = {
        "indexed": {
            "points": len(payloads),
            "records": len(rows),
            "entities": len(entities),
            "source_labels": len(labels),
            "source_pages": len({r["page_url"] for r in rows if r.get("page_url")}),
            "image_domains": len({r["image_domain"] for r in rows if r.get("image_domain")}),
            "image_entity_links": sum(len(p["entity_ids"]) for p in payloads.values()),
            "record_category_links": sum(bool(r.get("leaf_label")) for r in rows),
            "entity_category_links": len({(r["entity_id"], r["leaf_label"]) for r in rows}),
            "record_page_links": sum(bool(r.get("page_url")) for r in rows),
            "entity_images": {
                "min": min(sizes),
                "median": statistics.median(sizes),
                "max": max(sizes),
            },
        },
        "source": {
            "approved_records": len(approved),
            "approved_entities": len(approved_entities),
            "download_statuses": dict(Counter(r["download_status"] for r in downloaded)),
            "missing_approved_records": len(missing_records),
            "missing_entity_ids": missing_entities,
            "missing_entities": [
                {
                    "entity_id": eid,
                    "names": sorted({r["entity_name"] for r in approved if r["entity_id"] == eid}),
                }
                for eid in missing_entities
            ],
        },
        "quality": {
            "shared_images": len(shared),
            "entities_with_multiple_names": sum(len(e["names"]) > 1 for e in entities.values()),
            "entities_with_multiple_source_labels": sum(
                len(e["source_labels"]) > 1 for e in entities.values()
            ),
            "normalized_name_collisions": [
                {"normalized_name": key, "entity_ids": sorted(ids)}
                for key, ids in sorted(normalized_names.items())
                if len(ids) > 1
            ],
            "uncertain_caption_records": sum(
                bool(re.search(UNCERTAIN, r["mo_ta"], re.I)) for r in rows
            ),
            "illustration_caption_records": sum(
                bool(re.search(ILLUSTRATION, r["mo_ta"], re.I)) for r in rows
            ),
        },
        "fields": field_profile,
        "relation_hints": {
            kind: {
                "records": len({h["record_id"] for h in hints if h["family"] == kind}),
                "entities": len({h["entity_id"] for h in hints if h["family"] == kind}),
            }
            for kind in CUES
        },
        "cross_entity_name_mentions": {
            "evidence_rows": len(mentions),
            "records": len({m["record_id"] for m in mentions}),
            "directed_entity_pairs": len(
                {(m["subject_entity_id"], m["mentioned_entity_id"]) for m in mentions}
            ),
        },
        "structured_entity_relation_columns": [],
        "limitations": [
            "Kiểm kê toàn snapshot hiện có, không phải toàn bộ dữ liệu sản phẩm tương lai.",
            "Không đọc query/answer golden set; không gọi LLM, không sửa Qdrant hoặc pipeline.",
            "Theo quyết định người dùng: tin metadata approve=yes, không xác minh nguồn bên ngoài.",
            "Đếm từ khóa/khớp tên chưa phải trích xuất đúng chủ thể, quan hệ và đối tượng.",
            "Ảnh chung không chứng minh hai entity là một hoặc có quan hệ nghiệp vụ.",
            "Nhãn dài có tên địa phương/ví dụ; không gán các địa phương đó cho mọi entity.",
        ],
    }
    return summary, entities, labels, shared, hints, mentions, missing_records


def write_report(path, summary):
    indexed, source, quality = summary["indexed"], summary["source"], summary["quality"]
    lines = [
        "# Kiểm kê dữ liệu cho graph",
        "",
        "Toàn bộ snapshot Qdrant hiện tại và toàn CSV nguồn được quét; không dùng golden queries.",
        "",
        f"- Qdrant: {indexed['points']} ảnh, {indexed['records']} record, "
        f"{indexed['entities']} entity, {indexed['source_labels']} nhãn nguồn, "
        f"{indexed['source_pages']} trang nguồn.",
        f"- Nguồn: {source['csv_rows']} dòng CSV; {source['approved_records']} record "
        f"approve=yes thuộc {source['approved_entities']} entity.",
        f"- Toàn CSV thô: {source['raw_entities']} entity, {source['raw_source_labels']} nhãn. "
        "Các dòng approve=no không được coi là dữ liệu đã duyệt để dựng graph.",
        f"- Chưa có ảnh trong Qdrant: {source['missing_approved_records']} record được duyệt, "
        f"{len(source['missing_entity_ids'])} entity chưa có ảnh nào.",
        f"- {quality['shared_images']} ảnh có nhiều entity; "
        f"{quality['uncertain_caption_records']} record có từ ngữ chưa chắc chắn; "
        f"{quality['illustration_caption_records']} record nhắc phối cảnh/mô phỏng/minh họa.",
        "",
        "## Độ đầy đủ trường",
        "",
        "| Trường | Thiếu | Giá trị khác nhau |",
        "|---|---:|---:|",
    ]
    for field, stats in summary["fields"].items():
        lines.append(f"| {field} | {stats['missing']} | {stats['distinct_nonempty']} |")
    lines += [
        "",
        "## Dấu hiệu quan hệ trong metadata đang có ảnh",
        "",
        "| Nhóm từ khóa | Record | Entity |",
        "|---|---:|---:|",
    ]
    for kind, count in summary["relation_hints"].items():
        lines.append(f"| {kind} | {count['records']} | {count['entities']} |")
    lines += [
        "",
        "Nhóm từ khóa có thể chồng lấp và có false positive; không dùng làm độ phủ graph.",
        "",
        "## Kết luận",
        "",
        "Liên kết có cấu trúc hiện có: record → ảnh/entity/nhãn/trang nguồn.",
        "Chưa có cột quan hệ entity–entity. Neo4j không tự bổ sung các fact còn thiếu.",
        "Giữ entity_id để ánh xạ Qdrant; không gộp chỉ vì tên gần giống hoặc dùng chung ảnh.",
        "Graph mới tập trung entity–entity, bỏ các node nguồn; đây là kiểm kê, chưa migration.",
        "",
        *["- " + text for text in summary["limitations"]],
        "",
    ]
    path.write_text("\n".join(lines), encoding="utf-8")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-manifest", type=Path, default=EmbeddingSettings().manifest)
    parser.add_argument("--output-dir", type=Path, default=Path("var/graph-inventory-v1"))
    args = parser.parse_args()
    if args.output_dir.exists():
        parser.error("Output đã có; dùng thư mục mới để giữ kết quả kiểm kê")
    manifest = read_json(args.source_manifest)
    for key in ("csv", "records"):
        item = manifest["files"][key]
        if file_hash(item["path"]) != item["sha256"]:
            parser.error(f"Nguồn {key} đã thay đổi")
    _, index, store = load_index()
    try:
        if (
            file_hash(args.source_manifest) != index["config"]["manifest_sha256"]
            or manifest["files"]["records"]["sha256"] != index["records_sha256"]
        ):
            parser.error("Nguồn và Qdrant không cùng snapshot")
        payloads = store.payloads
        rows = [r for p in payloads.values() for r in p["records"]]
        approved = read_approved_records(manifest["files"]["csv"]["path"])
        downloaded = read_jsonl(manifest["files"]["records"]["path"])
        expected = {r["record_id"]: r for r in downloaded if r["download_status"] == "success"}
        if len(expected) != len(rows) or expected != {r["record_id"]: r for r in rows}:
            parser.error("Payload không khớp toàn bộ record tải thành công của nguồn")
        outputs = summarize(payloads, rows, approved, downloaded)
        summary, entities, labels, shared, hints, mentions, missing = outputs
        with open(manifest["files"]["csv"]["path"], encoding="utf-8-sig", newline="") as stream:
            csv_rows = list(csv.DictReader(stream))
        if {r["record_id"] for r in approved} != {r["record_id"] for r in downloaded}:
            parser.error("Record được duyệt và log download không bao phủ cùng tập nguồn")
        approved_profiles = []
        for eid, rs in sorted(group_rows(approved, "entity_id").items()):
            indexed = entities.get(eid)
            approved_profiles.append(
                {
                    "entity_id": eid,
                    "source_names": sorted({r["entity_name"] for r in rs}),
                    "source_labels": sorted({r["leaf_label"] for r in rs}),
                    "approved_records": len(rs),
                    "indexed_records": indexed["records"] if indexed else 0,
                    "indexed_images": indexed["images"] if indexed else 0,
                }
            )
        summary["source"]["raw_entities"] = len({r["entity_id"] for r in csv_rows})
        summary["source"]["raw_source_labels"] = len({r["leaf_label"] for r in csv_rows})
        for scope, scoped_rows in (("all_csv", csv_rows), ("approved_csv", approved)):
            summary["source"][scope + "_fields"] = {
                field: {
                    "missing": sum(r.get(field) in (None, "") for r in scoped_rows),
                    "distinct_nonempty": len(
                        {str(r[field]) for r in scoped_rows if r.get(field) not in (None, "")}
                    ),
                }
                for field in csv_rows[0]
            }
        summary["source"]["csv_rows"] = len(csv_rows)
        summary["source"]["csv_columns"] = list(csv_rows[0]) if csv_rows else []
        summary["source"]["approval_values"] = dict(Counter(r["approve"] for r in csv_rows))
        approved_entities = {
            r["entity_id"]: {"names": r["source_names"]} for r in approved_profiles
        }
        approved_hints, approved_mentions = find_relation_hints(approved, approved_entities)
        summary["approved_relation_hints"] = {
            kind: {
                "records": len({h["record_id"] for h in approved_hints if h["family"] == kind}),
                "entities": len({h["entity_id"] for h in approved_hints if h["family"] == kind}),
            }
            for kind in CUES
        }
        summary["approved_cross_entity_name_mentions"] = {
            "records": len({m["record_id"] for m in approved_mentions}),
            "directed_entity_pairs": len(
                {(m["subject_entity_id"], m["mentioned_entity_id"]) for m in approved_mentions}
            ),
        }
        summary["provenance"] = {
            "collection": RetrievalSettings().qdrant_collection,
            "index_sha256": index["index_sha256"],
            "search_metadata_sha256": index["search_metadata_sha256"],
            "source_manifest_sha256": file_hash(args.source_manifest),
            "source_files": {k: manifest["files"][k] for k in ("csv", "records")},
            "script_sha256": file_hash(Path(__file__)),
            "golden_queries_read": False,
        }
        args.output_dir.mkdir(parents=True)
        write_json(args.output_dir / "summary.json", summary)
        for name, records in (
            ("entities", entities.values()),
            ("approved-entities", approved_profiles),
            ("labels", labels),
            ("shared-images", shared),
            ("relation-hints", hints),
            ("cross-entity-mentions", mentions),
            ("missing-records", missing),
            ("approved-relation-hints", approved_hints),
            ("approved-cross-entity-mentions", approved_mentions),
        ):
            write_jsonl(args.output_dir / f"{name}.jsonl", records)
        write_report(args.output_dir / "report.md", summary)
        print(
            {
                "indexed": summary["indexed"],
                "quality": summary["quality"],
                "source_counts": {
                    key: value
                    for key, value in summary["source"].items()
                    if key not in ("all_csv_fields", "approved_csv_fields")
                },
                "hints": summary["relation_hints"],
                "mentions": summary["cross_entity_name_mentions"],
                "output": str(args.output_dir),
            }
        )
    finally:
        store.client.close()


if __name__ == "__main__":
    main()
