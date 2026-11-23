"""BM25 trên metadata đã duyệt, một document cho mỗi image_id."""

import math
import re
import unicodedata
from collections import Counter, defaultdict
from pathlib import Path

from image_search.baseline.utils import file_hash, read_json, read_jsonl, write_json, write_jsonl

FIELDS = ["entity_name", "leaf_label", "page_title", "mo_ta"]
TOKENIZER_VERSION = "unicode-nfkd;lower;fold-vietnamese;alphanumeric;v1"


def tokenize(text):
    text = unicodedata.normalize("NFKD", text.casefold().replace("đ", "d"))
    text = "".join(char for char in text if not unicodedata.combining(char))
    return re.findall(r"[a-z0-9]+", text)


def build_documents(records, image_ids):
    # Chỉ dùng metadata nguồn, không đọc query, đáp án hoặc bằng chứng gán nhãn.
    parts = {image_id: set() for image_id in image_ids}
    for record in records:
        image_id = record.get("image_id")
        if record.get("download_status") != "success" or image_id not in parts:
            continue
        for field in FIELDS:
            value = record.get(field, "").strip()
            if value:
                parts[image_id].add(value)
    return [
        {"image_id": image_id, "text": "\n".join(sorted(parts[image_id]))} for image_id in image_ids
    ]


def prepare_bm25(documents, k1, b):
    import numpy as np

    if not math.isfinite(k1) or k1 <= 0 or not 0 <= b <= 1:
        raise ValueError("BM25 cần k1 > 0, 0 <= b <= 1")
    postings = defaultdict(list)
    lengths = []
    for index, document in enumerate(documents):
        terms = tokenize(document["text"])
        lengths.append(len(terms))
        for term, count in Counter(terms).items():
            postings[term].append((index, count))
    lengths = np.asarray(lengths, dtype=np.float64)
    average = float(lengths.mean()) if len(lengths) else 0
    return {
        "image_ids": [row["image_id"] for row in documents],
        "postings": dict(postings),
        "lengths": lengths,
        "average_length": average or 1,
        "k1": k1,
        "b": b,
    }


def load_keyword_index(manifest, index_dir, k1, b):
    index_dir = Path(index_dir)
    index_dir.mkdir(parents=True, exist_ok=True)
    docs_path = index_dir / "documents.jsonl"
    meta_path = index_dir / "index.json"
    config = {
        "records_sha256": manifest["files"]["records"]["sha256"],
        "image_ids": [row["image_id"] for row in manifest["images"]],
        "fields": FIELDS,
        "tokenizer": TOKENIZER_VERSION,
        "k1": k1,
        "b": b,
    }
    if meta_path.exists():
        metadata = read_json(meta_path)
        if metadata["config"] != config or file_hash(docs_path) != metadata["documents_sha256"]:
            raise ValueError("Keyword index không tương thích; dùng --keyword-dir mới")
        documents = read_jsonl(docs_path)
    else:
        documents = build_documents(
            read_jsonl(manifest["files"]["records"]["path"]), config["image_ids"]
        )
        write_jsonl(docs_path, documents)
        metadata = {
            "config": config,
            "documents_sha256": file_hash(docs_path),
            "document_bytes": docs_path.stat().st_size,
        }
        write_json(meta_path, metadata)
    if [row["image_id"] for row in documents] != config["image_ids"]:
        raise ValueError("Thứ tự image_id không khớp keyword index")
    return prepare_bm25(documents, k1, b), metadata


def keyword_search(text, index, top_k):
    import numpy as np

    if not text.strip() or top_k < 1:
        raise ValueError("Query không được rỗng và top-k phải lớn hơn 0")
    size = len(index["image_ids"])
    scores = np.zeros(size, dtype=np.float64)
    for term in sorted(set(tokenize(text))):
        matches = index["postings"].get(term, [])
        if not matches:
            continue
        positions = np.asarray([row[0] for row in matches], dtype=int)
        tf = np.asarray([row[1] for row in matches], dtype=np.float64)
        idf = math.log(1 + (size - len(matches) + 0.5) / (len(matches) + 0.5))
        norm = index["k1"] * (
            1 - index["b"] + index["b"] * index["lengths"][positions] / index["average_length"]
        )
        scores[positions] += idf * tf * (index["k1"] + 1) / (tf + norm)
    # Không đưa document điểm 0 vào nhánh keyword chỉ để lấp đầy top-K.
    order = sorted(
        np.flatnonzero(scores > 0), key=lambda i: (-float(scores[i]), index["image_ids"][i])
    )
    return [{"image_id": index["image_ids"][i], "score": float(scores[i])} for i in order[:top_k]]


def fuse_rankings(vector_results, keyword_results, top_k, rrf_k):
    """RRF chuẩn: mỗi nhánh đóng góp 1 / (k + rank), rank bắt đầu từ 1."""
    if rrf_k <= 0 or top_k < 1:
        raise ValueError("Cấu hình RRF không hợp lệ")
    scores = defaultdict(float)
    for results in [vector_results, keyword_results]:
        seen = set()
        rank = 0
        for row in results:
            image_id = row["image_id"]
            if image_id in seen:
                continue
            seen.add(image_id)
            rank += 1
            scores[image_id] += 1 / (rrf_k + rank)
    order = sorted(scores, key=lambda image_id: (-scores[image_id], image_id))
    return [{"image_id": image_id, "score": scores[image_id]} for image_id in order[:top_k]]
