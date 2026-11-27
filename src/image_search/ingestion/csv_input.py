"""Bounded CSV validation with a durable result for every source row."""

import csv
import hashlib
import io
import json

from image_search.baseline.records import REQUIRED_COLUMNS

MAX_BYTES = 10 * 1024 * 1024
MAX_ROWS = 10000


def digest(value):
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, ensure_ascii=False).encode()
    ).hexdigest()


def parse_csv(data):
    if len(data) > MAX_BYTES:
        raise ValueError("CSV vượt giới hạn 10 MiB")
    try:
        text = data.decode("utf-8-sig")
    except UnicodeDecodeError as error:
        raise ValueError("CSV phải dùng UTF-8") from error
    reader = csv.DictReader(io.StringIO(text, newline=""), strict=True)
    fields = reader.fieldnames or []
    if len(fields) != len(set(fields)):
        raise ValueError("CSV có tên cột trùng")
    missing = set(REQUIRED_COLUMNS) - set(fields)
    if missing:
        raise ValueError("CSV thiếu cột: " + ", ".join(sorted(missing)))
    rows, seen = [], {}
    try:
        for number, row in enumerate(reader, 1):
            if number > MAX_ROWS:
                raise ValueError("CSV vượt giới hạn 10.000 dòng")
            error, status = None, "pending"
            if None in row or None in row.values():
                error = "Số cột không khớp tiêu đề"
                row = {}
            else:
                row = {k: v.strip() for k, v in row.items()}
                if row["approve"] != "yes":
                    status = "skipped"
                elif any(not row[k] for k in ("entity_id", "entity_name", "image_url")):
                    error = "Thiếu entity_id, entity_name hoặc image_url"
                elif not row["image_url"].startswith(("https://", "http://")):
                    error = "image_url phải là HTTP(S)"
                elif any(
                    row[k] and (not row[k].isdigit() or int(row[k]) <= 0)
                    for k in ("image_width", "image_height")
                ):
                    error = "Kích thước phải là số nguyên dương"
            key = digest([row.get("entity_id"), row.get("image_url")])
            payload_hash = digest(row)
            if status == "pending" and not error:
                if key in seen:
                    if seen[key] == payload_hash:
                        status = "skipped"
                    else:
                        error = "Record trùng khóa nhưng khác metadata trong cùng CSV"
                else:
                    seen[key] = payload_hash
            rows.append(
                {
                    "line": number,
                    "record": row,
                    "source_key": key,
                    "payload_hash": payload_hash,
                    "status": "failed" if error else status,
                    "error": error,
                }
            )
    except csv.Error as error:
        raise ValueError("CSV không đúng cấu trúc") from error
    if not rows:
        raise ValueError("CSV không có dòng dữ liệu")
    return rows
