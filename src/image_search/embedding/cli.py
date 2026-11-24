"""Kiểm tra index và tạo embedding text/plan; không gọi OpenAI hoặc retrieval."""

import argparse
import random
import time
from collections import defaultdict
from pathlib import Path

import numpy as np

from image_search.baseline.utils import file_hash, read_jsonl, write_json, write_jsonl
from image_search.embedding.settings import EmbeddingSettings
from image_search.embedding.siglip2 import Siglip2Embedding, plan_steps


def make_parser(settings):
    parser = argparse.ArgumentParser(description="Embedding SigLIP2 từ index hiện có")
    parser.add_argument("--manifest", type=Path, default=settings.manifest)
    parser.add_argument("--index-dir", type=Path, default=settings.index_dir)
    parser.add_argument("--threads", type=int, default=settings.threads)
    parser.add_argument("--batch-size", type=int, default=settings.batch_size)
    commands = parser.add_subparsers(dest="command", required=True)
    check = commands.add_parser("check")
    check.add_argument("--verify-samples", type=int, default=3)
    check.add_argument("--output-dir", type=Path, required=True)
    for name in ("text", "plans", "benchmark"):
        command = commands.add_parser(name)
        command.add_argument("input", help="Câu văn hoặc file predictions.jsonl của planner")
        command.add_argument("--output-dir", type=Path, required=True)
        if name == "benchmark":
            command.add_argument("--rounds", type=int, default=3)
            command.add_argument("--seed", type=int, default=42)
    return parser


def main():
    try:
        settings = EmbeddingSettings()
    except ValueError as error:
        raise SystemExit(f"Lỗi cấu hình embedding: {error}") from None
    parser = make_parser(settings)
    args = parser.parse_args()
    try:
        settings = EmbeddingSettings(
            **{
                **settings.model_dump(),
                "manifest": args.manifest,
                "index_dir": args.index_dir,
                "threads": args.threads,
                "batch_size": args.batch_size,
            }
        )
        if args.output_dir.exists():
            raise ValueError("Output đã tồn tại; dùng thư mục mới")
        source_hash = None
        skipped = []
        if args.command == "text":
            if not args.input.strip():
                raise ValueError("Text không được rỗng")
            items = [
                {
                    "row_index": 0,
                    "query_id": "interactive",
                    "step_id": "s1",
                    "search_text": args.input,
                }
            ]
        elif args.command != "check":
            source_hash = file_hash(args.input)
            items, skipped = plan_steps(read_jsonl(args.input))
            if not items:
                raise ValueError("Không có bước cần embedding (planner lỗi hoặc cần làm rõ)")
        if args.command == "benchmark" and args.rounds < 1:
            raise ValueError("rounds phải >= 1")
        encoder = Siglip2Embedding(settings)
        metadata = {
            "model": encoder.index["config"]["model"],
            "revision": encoder.index["config"]["revision"],
            "preprocessing": encoder.index["config"]["preprocessing"],
            "libraries": encoder.index["config"]["libraries"],
            "processor_sha256": encoder.index["processor_sha256"],
            "image_index_sha256": file_hash(settings.index_dir / "index.json"),
            "image_vectors_sha256": encoder.index["vector_sha256"],
            "manifest_sha256": file_hash(settings.manifest),
            "image_count": len(encoder.image_vectors),
            "dimensions": encoder.dimensions,
            "max_text_tokens": encoder.max_length,
            "index_check_seconds": encoder.index_check_seconds,
            "model_load_seconds": encoder.model_load_seconds,
            "settings": settings.model_dump(mode="json"),
            "input_sha256": source_hash,
            "skipped": skipped,
            "source_hashes": {p.name: file_hash(p) for p in Path(__file__).parent.glob("*.py")},
        }
        if args.command == "check":
            metadata["image_sample_checks"] = encoder.verify_image_samples(args.verify_samples)
        else:
            started = time.perf_counter()
            vectors, details = encoder.encode_texts([r["search_text"] for r in items])
            metadata["encode_seconds"] = time.perf_counter() - started
            for row, info in zip(items, details, strict=True):
                row.update(info)
            metadata.update(
                shape=list(vectors.shape),
                dtype=str(vectors.dtype),
                truncated_steps=sum(r["truncated"] for r in items),
            )
            args.output_dir.mkdir(parents=True)
            np.save(args.output_dir / "vectors.npy", vectors, allow_pickle=False)
            write_jsonl(args.output_dir / "steps.jsonl", items)
            metadata["vectors_sha256"] = file_hash(args.output_dir / "vectors.npy")
            metadata["steps_sha256"] = file_hash(args.output_dir / "steps.jsonl")
            if args.command == "benchmark":
                groups = defaultdict(list)
                for row in items:
                    groups[row["query_id"]].append(row["search_text"])
                encoder.encode_texts(next(iter(groups.values())))  # Warmup, không tính.
                timings = []
                rng = random.Random(args.seed)
                for number in range(args.rounds):
                    order = list(groups)
                    rng.shuffle(order)
                    for qid in order:
                        started = time.perf_counter()
                        encoder.encode_texts(groups[qid])
                        timings.append(
                            {
                                "query_id": qid,
                                "round": number + 1,
                                "steps": len(groups[qid]),
                                "latency_ms": (time.perf_counter() - started) * 1000,
                            }
                        )
                write_jsonl(args.output_dir / "timings.jsonl", timings)
                write_json(
                    args.output_dir / "benchmark.json",
                    {
                        "queries": len(groups),
                        "rounds": args.rounds,
                        "seed": args.seed,
                        "steps": len(items),
                        "skipped_queries": len(skipped),
                        "latency_ms": {
                            f"p{p}": float(np.percentile([r["latency_ms"] for r in timings], p))
                            for p in (50, 90, 95)
                        },
                        "scope": (
                            "Mã hóa toàn bộ bước của một plan; model đã nạp, không cache vector."
                        ),
                        "excludes": ["planner", "retrieval", "reranking", "model/index loading"],
                    },
                )
        write_json(args.output_dir / "embedding.json", metadata)
        print(
            f"Đã lưu: {args.output_dir}; {metadata['image_count']} ảnh, "
            f"{metadata['dimensions']} chiều",
            flush=True,
        )
    except (OSError, ValueError, KeyError) as error:
        parser.exit(1, f"Lỗi: {error}\n")
