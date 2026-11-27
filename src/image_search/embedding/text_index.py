"""Dựng và kiểm tra vector tên + mô tả từ metadata trong Qdrant."""

import hashlib
import json

from image_search.adapters.qdrant.text_vectors import QdrantTextVectors, text_collection
from image_search.adapters.qdrant.vectors import read_metadata, save_metadata

# Chỉ tên và mô tả: thêm nhãn/tiêu đề làm một nửa record vượt 64 token của SigLIP2.
TEXT_FIELDS = ["entity_name", "mo_ta"]


def text_documents(payloads):
    """Mỗi record một văn bản, không trộn mô tả của các nơi khác nhau."""
    rows = []
    for payload in payloads.values():
        for record in payload["records"]:
            text = ". ".join(v for f in TEXT_FIELDS if (v := (record.get(f) or "").strip()))
            if text:
                rows.append(
                    {
                        "record_id": record["record_id"],
                        "image_id": record["image_id"],
                        "entity_id": record["entity_id"],
                        "text": text,
                    }
                )
    return sorted(rows, key=lambda r: (r["image_id"], r["record_id"]))


def text_index(image_index, documents):
    """Định danh index text: model, xử lý và nội dung; đổi một thứ là index mới."""
    content = json.dumps(documents, ensure_ascii=False, sort_keys=True)
    config = image_index["config"]
    index = {
        "fields": TEXT_FIELDS,
        "model": config["model"],
        "revision": config["revision"],
        "preprocessing": config["preprocessing"],
        "libraries": config["libraries"],
        "processor_sha256": image_index["processor_sha256"],
        "dimensions": image_index["shape"][1],
        "documents": len(documents),
        "documents_sha256": hashlib.sha256(content.encode()).hexdigest(),
    }
    digest = hashlib.sha256(json.dumps(index, sort_keys=True).encode()).hexdigest()
    return {**index, "index_sha256": digest}


def build_text_index(encoder):
    """Trả (metadata index, số văn bản bị cắt)."""
    store = encoder.vector_store
    documents = text_documents(store.payloads)
    index = text_index(encoder.index, documents)
    vectors, details = encoder.encode_texts([r["text"] for r in documents])
    collection = text_collection(store.collection)
    text_store = QdrantTextVectors(
        store.client, collection, index["index_sha256"], index["dimensions"]
    )
    text_store.upload(documents, vectors)
    # Ghi metadata sau cùng: lần nạp dở dang không được dùng.
    save_metadata(store.client, collection, index)
    return index, sum(d["truncated"] for d in details)


def load_text_store(image_store, image_index):
    documents = text_documents(image_store.payloads)
    index = text_index(image_index, documents)
    collection = text_collection(image_store.collection)
    try:
        stored_index = read_metadata(image_store.client, collection)
    except ValueError as error:
        raise ValueError(
            "Thiếu metadata vector text; chạy image-search-qdrant --sync-text"
        ) from error
    if stored_index != index:
        raise ValueError(
            "Vector text không khớp index/metadata; chạy image-search-qdrant --sync-text"
        )
    store = QdrantTextVectors(
        image_store.client, collection, index["index_sha256"], index["dimensions"]
    )
    store.validate(documents)
    return store, index
