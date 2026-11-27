"""Tìm nguyên câu bằng vector/keyword/hybrid để làm mốc đối chiếu."""

import os
import platform
import random
import resource
import subprocess
import time
from pathlib import Path

import numpy as np

from image_search.baseline.benchmark import write_gallery
from image_search.baseline.settings import get_baseline_settings
from image_search.embedding.encoder import encode_text, load_encoder, processor_hash
from image_search.embedding.index import load_index
from image_search.files import file_hash, read_jsonl, write_json, write_jsonl
from image_search.retrieval.keyword import build_keyword_index, fuse_rankings, keyword_search


def runtime_info():
    result = subprocess.run(
        ["git", "rev-parse", "HEAD"], capture_output=True, text=True, check=False
    )
    return {
        "platform": platform.platform(),
        "processor": platform.processor(),
        "python": platform.python_version(),
        "cpu_count": os.cpu_count(),
        "git_revision": result.stdout.strip() or "uncommitted",
        "source_sha256": {
            path.name: file_hash(path) for path in sorted(Path(__file__).parent.glob("*.py"))
        },
        "peak_ram_mb": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024,
    }


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
    rrf_k=None,
    candidates=None,
):
    settings = get_baseline_settings()
    rrf_k = settings.hybrid_rrf_k if rrf_k is None else rrf_k
    candidates = settings.hybrid_candidates if candidates is None else candidates
    if method not in {"vector", "keyword", "hybrid"} or top_k < 1 or threads < 1:
        raise ValueError("Phương pháp, top-k hoặc threads không hợp lệ")
    if rrf_k < 1 or (method == "hybrid" and candidates < top_k):
        raise ValueError("Cấu hình hybrid không hợp lệ; candidates cần >= top-k")
    manifest, metadata, store = load_index(None if text is not None else manifest_path, collection)
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
        records = [r for payload in store.payloads.values() for r in payload["records"]]
        keyword_index, keyword_metadata = build_keyword_index(
            records, metadata["image_ids"], settings.keyword_k1, settings.keyword_b
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
            return fuse_rankings([vector_results, keyword_results], top_k, rrf_k)
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
            "manifest_sha256": metadata["config"]["manifest_sha256"],
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
