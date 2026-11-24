"""Kiểm tra liên kết và điều kiện theo metadata nguồn; không xác nhận nội dung ảnh."""

import re
import unicodedata


def condition_key(text):
    return " ".join(re.findall(r"\w+", unicodedata.normalize("NFC", text).casefold()))


def inspect_evidence(catalog, image_id, entity_id, conditions):
    linked = catalog.image_entities[image_id]
    if entity_id is not None and entity_id not in linked:
        identity = "not_linked"
    elif len(linked) != 1:
        identity = "conflicting"
    elif image_id in catalog.uncertain:
        identity = "uncertain"
    else:
        identity = "supported_by_metadata"
    records = [
        r for r in catalog.records[image_id] if entity_id is None or r["entity_id"] == entity_id
    ]
    checks = []
    for condition in conditions:
        phrase = condition_key(condition)
        # Chỉ nhận cụm xuất hiện tường minh. Không suy phủ định từ việc caption thiếu từ.
        support = [
            r
            for r in records
            if phrase and f" {phrase} " in f" {condition_key(r.get('mo_ta', ''))} "
        ]
        checks.append(
            {
                "condition": condition,
                "status": "supported_by_metadata" if support else "unverified",
                "sources": [
                    {
                        "record_id": r["record_id"],
                        "caption": r.get("mo_ta", ""),
                        "page_url": r.get("page_url"),
                    }
                    for r in support
                ],
            }
        )
    supported = all(c["status"] == "supported_by_metadata" for c in checks)
    return {
        "image_id": image_id,
        "entity_id": entity_id,
        "identity_status": identity,
        "identity_sources": [
            {
                "record_id": r["record_id"],
                "entity_id": r["entity_id"],
                "page_url": r.get("page_url"),
            }
            for r in records
        ],
        "conditions_status": "not_requested"
        if not checks
        else "supported_by_metadata"
        if supported
        else "unverified",
        "condition_checks": checks,
        "visual_verification": "not_performed",
    }


def metadata_supported(evidence):
    return evidence["identity_status"] == "supported_by_metadata" and evidence[
        "conditions_status"
    ] in ("not_requested", "supported_by_metadata")
