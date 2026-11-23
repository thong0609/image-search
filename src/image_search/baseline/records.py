"""Đọc CSV nguồn, lọc record đã duyệt và ghi thống kê."""

import csv

from image_search.baseline.utils import file_hash, write_json, write_jsonl

REQUIRED_COLUMNS = [
    "entity_id",
    "entity_name",
    "leaf_label",
    "image_url",
    "image_width",
    "image_height",
    "page_url",
    "page_title",
    "image_domain",
    "mo_ta",
    "approve",
]


def read_approved_records(csv_path):
    records = []
    with open(csv_path, encoding="utf-8-sig", newline="") as csv_file:
        reader = csv.DictReader(csv_file, strict=True)
        missing = set(REQUIRED_COLUMNS) - set(reader.fieldnames or [])
        if missing:
            raise ValueError(f"CSV thiếu cột: {', '.join(sorted(missing))}")
        if len(reader.fieldnames) != len(set(reader.fieldnames)):
            raise ValueError("CSV có tên cột trùng nhau")

        # Đánh số record dữ liệu từ 1, không tính hàng tiêu đề.
        for record_number, row in enumerate(reader, start=1):
            if None in row or None in row.values():
                raise ValueError(f"Record {record_number}: số cột không khớp tiêu đề")
            if row["approve"] != "yes":
                continue
            if not row["entity_id"].strip() or not row["image_url"].strip():
                raise ValueError(f"Record {record_number}: thiếu entity_id hoặc image_url")
            for column in ["image_width", "image_height"]:
                value = row[column]
                if value and (not value.isdigit() or int(value) <= 0):
                    raise ValueError(f"Record {record_number}: {column} phải là số nguyên dương")

            row["record_id"] = f"csv-{record_number}"
            row["csv_record_number"] = record_number
            records.append(row)
    return records


def prepare_records(csv_path, output_dir):
    if csv_path.suffix.lower() != ".csv":
        raise ValueError("Chỉ đọc file .csv được chỉ định, không đọc .bak")
    records = read_approved_records(csv_path)
    output_path = output_dir / "records.jsonl"
    write_jsonl(output_path, records)
    write_json(
        output_dir / "prepare.json",
        {
            "csv_path": str(csv_path.resolve()),
            "csv_sha256": file_hash(csv_path),
            "records": len(records),
            "entities": len({r["entity_id"] for r in records}),
            "urls": len({r["image_url"] for r in records}),
        },
    )
    print(f"Record đã duyệt: {len(records)}")
    print(f"Entity duy nhất: {len({row['entity_id'] for row in records})}")
    print(f"URL ảnh duy nhất: {len({row['image_url'] for row in records})}")
    print(f"Đã lưu: {output_path}")
