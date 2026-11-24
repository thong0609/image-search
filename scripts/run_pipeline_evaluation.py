"""Đo pipeline thật, gọi planner trên text; labels chỉ phục vụ script chấm riêng."""

import argparse
import json
import threading
import time
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from pathlib import Path

import numpy as np

from image_search.baseline.utils import file_hash, read_json, read_jsonl, write_json, write_jsonl
from image_search.embedding.settings import EmbeddingSettings
from image_search.embedding.siglip2 import Siglip2Embedding
from image_search.planner.router import PROMPT, PROMPT_VERSION, make_client, route_query
from image_search.planner.settings import PlannerSettings
from image_search.retrieval.runtime import load_engine
from image_search.retrieval.settings import RetrievalSettings


def main():
    parser = argparse.ArgumentParser(description="Đánh giá pipeline RRF, không rerank")
    parser.add_argument("--queries", type=Path, default=Path("var/benchmark-v2/queries.jsonl"))
    parser.add_argument("--answers", type=Path, default=Path("var/benchmark-v2/answers.jsonl"))
    parser.add_argument("--output-dir", type=Path, default=Path("var/pipeline-v1"))
    parser.add_argument("--workers", type=int, default=8)
    parser.add_argument("--resume", action="store_true")
    args = parser.parse_args()
    if not 1 <= args.workers <= 8:
        parser.error("workers cần trong 1..8")
    queries = read_jsonl(args.queries)
    if not queries or len({q["query_id"] for q in queries}) != len(queries):
        parser.error("Query rỗng hoặc trùng ID")
    planner, embedding, retrieval = PlannerSettings(), EmbeddingSettings(), RetrievalSettings()
    if not planner.api_key:
        parser.error("Thiếu OPENAI_API_KEY")
    import hashlib

    configuration = {
        "queries": str(args.queries.resolve()),
        "queries_sha256": file_hash(args.queries),
        "answers": str(args.answers.resolve()),
        "answers_sha256": file_hash(args.answers),
        "planner": planner.model_dump(mode="json", exclude={"api_key"}),
        "embedding": embedding.model_dump(mode="json"),
        "retrieval": retrieval.model_dump(mode="json"),
        "prompt_version": PROMPT_VERSION,
        "prompt_sha256": hashlib.sha256(PROMPT.encode()).hexdigest(),
        "image_index_sha256": file_hash(embedding.index_dir / "index.json"),
        "method": "hybrid",
        "rrf_weights": [1, 1],
        "workers": args.workers,
        "query_count": len(queries),
        "expected_or_labels_sent_to_model": False,
        "sources": {
            str(p): file_hash(p)
            for package in ("planner", "embedding", "retrieval")
            for p in Path("src/image_search", package).glob("*.py")
        },
        "runner_sha256": file_hash(Path(__file__)),
        "evaluation_policy": {
            "served": "round-robin unique IDs across group.results, global top-10",
            "candidates": "round-robin per hypothesis then per group, global top-50/100",
            "ambiguous_entity": "No served images; hypotheses remain diagnostic candidates.",
            "labels": "Known positives only; unknown excluded, catalog negatives separate.",
            "aggregation": (
                "Separate split/type/canonical/robustness, average within intent then intents."
            ),
            "latency": (
                "Actual submit-to-completion including OpenAI, client, CPU queue, embedding, "
                "executor and JSON serialization; excludes startup and report/file writes."
            ),
        },
    }
    if args.output_dir.exists():
        if (
            not args.resume
            or read_json(args.output_dir / "run.json")["configuration"] != configuration
        ):
            parser.error("Output đã có hoặc cấu hình resume không khớp")
        if (args.output_dir / "completed.json").exists():
            parser.error("Run đã hoàn tất")
    else:
        args.output_dir.mkdir(parents=True)
        write_json(args.output_dir / "run.json", {"configuration": configuration})
    started = time.perf_counter()
    engine, _, _ = load_engine(embedding, retrieval)
    encoder = Siglip2Embedding(embedding)
    encoder.encode_texts(["ảnh cửa hàng"])  # Warmup trước đo; không gọi API.
    startup_seconds = time.perf_counter() - started
    cpu = threading.Lock()
    plans_path = args.output_dir / "plans.jsonl"
    results_path = args.output_dir / "predictions.jsonl"
    vectors_path = args.output_dir / "embedding-checkpoint.jsonl"
    done = read_jsonl(results_path) if results_path.exists() else []
    done_ids = {r["query_id"] for r in done}
    for path in (plans_path, vectors_path):
        if path.exists():
            write_jsonl(path, [r for r in read_jsonl(path) if r["query_id"] in done_ids])
    remaining = [q for q in queries if q["query_id"] not in done_ids]
    stop = False

    def execute(query, submitted):
        qid = query["query_id"]
        with make_client(planner) as client:
            planned = {"query_id": qid, **route_query(query["text"], planner, client)}
        vector_rows = []
        error = None
        wait_start = time.perf_counter()
        with cpu:
            acquired = time.perf_counter()
            encode_ms = 0
            executor_ms = 0
            if planned["status"] != "ok":
                result = {"status": "planner_error", "groups": [], "trace": []}
            else:
                plan = planned["plan"]
                mapping = None
                try:
                    if not plan["needs_clarification"]:
                        begin = time.perf_counter()
                        array, details = encoder.encode_texts(
                            [s["search_text"] for s in plan["steps"]]
                        )
                        encode_ms = (time.perf_counter() - begin) * 1000
                        if any(d["truncated"] for d in details):
                            raise ValueError("truncated_query")
                        mapping = {s["id"]: v for s, v in zip(plan["steps"], array, strict=True)}
                        vector_rows = [
                            {
                                "query_id": qid,
                                "step_id": s["id"],
                                "search_text": s["search_text"],
                                "vector": v.tolist(),
                            }
                            for s, v in zip(plan["steps"], array, strict=True)
                        ]
                    begin = time.perf_counter()
                    result = engine.execute(plan, "hybrid", mapping)
                    executor_ms = (time.perf_counter() - begin) * 1000
                except (ValueError, KeyError) as exc:
                    error = type(exc).__name__
                    result = {"status": "execution_error", "groups": [], "trace": []}
        record = {
            "query_id": qid,
            "text": query["text"],
            **result,
            "planner_status": planned["status"],
            "planner_error": planned["error_code"],
            "execution_error": error,
        }
        json.dumps(record, ensure_ascii=False)  # Tính cả serialize response, không tính ghi file.
        record["timing_ms"] = {
            "planner": planned["latency_ms"],
            "cpu_queue": (acquired - wait_start) * 1000,
            "embedding": encode_ms,
            "executor": executor_ms,
            "end_to_end": (time.perf_counter() - submitted) * 1000,
        }
        return planned, record, vector_rows

    def append(stream, rows):
        for row in rows:
            stream.write(json.dumps(row, ensure_ascii=False) + "\n")
        stream.flush()

    begin_run = time.perf_counter()
    iterator = iter(remaining)
    with (
        plans_path.open("a", encoding="utf-8") as plan_file,
        results_path.open("a", encoding="utf-8") as result_file,
        vectors_path.open("a", encoding="utf-8") as vector_file,
        ThreadPoolExecutor(max_workers=args.workers) as pool,
    ):
        pending = {}
        for query in list(remaining[: args.workers]):
            next(iterator)
            pending[pool.submit(execute, query, time.perf_counter())] = query["query_id"]
        while pending:
            finished, _ = wait(pending, return_when=FIRST_COMPLETED)
            for future in finished:
                pending.pop(future)
                planned, result, vectors = future.result()
                append(plan_file, [planned])
                append(vector_file, vectors)
                append(result_file, [result])  # Commit marker sau plan + vector.
                done.append(result)
                if planned["error_code"] in ("api_http_401", "api_http_403", "api_http_429"):
                    stop = True
                write_json(
                    args.output_dir / "progress.json",
                    {
                        "completed": len(done),
                        "total": len(queries),
                        "stop_requested": stop,
                        "statuses": dict(
                            __import__("collections").Counter(r["status"] for r in done)
                        ),
                        "startup_seconds": startup_seconds,
                        "session_seconds": time.perf_counter() - begin_run,
                    },
                )
                print(
                    f"{len(done)}/{len(queries)} {result['query_id']}: {result['status']}",
                    flush=True,
                )
                if not stop:
                    query = next(iterator, None)
                    if query is not None:
                        pending[pool.submit(execute, query, time.perf_counter())] = query[
                            "query_id"
                        ]
    if len(done) != len(queries):
        parser.exit(1, "Run dừng sớm do key/quyền/quota; có thể resume cùng cấu hình.\n")
    vector_rows = read_jsonl(vectors_path)
    if vector_rows:
        np.save(
            args.output_dir / "query-vectors.npy",
            np.asarray([r.pop("vector") for r in vector_rows], dtype=np.float32),
            allow_pickle=False,
        )
        write_jsonl(
            args.output_dir / "query-steps.jsonl",
            [dict(r, row_index=i) for i, r in enumerate(vector_rows)],
        )
    write_json(
        args.output_dir / "completed.json",
        {
            "queries": len(done),
            "plans_sha256": file_hash(plans_path),
            "predictions_sha256": file_hash(results_path),
            "startup_seconds": startup_seconds,
            "query_vectors_sha256": file_hash(args.output_dir / "query-vectors.npy")
            if vector_rows
            else None,
        },
    )
    vectors_path.unlink(missing_ok=True)
    print("Completed", args.output_dir, flush=True)


if __name__ == "__main__":
    main()
