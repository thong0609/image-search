"""Nạp index/cached query vector có kiểm tra hash; không dùng nhãn đáp án."""

from pathlib import Path

import numpy as np

from image_search.baseline.keyword import load_keyword_index
from image_search.baseline.settings import get_baseline_settings
from image_search.baseline.utils import file_hash, read_json, read_jsonl
from image_search.baseline.vectors import load_index
from image_search.embedding.siglip2 import plan_steps
from image_search.retrieval.catalog import Catalog
from image_search.retrieval.engine import RetrievalEngine


def load_engine(embedding_settings, settings, aliases=None):
    corpus, index, vectors = load_index(embedding_settings.manifest, embedding_settings.index_dir)
    baseline = get_baseline_settings()
    keyword, _ = load_keyword_index(
        corpus, settings.keyword_dir, baseline.keyword_k1, baseline.keyword_b
    )
    records = read_jsonl(corpus["files"]["records"]["path"])
    catalog = Catalog(records, index["image_ids"], aliases)
    return RetrievalEngine(index["image_ids"], vectors, keyword, catalog, settings), corpus, index


def load_query_vectors(directory, predictions_path, predictions, index):
    directory = Path(directory)
    metadata = read_json(directory / "embedding.json")
    config = index["config"]
    if (
        metadata["input_sha256"] != file_hash(predictions_path)
        or metadata["image_vectors_sha256"] != index["vector_sha256"]
        or any(
            metadata[key] != config[key]
            for key in ("model", "revision", "preprocessing", "libraries")
        )
        or metadata["processor_sha256"] != index["processor_sha256"]
    ):
        raise ValueError("Query embedding không khớp input/model/image index")
    for name, key in (("vectors.npy", "vectors_sha256"), ("steps.jsonl", "steps_sha256")):
        if file_hash(directory / name) != metadata[key]:
            raise ValueError("Query embedding artifact đã thay đổi")
    rows = read_jsonl(directory / "steps.jsonl")
    expected, _ = plan_steps(predictions)
    if len(rows) != len(expected) or any(
        any(actual.get(k) != v for k, v in wanted.items())
        for actual, wanted in zip(rows, expected, strict=True)
    ):
        raise ValueError("Row mapping không khớp query/step/text/plan")
    vectors = np.load(directory / "vectors.npy", allow_pickle=False)
    if (
        vectors.shape != (len(rows), index["shape"][1])
        or not np.isfinite(vectors).all()
        or not np.allclose(np.linalg.norm(vectors, axis=1), 1, atol=1e-5)
    ):
        raise ValueError("Query vector sai shape/norm")
    if any(r.get("truncated") for r in rows):
        raise ValueError("Có query bị cắt token; cần rà lại trước khi retrieval")
    mapping = {}
    for row, vector in zip(rows, vectors, strict=True):
        mapping.setdefault(row["query_id"], {})[row["step_id"]] = vector
    return mapping
