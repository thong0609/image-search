"""Tạo nháp câu hỏi, xem ảnh và cố định bộ đánh giá đã gán nhãn."""

import html
from pathlib import Path

from image_search.baseline.download import reusable
from image_search.baseline.records import read_approved_records
from image_search.baseline.utils import (
    file_hash,
    read_json,
    read_jsonl,
    unique_by,
    write_json,
    write_jsonl,
)

QUERY_TYPES = {"single", "multi-target", "multi-hop"}
RULES = {"top_k": [1, 5, 10], "ties": "image_id ascending", "labels": "known binary"}


def corpus_from_records(records):
    images = {}
    for record in records:
        if record.get("download_status") == "success":
            images[record["image_id"]] = {
                "image_id": record["image_id"],
                "local_path": record["local_path"],
            }
    if not images:
        raise ValueError("Chưa có ảnh tải thành công")
    return [images[key] for key in sorted(images)]


def write_gallery(path, rows, title):
    cards = []
    for row in rows:
        label = html.escape(row.get("caption", row.get("image_id", "")))
        source = html.escape(Path(row["local_path"]).resolve().as_uri(), quote=True)
        cards.append(f'<article><img src="{source}" loading="lazy"><p>{label}</p></article>')
    Path(path).write_text(
        '<!doctype html><meta charset="utf-8">'
        f"<title>{html.escape(title)}</title>"
        "<style>body{font:16px sans-serif;margin:24px}main{display:flex;flex-wrap:wrap;gap:16px}"
        "article{width:300px;overflow-wrap:anywhere}img{width:100%;height:210px;object-fit:contain}"
        "</style>"
        f"<h1>{html.escape(title)}</h1><main>{''.join(cards)}</main>",
        encoding="utf-8",
    )


def entity_groups(records):
    # Các entity dùng chung ảnh phải nằm cùng split.
    groups = []
    for record in records:
        members = {f"entity:{record['entity_id']}", f"image:{record['image_id']}"}
        if record.get("split_group"):
            members.add(f"manual:{record['split_group']}")
        remaining = []
        for group in groups:
            if group & members:
                members |= group
            else:
                remaining.append(group)
        groups = remaining + [members]
    return groups


def draft_benchmark(records_path, output_dir, per_type=3):
    if per_type < 1:
        raise ValueError("per-type phải lớn hơn 0")
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    if any((output_dir / name).exists() for name in ["queries.jsonl", "answers.jsonl"]):
        raise ValueError("Đã có file nhãn; dùng thư mục khác để tránh ghi đè")
    records = [row for row in read_jsonl(records_path) if row.get("download_status") == "success"]
    corpus_from_records(records)
    split_by_entity = {}
    for index, group in enumerate(entity_groups(records)):
        for member in group:
            if member.startswith("entity:"):
                split_by_entity[member[7:]] = "dev" if index % 2 == 0 else "test"
    entities = {}
    for row in records:
        entities.setdefault(row["entity_id"], {})[row["image_id"]] = row
    queries, answers = [], []

    def add(text, kind, split, targets, evidence, answerable=True):
        query_id = f"q{len(queries) + 1:03d}"
        queries.append(
            {
                "query_id": query_id,
                "text": text,
                "type": kind,
                "split": split,
                "answerable": answerable,
                "synthetic": True,
                "reviewed": False,
            }
        )
        answers.append(
            {
                "query_id": query_id,
                "targets": targets,
                "evidence": evidence,
                "verification": "",
            }
        )

    def target(rows):
        return {"image_ids": [row["image_id"] for row in rows], "required": 1}

    for split in ["dev", "test"]:
        available = [
            list(rows.values())
            for entity, rows in entities.items()
            if split_by_entity[entity] == split
        ]
        for rows in available[:per_type]:
            add(f"Tìm ảnh về {rows[0]['entity_name']}.", "single", split, [target(rows)], [])
        for index in range(min(per_type, len(available) // 2)):
            left, right = available[index * 2 : index * 2 + 2]
            add(
                f"Tìm một ảnh về {left[0]['entity_name']} và một ảnh về {right[0]['entity_name']}.",
                "multi-target",
                split,
                [target(left), target(right)],
                [],
            )
        candidates = [rows for rows in available if len(rows) >= 2]
        for rows in candidates[:per_type]:
            bridge, destination = rows[:2]
            add(
                "[CẦN VIẾT] Tìm ảnh có đặc điểm đích của địa điểm được nhận ra qua ảnh gợi ý.",
                "multi-hop",
                split,
                [target([destination])],
                [
                    {
                        "record_id": bridge["record_id"],
                        "role": "bridge",
                        "description": bridge["mo_ta"],
                    },
                    {
                        "record_id": destination["record_id"],
                        "role": "target",
                        "description": destination["mo_ta"],
                    },
                ],
            )
        add(
            "[CẦN VIẾT] Câu hỏi đã xác minh không có đáp án trong kho.",
            "single",
            split,
            [],
            [],
            answerable=False,
        )
    write_jsonl(output_dir / "queries.jsonl", queries)
    write_jsonl(output_dir / "answers.jsonl", answers)
    write_gallery(
        output_dir / "catalog.html",
        [
            {
                **row,
                "caption": f"{row['record_id']} | {row['entity_id']} | {row['entity_name']} | "
                f"{row['image_id']} | {row['mo_ta']}",
            }
            for row in records
        ],
        "Kho ảnh và mô tả nguồn — dùng để gán nhãn",
    )
    print(f"Đã tạo {len(queries)} câu nháp. Sửa nội dung và nhãn trước khi đặt reviewed=true.")


def validate_benchmark(records, queries, answers):
    images = {row["image_id"] for row in corpus_from_records(records)}
    record_map = unique_by(records, "record_id")
    query_map = unique_by(queries, "query_id")
    answer_map = unique_by(answers, "query_id")
    if not queries or query_map.keys() != answer_map.keys():
        raise ValueError("Query và đáp án phải khớp ID, không được rỗng")
    image_splits = {}
    for query in queries:
        qid = query["query_id"]
        if query["type"] not in QUERY_TYPES or query["split"] not in {"dev", "test"}:
            raise ValueError(f"{qid}: type hoặc split không hợp lệ")
        if query.get("reviewed") is not True or not query["text"].strip():
            raise ValueError(f"{qid}: chưa xác nhận nhãn/nội dung")
        if "[CẦN VIẾT]" in query["text"]:
            raise ValueError(f"{qid}: còn nội dung mẫu")
        for key in ["answerable", "synthetic"]:
            if type(query.get(key)) is not bool:
                raise ValueError(f"{qid}: {key} phải là boolean")
        answer = answer_map[qid]
        targets = answer["targets"]
        if not query["answerable"]:
            if targets or not answer.get("verification", "").strip():
                raise ValueError(f"{qid}: câu không đáp án cần ghi cách xác minh và targets=[]")
            continue
        if not targets or (query["type"] == "multi-target" and len(targets) < 2):
            raise ValueError(f"{qid}: thiếu mục tiêu")
        if query["type"] != "multi-target" and len(targets) != 1:
            raise ValueError(f"{qid}: loại câu này cần đúng một mục tiêu")
        involved = set()
        for target in targets:
            ids = target["image_ids"]
            required = target["required"]
            if len(set(ids)) != len(ids) or not set(ids) <= images:
                raise ValueError(f"{qid}: ID ảnh trùng hoặc không có trong kho")
            if type(required) is not int or not 1 <= required <= len(ids):
                raise ValueError(f"{qid}: số ảnh yêu cầu không hợp lệ")
            involved.update(ids)
        evidence = answer.get("evidence", [])
        for item in evidence:
            source = record_map.get(item["record_id"])
            if not source or source.get("download_status") != "success":
                raise ValueError(f"{qid}: bằng chứng không có ảnh thành công")
            if not item.get("description", "").strip():
                raise ValueError(f"{qid}: thiếu mô tả bằng chứng")
            involved.add(source["image_id"])
        if query["type"] == "multi-hop":
            bridges = [record_map[e["record_id"]] for e in evidence if e["role"] == "bridge"]
            ends = [record_map[e["record_id"]] for e in evidence if e["role"] == "target"]
            target_ids = set(targets[0]["image_ids"])
            if not bridges or not ends or not target_ids <= {r["image_id"] for r in ends}:
                raise ValueError(f"{qid}: thiếu chuỗi bridge → entity → target")
            for end in ends:
                if not any(
                    b["entity_id"] == end["entity_id"] and b["image_id"] != end["image_id"]
                    for b in bridges
                ):
                    raise ValueError(f"{qid}: bridge và target cần chung entity, khác ảnh")
        for image_id in involved:
            image_splits.setdefault(image_id, set()).add(query["split"])
    successful = [r for r in records if r.get("download_status") == "success"]
    for group in entity_groups(successful):
        splits = set()
        for member in group:
            if member.startswith("image:"):
                splits.update(image_splits.get(member[6:], set()))
        if len(splits) > 1:
            raise ValueError("Rò rỉ dev/test qua entity, ảnh trùng hoặc split_group")
    for split in ["dev", "test"]:
        kinds = {q["type"] for q in queries if q["split"] == split and q["answerable"]}
        if kinds != QUERY_TYPES:
            raise ValueError(f"{split}: cần đủ single, multi-target, multi-hop")
    if not any(not q["answerable"] for q in queries):
        raise ValueError("Cần ít nhất một câu không có đáp án đã xác minh")


def freeze_benchmark(csv_path, records_path, queries_path, answers_path, manifest_path):
    manifest_path = Path(manifest_path)
    if manifest_path.exists():
        raise ValueError("Manifest đã tồn tại; dùng tên mới cho phiên bản mới")
    records = read_jsonl(records_path)
    original = unique_by(read_approved_records(csv_path), "record_id")
    downloaded = unique_by(records, "record_id")
    if original.keys() != downloaded.keys():
        raise ValueError("Record tải ảnh không khớp CSV nguồn")
    for record_id, row in original.items():
        if any(downloaded[record_id].get(key) != value for key, value in row.items()):
            raise ValueError(f"Metadata không khớp CSV: {record_id}")
    validate_benchmark(records, read_jsonl(queries_path), read_jsonl(answers_path))
    for row in records:
        if row.get("download_status") == "success" and not reusable(row):
            raise ValueError(f"Ảnh thiếu/hỏng: {row['record_id']}")
    files = {}
    for name, path in {
        "csv": csv_path,
        "records": records_path,
        "queries": queries_path,
        "answers": answers_path,
    }.items():
        files[name] = {"path": str(Path(path).resolve()), "sha256": file_hash(path)}
    write_json(
        manifest_path,
        {"version": 1, "files": files, "images": corpus_from_records(records), "rules": RULES},
    )
    print(f"Đã cố định benchmark: {manifest_path}")


def load_manifest(path):
    manifest = read_json(path)
    if manifest["version"] != 1 or manifest["rules"] != RULES:
        raise ValueError("Phiên bản benchmark hoặc quy tắc chấm không tương thích")
    for name, item in manifest["files"].items():
        if file_hash(item["path"]) != item["sha256"]:
            raise ValueError(f"Benchmark đã thay đổi: {name}; cần phiên bản mới")
    unique_by(manifest["images"], "image_id")
    for image in manifest["images"]:
        if file_hash(image["local_path"]) != image["image_id"]:
            raise ValueError(f"Ảnh đã thay đổi: {image['image_id']}")
    return manifest
