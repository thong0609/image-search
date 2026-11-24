"""Metadata tìm kiếm trong payload; file nguồn chỉ được đọc khi nhập dữ liệu."""

import hashlib
import json

from qdrant_client import models

from image_search.adapters.qdrant.vectors import point_id, save_metadata
from image_search.baseline.keyword import tokenize


def name_key(text):
    return " ".join(tokenize(text))


def metadata_payload(records, image):
    def values(field):
        return sorted({r[field] for r in records if r.get(field)})

    return {
        "metadata_schema": 1,
        "records": records,
        "image": image,
        "entity_ids": values("entity_id"),
        "entity_names": values("entity_name"),
        "entity_name_keys": sorted({name_key(r["entity_name"]) for r in records}),
        "captions": values("mo_ta"),
        "leaf_labels": values("leaf_label"),
        "page_titles": values("page_title"),
    }


def snapshot_hash(payloads):
    content = json.dumps(payloads, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(content.encode()).hexdigest()


def read_payloads(store, image_ids, metadata_hash):
    payloads = {}
    expected_ids = set(image_ids)
    offset = None
    while True:
        points, offset = store.client.scroll(
            store.collection, limit=256, offset=offset, with_payload=True, with_vectors=False
        )
        for point in points:
            row = point.payload or {}
            iid = row.get("image_id")
            if (
                iid not in expected_ids
                or str(point.id) != point_id(iid)
                or row.get("index_sha256") != store.index_hash
                or row.get("search_metadata_sha256") != metadata_hash
                or row.get("metadata_schema") != 1
            ):
                raise ValueError(
                    "Metadata Qdrant thiếu hoặc không khớp index; chạy --sync-metadata"
                )
            if not isinstance(row.get("records"), list) or not isinstance(row.get("image"), dict):
                raise ValueError("Payload thiếu records hoặc thông tin ảnh")
            expected = metadata_payload(row["records"], row["image"])
            if any(row.get(key) != value for key, value in expected.items()):
                raise ValueError("Payload metadata Qdrant không nhất quán")
            if (
                row["image"].get("image_id") != iid
                or any(
                    r.get("image_id") != iid or r.get("download_status") != "success"
                    for r in row["records"]
                )
                or not row["records"]
            ):
                raise ValueError("Record metadata không thuộc image ID")
            payloads[iid] = expected
        if offset is None:
            break
    if set(payloads) != set(image_ids) or snapshot_hash(payloads) != metadata_hash:
        raise ValueError("Snapshot metadata Qdrant thiếu ảnh hoặc bị thay đổi")
    return payloads


def sync_metadata(store, index, catalog, images, records_sha256):
    store.validate(index["image_ids"])
    by_id = {image["image_id"]: image for image in images}
    payloads = {
        iid: metadata_payload(catalog.records[iid], by_id[iid]) for iid in index["image_ids"]
    }
    if any(not p["records"] for p in payloads.values()):
        raise ValueError("Thiếu metadata nguồn của ảnh")
    digest = snapshot_hash(payloads)
    for field in ("entity_ids", "entity_name_keys", "search_metadata_sha256"):
        store.client.create_payload_index(
            store.collection, field, models.PayloadSchemaType.KEYWORD, wait=True
        )
    ids = index["image_ids"]
    for start in range(0, len(ids), 64):
        operations = [
            models.SetPayloadOperation(
                set_payload=models.SetPayload(
                    points=[point_id(iid)],
                    payload={**payloads[iid], "search_metadata_sha256": digest},
                )
            )
            for iid in ids[start : start + 64]
        ]
        store.client.batch_update_points(store.collection, operations, wait=True)
    read_payloads(store, ids, digest)
    updated = {**index, "search_metadata_sha256": digest, "records_sha256": records_sha256}
    save_metadata(store.client, store.collection, updated)
    store.metadata_hash = digest
    return updated
