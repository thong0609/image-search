"""Trích xuất metadata yes offline, nhập/kiểm tra graph thực thể Neo4j."""

import argparse
import json
from pathlib import Path

from neo4j.exceptions import DriverError, Neo4jError
from openai import APIConnectionError, APIStatusError

from image_search.adapters.neo4j.client import create_graph_driver
from image_search.adapters.neo4j.store import GraphStore
from image_search.baseline.utils import read_json, read_jsonl, write_json, write_jsonl
from image_search.baseline.vectors import load_index
from image_search.modules.graph.build import build_graph
from image_search.modules.graph.extraction import digest, inputs, run_extraction
from image_search.modules.graph.settings import GraphSettings


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    extract = commands.add_parser("extract")
    extract.add_argument("--output-dir", type=Path, required=True)
    extract.add_argument("--limit", type=int, help="Thử một số nhóm; không tạo graph để import")
    prepare = commands.add_parser(
        "prepare", help="Xuất nhóm metadata để đọc trực tiếp, không gọi API"
    )
    prepare.add_argument("--output", type=Path, required=True)
    build = commands.add_parser("build", help="Dựng graph từ extraction đã điền, không gọi API")
    build.add_argument("reviewed", type=Path)
    build.add_argument("--output", type=Path, required=True)
    imported = commands.add_parser("import")
    imported.add_argument("artifact", type=Path)
    imported.add_argument("--output", type=Path)
    commands.add_parser("check").add_argument("--output", type=Path)
    commands.add_parser("entity").add_argument("name")
    commands.add_parser("images").add_argument("entity_id")
    args = parser.parse_args()
    if getattr(args, "limit", None) is not None and args.limit < 1:
        parser.error("limit phải >=1")
    settings = GraphSettings()
    _, index, store = load_index()
    try:
        if args.command in ("prepare", "build"):
            records, groups, csv_hash = inputs(index, store.payloads, settings.max_input_chars)
            if args.output.exists():
                raise ValueError("Output đã tồn tại; dùng tên khác để giữ kết quả trước")
            if args.command == "prepare":
                write_jsonl(args.output, groups)
                result = {"groups": len(groups), "csv_sha256": csv_hash}
            else:
                reviewed = read_jsonl(args.reviewed)
                artifact = build_graph(records, groups, reviewed, index, store.payloads)
                write_json(args.output, artifact)
                result = {
                    "entities": len(artifact["entities"]),
                    "relations": len(artifact["relations"]),
                    "graph_sha256": artifact["graph_sha256"],
                    "reviewed_sha256": digest(reviewed),
                    "api_called": False,
                }
        elif args.command == "extract":
            records, groups, responses, result = run_extraction(
                index, store.payloads, settings, args.output_dir, args.limit
            )
            if result["complete"]:
                graph = build_graph(records, groups, responses, index, store.payloads)
                write_json(args.output_dir / "graph.json", graph)
        else:
            with create_graph_driver(settings) as driver:
                graph = GraphStore(driver, settings, index["search_metadata_sha256"])
                if args.command == "import":
                    artifact = read_json(args.artifact)
                    # Đối chiếu ID ảnh và mapping trước khi ghi, validate đầy đủ sau ghi.
                    if sorted(artifact["image_ids"]) != sorted(index["image_ids"]):
                        raise ValueError("Artifact không cùng tập ảnh Qdrant")
                    graph.import_graph(artifact, index, store.payloads)
                result = graph.validate(index, store.payloads)
                if args.command == "entity":
                    result = {"entity_ids": sorted(graph.resolve(args.name))}
                elif args.command == "images":
                    result = {"image_ids": sorted(graph.images_for({args.entity_id}))}
        if getattr(args, "output", None) and args.command not in ("prepare", "build"):
            write_json(args.output, result)
        print(json.dumps(result, ensure_ascii=False, indent=2))
    except APIStatusError as error:
        parser.exit(
            1,
            f"OpenAI HTTP {error.status_code}; kiểm tra credit/quota/quyền truy cập. "
            "Kết quả thành công đã lưu, chưa nhập graph.\n",
        )
    except APIConnectionError:
        parser.exit(1, "Không kết nối được OpenAI; kết quả thành công đã lưu để chạy tiếp.\n")
    except (DriverError, Neo4jError) as error:
        parser.exit(1, f"Lỗi Neo4j: {type(error).__name__}; kiểm tra dịch vụ và cấu hình.\n")
    except (OSError, ValueError, KeyError) as error:
        parser.exit(1, f"Lỗi graph: {error}\n")
    finally:
        store.client.close()


if __name__ == "__main__":
    main()
