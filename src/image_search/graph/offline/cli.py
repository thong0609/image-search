"""Offline triples pipeline; all artifacts belong under var/."""

import argparse
from pathlib import Path

from image_search.files import read_json, write_json
from image_search.graph.offline.extract import Settings, prepare, run
from image_search.graph.offline.models import digest
from image_search.graph.offline.registry import build, candidates


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    p = commands.add_parser("prepare")
    p.add_argument("csv", type=Path)
    p.add_argument("--output", type=Path, required=True)
    p.add_argument("--max-chars", type=int, default=18000)
    p = commands.add_parser("extract")
    p.add_argument("input", type=Path)
    p.add_argument("--output-dir", type=Path, required=True)
    p.add_argument(
        "--max-requests", type=int, required=True, help="Giới hạn số request mới, bao gồm retry"
    )
    p = commands.add_parser("build")
    p.add_argument("extractions", type=Path)
    p.add_argument("--decisions", type=Path)
    p.add_argument("--output", type=Path, required=True)
    p = commands.add_parser("stage")
    p.add_argument("artifact", type=Path)
    p.add_argument("--output", type=Path, required=True)
    p = commands.add_parser("resolve")
    p.add_argument("artifact", type=Path)
    p.add_argument("--candidates", type=Path, required=True)
    p.add_argument("--output-dir", type=Path, required=True)
    p.add_argument("--max-requests", type=int, required=True)
    p = commands.add_parser("vector-candidates")
    p.add_argument("artifact", type=Path)
    p.add_argument("--output", type=Path, required=True)
    p = commands.add_parser("extract-many")
    p.add_argument("csv", type=Path, nargs="+")
    p.add_argument("--output-dir", type=Path, required=True)
    p.add_argument("--workers", type=int, default=16)
    p.add_argument("--max-requests", type=int, required=True)
    p.add_argument("--max-chars", type=int, default=9000)
    p.add_argument("--max-records", type=int, default=8)
    p.add_argument("--max-tokens", type=int, default=8192)
    args = parser.parse_args()
    try:
        if args.command == "extract-many":
            from image_search.files import file_hash
            from image_search.graph.offline.parallel import prepare_files, run_parallel

            if args.max_records < 1 or args.max_chars < 1000:
                raise ValueError("max-records >=1, max-chars >=1000")
            groups = prepare_files(args.csv, args.max_chars, args.max_records)
            inputs = {
                "groups": groups,
                "files": [{"path": str(p.resolve()), "sha256": file_hash(p)} for p in args.csv],
            }
            write_json(args.output_dir / "inputs.json", inputs)
            result = run_parallel(
                groups,
                args.output_dir,
                Settings(max_tokens=args.max_tokens),
                args.max_requests,
                workers=args.workers,
            )
            print(result["state"])
        elif args.command == "prepare":
            if args.max_chars < 1000:
                raise ValueError("max-chars phải >=1000")
            groups = prepare(args.csv, args.max_chars)
            write_json(args.output, {"groups": groups, "sha256": digest(groups)})
        elif args.command == "extract":
            if args.max_requests < 1:
                raise ValueError("max-requests phải >=1")
            prepared = read_json(args.input)
            if prepared["sha256"] != digest(prepared["groups"]):
                raise ValueError("Input hash không khớp")
            run(prepared["groups"], args.output_dir, Settings(), args.max_requests)
        elif args.command == "build":
            artifact = build(
                read_json(args.extractions), read_json(args.decisions) if args.decisions else None
            )
            write_json(args.output, artifact)
            write_json(args.output.with_suffix(".candidates.json"), candidates(artifact))
        elif args.command == "resolve":
            from image_search.graph.offline.resolve import resolve

            if args.max_requests < 1:
                raise ValueError("max-requests phải >=1")
            resolve(
                read_json(args.artifact),
                read_json(args.candidates),
                args.output_dir,
                Settings(),
                args.max_requests,
            )
        elif args.command == "vector-candidates":
            from image_search.embedding.index import load_index
            from image_search.graph.offline.resolve import vector_candidates

            _, _, store = load_index()
            try:
                artifact = read_json(args.artifact)
                rows = candidates(artifact) + vector_candidates(
                    artifact, store.client, "graph_registry_" + artifact["generation"]
                )
                write_json(args.output, rows)
            finally:
                store.client.close()
        else:
            from image_search.adapters.neo4j.client import create_graph_driver
            from image_search.embedding.settings import EmbeddingSettings
            from image_search.embedding.siglip2 import Siglip2Embedding
            from image_search.graph.offline.publish import stage
            from image_search.graph.settings import GraphSettings

            settings = GraphSettings()
            encoder = Siglip2Embedding(EmbeddingSettings())
            try:
                with create_graph_driver(settings) as driver:
                    result = stage(read_json(args.artifact), encoder, driver, settings.database)
                    write_json(args.output, result)
            finally:
                encoder.vector_store.client.close()
    except (ValueError, OSError) as error:
        parser.exit(1, f"Lỗi offline graph: {error}\n")


if __name__ == "__main__":
    main()
