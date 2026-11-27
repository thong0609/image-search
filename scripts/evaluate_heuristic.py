"""Offline planner comparison with saved LLM plans; never calls a model API.

Retrieval timing is measured live. Adding historical planner latency is an estimate,
not a fresh end-to-end HTTP measurement. Concurrent runs include the service lock.
"""

import argparse
import random
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np
from evaluate_retrieval import summarize

from image_search.adapters.postgres.database import create_database_engine
from image_search.config import Settings
from image_search.files import file_hash, read_json, read_jsonl, write_json, write_jsonl
from image_search.library import Library
from image_search.planner.heuristic import VERSION
from image_search.planner.schemas import QueryPlan
from image_search.search import SearchService
from image_search.timing import capture


def percentiles(values):
    return {f"p{p}": float(np.percentile(values, p)) for p in (50, 90, 95)} if values else {}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--queries", type=Path, required=True)
    parser.add_argument("--answers", type=Path, required=True)
    parser.add_argument("--plans", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--split", choices=("dev", "test"), required=True)
    parser.add_argument("--workers", type=int, nargs="+", default=[1, 4])
    parser.add_argument("--rounds", type=int, default=1)
    parser.add_argument("--limit", type=int)
    parser.add_argument("--timing-limit", type=int)
    parser.add_argument("--baseline-predictions", type=Path)
    parser.add_argument(
        "--website", action="store_true", help="Include SQL active index/visibility"
    )
    args = parser.parse_args()
    if args.rounds < 1 or any(n < 1 for n in args.workers):
        parser.error("rounds/workers must be positive")
    args.output_dir.mkdir(parents=True, exist_ok=False)
    queries = [q for q in read_jsonl(args.queries) if q["split"] == args.split]
    if args.limit:
        queries = queries[: args.limit]
    saved = {p["query_id"]: p for p in read_jsonl(args.plans)}
    answers = {a["query_id"]: a for a in read_jsonl(args.answers)}
    for q in queries:
        if saved[q["query_id"]]["text"] != q["text"]:
            raise ValueError("Saved plan text differs from query")
    service, database = SearchService(Path("var/objects/thumbnails")), None
    try:
        if args.website:
            settings = Settings()
            database = create_database_engine(settings)
            service.library = Library(database, settings.auth_private_key)
        service.prepare()
        if service.engine.text_store is not None:
            raise ValueError("Evaluation requires two-branch hybrid")
        decisions = {q["query_id"]: service.local_planner.decide(q["text"]) for q in queries}
        rows = [
            {
                "query_id": q["query_id"],
                "text": q["text"],
                "expected_type": q["type"],
                **decisions[q["query_id"]].metadata(),
                "plan": decisions[q["query_id"]].plan.model_dump()
                if decisions[q["query_id"]].plan
                else None,
            }
            for q in queries
        ]
        write_jsonl(args.output_dir / "routes.jsonl", rows)
        write_json(
            args.output_dir / "run.json",
            {
                "version": VERSION,
                "split": args.split,
                "workers": args.workers,
                "rounds": args.rounds,
                "website": args.website,
                "paid_calls": 0,
                "timing_limit": args.timing_limit,
                "baseline_predictions": str(args.baseline_predictions),
                "sources": {str(p): file_hash(p) for p in (args.queries, args.answers, args.plans)},
                "code": {str(p): file_hash(p) for p in Path("src/image_search").rglob("*.py")},
                "image_index": service.index["index_sha256"],
                "graph_hash": service.engine.graph_store.graph_hash,
                "scope": (
                    "planner rules + SearchService.retrieve; excludes HTTP, "
                    "response hydration and snapshot writes"
                ),
                "cache": "no query/embedding cache; historical LLM plans replayed without sleep",
            },
        )
        report = {
            "queries": len(queries),
            "routes": dict(Counter(r["route"] for r in rows)),
            "reasons": dict(Counter(r["reason"] for r in rows)),
            "runs": {},
        }
        print({k: v for k, v in report.items() if k != "runs"}, flush=True)

        def execute(job):
            q, mode, round_number = job
            started = time.perf_counter()
            with capture() as spans:
                before = time.perf_counter()
                decision = service.local_planner.decide(q["text"]) if mode == "heuristic" else None
                local_ms = (time.perf_counter() - before) * 1000
                original = saved[q["query_id"]]
                local = decision is not None and decision.plan is not None
                plan = (
                    decision.plan
                    if local
                    else (
                        QueryPlan.model_validate(original["plan"])
                        if original["status"] == "ok"
                        else None
                    )
                )
                result = service.retrieve(q["text"], plan)
            measured = (time.perf_counter() - started) * 1000
            historical = 0 if local else original["latency_ms"]
            return {
                "query_id": q["query_id"],
                "round": round_number,
                "route": "heuristic" if local else "llm_replay",
                "latency_ms": measured,
                "local_planner_ms": local_ms,
                "estimated_with_historical_planner_ms": measured + historical,
                "spans": spans,
                **result,
            }

        if args.baseline_predictions:
            previous = read_json(args.baseline_predictions.parent.parent / "run.json")
            if (
                previous["image_index_sha256"] != service.index["index_sha256"]
                or previous["search_metadata_sha256"] != service.index["search_metadata_sha256"]
                or previous["graph_sha256"] != service.engine.graph_store.graph_hash
                or previous["plans_sha256"] != file_hash(args.plans)
            ):
                raise ValueError("Saved baseline does not match current index/graph/plans")
            if service.library and service.library.visible() != set(service.images):
                raise ValueError("Saved baseline cannot be reused with different visibility")
            baseline = {r["query_id"]: r for r in read_jsonl(args.baseline_predictions)}
            updated = dict(baseline)
            for q in queries:
                if decisions[q["query_id"]].plan is not None:
                    updated[q["query_id"]] = execute((q, "heuristic", 0))
            report["quality_full_split"] = {
                "baseline": summarize(queries, answers, baseline),
                "heuristic": summarize(queries, answers, updated),
                "unchanged_fallback": "Reuse saved baseline results for identical LLM plans",
            }
            write_jsonl(
                args.output_dir / "quality-predictions.jsonl",
                [updated[q["query_id"]] for q in queries],
            )
        timing_queries = list(queries)
        random.Random(42).shuffle(timing_queries)
        if args.timing_limit:
            timing_queries = timing_queries[: args.timing_limit]
        for workers in args.workers:
            for mode in ("llm", "heuristic"):
                jobs = [(q, mode, r) for r in range(args.rounds) for q in timing_queries]
                random.Random(42).shuffle(jobs)
                results = []
                with ThreadPoolExecutor(workers) as pool:
                    for result in pool.map(execute, jobs):
                        results.append(result)
                        if len(results) % 25 == 0:
                            print(mode, workers, len(results), "/", len(jobs), flush=True)
                tag = f"{mode}-workers-{workers}"
                write_jsonl(args.output_dir / f"{tag}.jsonl", results)
                report["runs"][tag] = {
                    "measured_replay_ms": percentiles([r["latency_ms"] for r in results]),
                    "local_only_ms": percentiles(
                        [r["latency_ms"] for r in results if r["route"] == "heuristic"]
                    ),
                    "estimated_with_historical_planner_ms": percentiles(
                        [r["estimated_with_historical_planner_ms"] for r in results]
                    ),
                    "spans_ms": {
                        key: percentiles([r["spans"].get(key, 0) for r in results])
                        for key in sorted({k for r in results for k in r["spans"]})
                    },
                    "queue_ms": percentiles([r["timing_ms"]["queue"] for r in results]),
                    "quality": summarize(
                        timing_queries, answers, {r["query_id"]: r for r in results}
                    ),
                }
                write_json(args.output_dir / "report.json", report)
                print(tag, report["runs"][tag]["measured_replay_ms"], flush=True)
    finally:
        service.close()
        if database is not None:
            database.dispose()


if __name__ == "__main__":
    main()
