"""SigLIP 2 → vector chuẩn hóa → tìm kiếm cosine chính xác."""

import hashlib
import importlib.metadata
import random
import time
from pathlib import Path

from PIL import Image

from image_search.baseline.benchmark import load_manifest, write_gallery
from image_search.baseline.keyword import fuse_rankings, keyword_search, load_keyword_index
from image_search.baseline.settings import get_baseline_settings
from image_search.baseline.utils import (
    file_hash,
    read_jsonl,
    runtime_info,
    write_json,
    write_jsonl,
)

PREPROCESSING = "rgb;processor-default;max_length=model;truncate;l2;float32;v1"


def library_versions():
    return {
        name: importlib.metadata.version(name)
        for name in ["torch", "transformers", "numpy", "pillow", "tokenizers"]
    }


def load_encoder(model_name, revision, cache_dir, threads=4):
    import torch
    from transformers import AutoModel, AutoProcessor

    if len(revision) != 40 or any(c not in "0123456789abcdef" for c in revision):
        raise ValueError("revision phải là commit SHA đầy đủ (40 ký tự)")
    if threads < 1:
        raise ValueError("threads phải lớn hơn 0")
    torch.set_num_threads(threads)
    processor = AutoProcessor.from_pretrained(model_name, revision=revision, cache_dir=cache_dir)
    model = AutoModel.from_pretrained(model_name, revision=revision, cache_dir=cache_dir).eval()
    return model, processor


def processor_hash(processor):
    text = processor.image_processor.to_json_string()
    text += processor.tokenizer.backend_tokenizer.to_str()
    return hashlib.sha256(text.encode()).hexdigest()


def normalize(vectors):
    import numpy as np

    vectors = np.asarray(vectors, dtype=np.float32)
    norms = np.linalg.norm(vectors, axis=-1, keepdims=True)
    if not np.isfinite(vectors).all() or (norms <= 0).any():
        raise ValueError("Vector rỗng/NaN/Inf")
    return vectors / norms


def encode_text(text, model, processor):
    import torch

    if not text.strip():
        raise ValueError("Câu tìm kiếm không được rỗng")
    inputs = processor(
        text=[text],
        padding="max_length",
        truncation=True,
        max_length=model.config.text_config.max_position_embeddings,
        return_tensors="pt",
    )
    with torch.inference_mode():
        features = model.get_text_features(**inputs)
    return normalize(features.cpu().numpy())[0]


def build_index(
    manifest_path, collection=None, model_name=None, revision=None, batch_size=8, threads=4
):
    import json

    import numpy as np
    import torch

    from image_search.adapters.qdrant.client import create_qdrant_client
    from image_search.adapters.qdrant.vectors import QdrantVectors, save_metadata
    from image_search.config import get_settings
    from image_search.retrieval.catalog import Catalog
    from image_search.retrieval.settings import RetrievalSettings

    settings = get_baseline_settings()
    collection = collection or RetrievalSettings().qdrant_collection
    if batch_size < 1 or threads < 1:
        raise ValueError("batch-size/threads phải lớn hơn 0")
    manifest = load_manifest(manifest_path)
    client = create_qdrant_client(get_settings())
    try:
        if client.collection_exists(collection):
            _, existing, existing_store = load_index(manifest_path, collection)
            existing_store.client.close()
            if existing["config"]["model"] != (model_name or settings.model_name) or existing[
                "config"
            ]["revision"] != (revision or settings.model_revision):
                raise ValueError("Index không tương thích; dùng collection mới")
            print("Dùng lại collection Qdrant đã kiểm tra")
            return
        model, processor = load_encoder(
            model_name or settings.model_name,
            revision or settings.model_revision,
            Path("var/models"),
            threads,
        )
        batches = []
        for start in range(0, len(manifest["images"]), batch_size):
            batch = []
            try:
                for row in manifest["images"][start : start + batch_size]:
                    with Image.open(row["local_path"]) as image:
                        batch.append(image.convert("RGB"))
                inputs = processor(images=batch, return_tensors="pt")
                with torch.inference_mode():
                    features = model.get_image_features(**inputs)
                batches.append(normalize(features.cpu().numpy()))
            finally:
                for image in batch:
                    image.close()
        vectors = np.concatenate(batches)
        index = {
            "config": {
                "manifest_sha256": file_hash(manifest_path),
                "model": model_name or settings.model_name,
                "revision": revision or settings.model_revision,
                "preprocessing": PREPROCESSING,
                "libraries": library_versions(),
            },
            "image_ids": [r["image_id"] for r in manifest["images"]],
            "shape": list(vectors.shape),
            "processor_sha256": processor_hash(processor),
        }
        index["index_sha256"] = hashlib.sha256(
            json.dumps(index, sort_keys=True).encode()
        ).hexdigest()
        catalog = Catalog(read_jsonl(manifest["files"]["records"]["path"]), index["image_ids"])
        store = QdrantVectors(client, collection, index["index_sha256"], vectors.shape[1])
        store.upload(
            index["image_ids"],
            vectors,
            catalog,
            index["config"]["model"],
            index["config"]["revision"],
        )
        save_metadata(client, collection, index)
    finally:
        client.close()


def load_index(manifest_path, collection=None):
    from image_search.adapters.qdrant.client import create_qdrant_client
    from image_search.adapters.qdrant.vectors import QdrantVectors, read_metadata
    from image_search.config import get_settings
    from image_search.retrieval.settings import RetrievalSettings

    collection = collection or RetrievalSettings().qdrant_collection
    manifest = load_manifest(manifest_path)
    client = create_qdrant_client(get_settings())
    try:
        metadata = read_metadata(client, collection)
        config = metadata["config"]
        if (
            config["manifest_sha256"] != file_hash(manifest_path)
            or config["preprocessing"] != PREPROCESSING
            or config["libraries"] != library_versions()
        ):
            raise ValueError("Qdrant index không khớp corpus/model/thư viện")
        if [r["image_id"] for r in manifest["images"]] != metadata["image_ids"]:
            raise ValueError("Image IDs không khớp Qdrant index")
        store = QdrantVectors(client, collection, metadata["index_sha256"], metadata["shape"][1])
        store.validate(metadata["image_ids"])
        return manifest, metadata, store
    except Exception:
        client.close()
        raise


def search_index(
    manifest_path,
    collection=None,
    text=None,
    split="dev",
    top_k=10,
    seed=42,
    threads=4,
    output_dir=None,
    method="vector",
    keyword_dir=None,
    rrf_k=None,
    candidates=None,
):
    import numpy as np

    settings = get_baseline_settings()
    rrf_k = settings.hybrid_rrf_k if rrf_k is None else rrf_k
    candidates = settings.hybrid_candidates if candidates is None else candidates
    if method not in {"vector", "keyword", "hybrid"} or top_k < 1 or threads < 1:
        raise ValueError("Phương pháp, top-k hoặc threads không hợp lệ")
    if rrf_k < 1 or (method == "hybrid" and candidates < top_k):
        raise ValueError("Cấu hình hybrid không hợp lệ; candidates cần >= top-k")
    manifest, metadata, store = load_index(manifest_path, collection)
    config = metadata["config"]
    model_load_seconds = 0
    if method != "keyword":
        started = time.perf_counter()
        model, processor = load_encoder(
            config["model"], config["revision"], Path("var/models"), threads
        )
        model_load_seconds = time.perf_counter() - started
        if processor_hash(processor) != metadata["processor_sha256"]:
            raise ValueError("Tiền xử lý đã thay đổi so với index")
    keyword_metadata = None
    keyword_load_seconds = 0
    if method != "vector":
        started = time.perf_counter()
        keyword_dir = Path(keyword_dir or Path("var/hybrid-v1/keyword-index"))
        keyword_index, keyword_metadata = load_keyword_index(
            manifest, keyword_dir, settings.keyword_k1, settings.keyword_b
        )
        keyword_load_seconds = time.perf_counter() - started
    default_output = Path("var") / ("search" if text is not None else split)
    if method != "vector":
        default_output = default_output / method
    output_dir = Path(output_dir or default_output)
    output_dir.mkdir(parents=True, exist_ok=True)
    if text is not None:
        queries = [{"query_id": "interactive", "text": text}]
        rounds = 1
    else:
        queries = [
            q for q in read_jsonl(manifest["files"]["queries"]["path"]) if q["split"] == split
        ]
        rounds = 3
    if not queries:
        raise ValueError("Không có query trong split")

    def retrieve(query):
        vector_results, keyword_results = [], []
        count = candidates if method == "hybrid" else top_k
        if method != "keyword":
            vector = encode_text(query["text"], model, processor)
            vector_results = store.search(vector, count, set(metadata["image_ids"]))
        if method != "vector":
            keyword_results = keyword_search(query["text"], keyword_index, count)
        if method == "hybrid":
            return fuse_rankings(vector_results, keyword_results, top_k, rrf_k)
        return keyword_results if method == "keyword" else vector_results

    retrieve(queries[0])  # Warmup không tính vào độ trễ.
    timings, predictions = [], {}
    rng = random.Random(seed)
    for round_number in range(rounds):
        order = list(queries)
        rng.shuffle(order)
        for query in order:
            started = time.perf_counter()
            results = retrieve(query)
            elapsed_ms = (time.perf_counter() - started) * 1000
            timings.append(
                {"query_id": query["query_id"], "round": round_number + 1, "latency_ms": elapsed_ms}
            )
            predictions[query["query_id"]] = {"query_id": query["query_id"], "results": results}
    write_jsonl(output_dir / "predictions.jsonl", [predictions[q["query_id"]] for q in queries])
    write_jsonl(output_dir / "timings.jsonl", timings)
    write_json(
        output_dir / "run.json",
        {
            "manifest_sha256": file_hash(manifest_path),
            "index_sha256": metadata["index_sha256"],
            "split": split if text is None else None,
            "seed": seed,
            "rounds": rounds,
            "top_k": top_k,
            "threads": threads,
            "method": method,
            "hybrid": {
                "fusion": "rrf",
                "weights": {"vector": 1, "keyword": 1},
                "rrf_k": rrf_k,
                "candidates": candidates,
            }
            if method == "hybrid"
            else None,
            "keyword_index": keyword_metadata,
            "keyword_load_seconds": keyword_load_seconds,
            "query_cache": False,
            "result_cache": False,
            "model_load_seconds": model_load_seconds,
            "p50_ms": float(np.percentile([t["latency_ms"] for t in timings], 50)),
            "p95_ms": float(np.percentile([t["latency_ms"] for t in timings], 95)),
            "runtime": runtime_info(),
            "index": metadata,
            "predictions_sha256": file_hash(output_dir / "predictions.jsonl"),
        },
    )
    paths = {row["image_id"]: row["local_path"] for row in manifest["images"]}
    cards = []
    for query in queries:
        for rank, result in enumerate(predictions[query["query_id"]]["results"], start=1):
            cards.append(
                {
                    "local_path": paths[result["image_id"]],
                    "caption": f"{query['query_id']} | {query['text']} | #{rank} | "
                    f"{result['score']:.4f} | {result['image_id']}",
                }
            )
    write_gallery(output_dir / "results.html", cards, "Kết quả baseline")
    return output_dir
