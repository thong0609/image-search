"""Chạy các kế hoạch đã lưu, không gọi OpenAI hoặc sửa prompt."""

import argparse
import html
import random
import time
from collections import Counter
from pathlib import Path

import numpy as np
from neo4j.exceptions import DriverError, Neo4jError

from image_search.embedding.settings import EmbeddingSettings
from image_search.embedding.siglip2 import Siglip2Embedding
from image_search.files import file_hash, read_json, read_jsonl, write_json, write_jsonl
from image_search.planner.schemas import QueryPlan
from image_search.retrieval.executor import direct_steps
from image_search.retrieval.listing import search_list
from image_search.retrieval.runtime import load_engine
from image_search.retrieval.settings import RetrievalSettings


def write_gallery(path, predictions, corpus):
    images = {r["image_id"]: r for r in corpus["images"]}

    def card(iid, caption):
        uri = Path(images[iid]["local_path"]).resolve().as_uri()
        return (
            f'<figure><a href="{html.escape(uri, quote=True)}"><img loading="lazy" '
            f'src="{html.escape(uri, quote=True)}"></a><figcaption>'
            f"{html.escape(caption)}<br>{iid}</figcaption></figure>"
        )

    sections = []
    for row in predictions:
        content = f"<h2>{html.escape(row['query_id'])} · {row['status']}</h2>"
        content += f"<p>{html.escape(row.get('text', ''))}</p>"
        for step in row.get("trace", []):
            names = [h["name"] for h in step.get("hypotheses", [])] or step.get("entity_ids", [])
            content += f"<p>{step['status']}: " + html.escape(str(names)) + "</p>"
        for group in row.get("groups", []):
            content += (
                f"<h3>{html.escape(group['target_id'])} · "
                f"{html.escape(group['search_text'])} · {group['status']}</h3>"
            )
            content += "<p>Entity scope: " + html.escape(str(group["entity_scope"])) + "</p><div>"
            content += "".join(card(r["image_id"], str(r["score"])) for r in group["results"])
            content += "</div>"
            content += "<p>" + html.escape(group.get("verification_status", "")) + "</p>"
        sections.append("<section>" + content + "</section>")
    style = (
        '<meta charset="utf-8"><style>body{font:15px system-ui;margin:20px}'
        "section{border-bottom:2px solid #aaa;padding:15px}div{display:flex;flex-wrap:wrap}"
        "figure{width:220px;margin:8px}img{width:220px;height:160px;object-fit:contain}"
        "figcaption{overflow-wrap:anywhere;font-size:12px}</style>"
    )
    path.write_text(
        style + "<h1>Retrieval theo planner</h1><p>Ứng viên chưa được rerank hoặc "
        "xác minh thị giác. Điểm không phải xác suất.</p>" + "".join(sections)
    )


def validate_plans(rows):
    if not rows:
        raise ValueError("File kế hoạch rỗng")
    seen = set()
    for row in rows:
        qid = row.get("query_id")
        if not isinstance(qid, str) or not qid.strip() or qid in seen:
            raise ValueError("Query ID rỗng/trùng")
        seen.add(qid)
        if row.get("status") not in ("ok", "error"):
            raise ValueError(f"{qid}: status cần là ok/error")
        if row["status"] == "ok":
            QueryPlan.model_validate(row["plan"])


def main():
    parser = argparse.ArgumentParser(description="Retrieval từ kế hoạch planner đã lưu")
    parser.add_argument("plans", type=Path, help="File predictions.jsonl của planner")
    parser.add_argument("--method", choices=("vector", "keyword", "hybrid", "all"), default="all")
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument(
        "--aliases", type=Path, help="JSON alias -> danh sách entity ID có trong catalog"
    )
    parser.add_argument("--rounds", type=int, default=3)
    parser.add_argument(
        "--strict", action="store_true", help="Chỉ kết quả đúng kế hoạch, không lấp bằng cả câu"
    )
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()
    engine, encoder = None, None
    try:
        settings, embedding_settings = RetrievalSettings(), EmbeddingSettings()
        if args.rounds < 1:
            raise ValueError("rounds phải >= 1")
        if args.output_dir.exists():
            raise ValueError("Output đã tồn tại; dùng thư mục phiên bản mới")
        rows = read_jsonl(args.plans)
        validate_plans(rows)  # Kiểm tra toàn bộ input trước khi tải index/model.
        aliases = read_json(args.aliases) if args.aliases else None
        started = time.perf_counter()
        engine, corpus, index = load_engine(embedding_settings, settings, aliases)
        encoder = None
        if args.method != "keyword":
            encoder = Siglip2Embedding(embedding_settings)
        startup_seconds = time.perf_counter() - started
        methods = ("vector", "keyword", "hybrid") if args.method == "all" else (args.method,)
        write_json(
            args.output_dir / "run.json",
            {
                "plans_sha256": file_hash(args.plans),
                "method": args.method,
                "strict": args.strict,
                "settings": settings.model_dump(mode="json"),
                "embedding_settings": embedding_settings.model_dump(mode="json"),
                "rounds": args.rounds,
                "seed": args.seed,
                "manifest_sha256": index["config"]["manifest_sha256"],
                "image_index_sha256": index["index_sha256"],
                "keyword_metadata": engine.keyword_metadata,
                "search_metadata_sha256": index["search_metadata_sha256"],
                "aliases_sha256": file_hash(args.aliases) if args.aliases else None,
                "startup_seconds": startup_seconds,
                "planner_called": False,
                "graph_snapshot_sha256": index["search_metadata_sha256"],
                "graph_mode": "entity_relations",
                "graph_sha256": engine.graph_store.graph_hash,
                "source_hashes": {p.name: file_hash(p) for p in Path(__file__).parent.glob("*.py")},
            },
        )

        def execute(row, method):
            if not args.strict and row.get("text"):
                plan = row["plan"] if row["status"] == "ok" else None
                result = search_list(engine, encoder, row["text"], plan, method)
                result.pop("timing_ms")
                return result
            if row["status"] == "error":
                return {"status": "planner_error", "groups": [], "trace": []}
            plan = QueryPlan.model_validate(row["plan"])
            vectors = None
            steps = direct_steps(plan)
            if not plan.needs_clarification and steps and method != "keyword":
                array, details = encoder.encode_texts([s.search_text for s in steps])
                if any(d["truncated"] for d in details):
                    raise ValueError("Query bị cắt token; không tiếp tục retrieval")
                vectors = {s.id: v for s, v in zip(steps, array, strict=True)}
            return engine.execute(plan, method, vectors)

        links = []
        for method in methods:
            warmup = next(
                (r for r in rows if r["status"] == "ok" and not r["plan"]["needs_clarification"]),
                rows[0],
            )
            execute(warmup, method)  # Warmup, không đo.
            predictions, timings = {}, []
            rng = random.Random(args.seed)
            for number in range(args.rounds):
                order = list(rows)
                rng.shuffle(order)
                for row in order:
                    started = time.perf_counter()
                    result = execute(row, method)
                    timings.append(
                        {
                            "query_id": row["query_id"],
                            "round": number + 1,
                            "latency_ms": (time.perf_counter() - started) * 1000,
                            "status": result["status"],
                            "query_type": row.get("plan", {}).get("query_type")
                            if row.get("plan")
                            else None,
                        }
                    )
                    predictions[row["query_id"]] = {
                        "query_id": row["query_id"],
                        "text": row.get("text", ""),
                        **result,
                    }
            output = args.output_dir / method
            ordered = [predictions[r["query_id"]] for r in rows]
            write_jsonl(output / "predictions.jsonl", ordered)
            write_jsonl(output / "timings.jsonl", timings)
            measured = [
                t for t in timings if t["status"] not in ("needs_clarification", "planner_error")
            ]
            write_json(
                output / "report.json",
                {
                    "queries": len(rows),
                    "active_queries": len(measured) // args.rounds,
                    "groups": sum(len(p["groups"]) for p in ordered),
                    "method": method,
                    "group_statuses": dict(
                        Counter(g["status"] for p in ordered for g in p["groups"])
                    ),
                    "queries_with_results": sum(
                        any(g["results"] for g in p["groups"]) for p in ordered
                    ),
                    "queries_with_candidates": sum(
                        any(g["candidates"] for g in p["groups"]) for p in ordered
                    ),
                    "latency_ms": {
                        f"p{p}": float(np.percentile([t["latency_ms"] for t in measured], p))
                        if measured
                        else None
                        for p in (50, 90, 95)
                    },
                    "scope": "embedding_and_retrieval"
                    if method != "keyword"
                    else "keyword_retrieval",
                    "excludes": ["OpenAI planner", "reranking", "startup/index/model loading"],
                    "quality_metrics": None,
                    "predictions_sha256": file_hash(output / "predictions.jsonl"),
                },
            )
            write_gallery(output / "results.html", ordered, corpus)
            links.append(f'<li><a href="{method}/results.html">{method}</a></li>')
            print(f"{method}: {len(ordered)} queries -> {output}", flush=True)
        (args.output_dir / "index.html").write_text(
            '<meta charset="utf-8"><h1>Retrieval thử nghiệm</h1><ul>' + "".join(links) + "</ul>"
        )
    except (DriverError, Neo4jError) as error:
        parser.exit(1, f"Lỗi Neo4j: {type(error).__name__}; kiểm tra dịch vụ và cấu hình graph.\n")
    except (OSError, ValueError, KeyError) as error:
        parser.exit(1, f"Lỗi: {error}\n")
    finally:
        if engine is not None:
            engine.vector_store.client.close()
            engine.graph_store.driver.close()
        if encoder is not None:
            encoder.vector_store.client.close()
