import argparse
import csv
from pathlib import Path

from image_search.baseline.benchmark import draft_benchmark, freeze_benchmark
from image_search.baseline.download import download_records
from image_search.baseline.evaluate import evaluate_predictions
from image_search.baseline.records import prepare_records
from image_search.baseline.settings import get_baseline_settings
from image_search.baseline.vectors import build_index, search_index


def add_index_arguments(parser):
    parser.add_argument("--manifest", type=Path, default=Path("var/benchmark.json"))
    parser.add_argument("--collection", default=None)
    parser.add_argument("--threads", type=int, default=4)


def add_search_arguments(parser):
    parser.add_argument("--method", choices=["vector", "keyword", "hybrid"], default="vector")
    parser.add_argument("--rrf-k", type=int)
    parser.add_argument("--candidates", type=int)


def make_parser():
    settings = get_baseline_settings()
    parser = argparse.ArgumentParser(description="Baseline tìm kiếm ảnh — chạy từng bước.")
    commands = parser.add_subparsers(dest="command", required=True)

    prepare = commands.add_parser("prepare", help="Đọc và lọc CSV")
    prepare.add_argument("csv_path", type=Path)
    prepare.add_argument("--output-dir", type=Path, default=Path("var"))

    download = commands.add_parser("download", help="Tải ảnh, hỗ trợ chạy tiếp")
    download.add_argument("--records", type=Path, default=Path("var/records.jsonl"))
    download.add_argument("--output-dir", type=Path, default=Path("var"))
    download.add_argument("--limit", type=int)
    download.add_argument("--workers", type=int, default=settings.workers)
    download.add_argument("--timeout", type=float, default=settings.timeout)
    download.add_argument("--max-bytes", type=int, default=settings.max_bytes)
    download.add_argument("--retries", type=int, default=settings.retries)

    draft = commands.add_parser("draft", help="Tạo nháp query/đáp án và trang xem ảnh")
    draft.add_argument("--records", type=Path, default=Path("var/downloaded-records.jsonl"))
    draft.add_argument("--output-dir", type=Path, default=Path("var"))
    draft.add_argument("--per-type", type=int, default=3)

    freeze = commands.add_parser("freeze", help="Kiểm tra nhãn và cố định benchmark")
    freeze.add_argument("--csv", required=True, type=Path)
    freeze.add_argument("--records", type=Path, default=Path("var/downloaded-records.jsonl"))
    freeze.add_argument("--queries", type=Path, default=Path("var/queries.jsonl"))
    freeze.add_argument("--answers", type=Path, default=Path("var/answers.jsonl"))
    freeze.add_argument("--manifest", type=Path, default=Path("var/benchmark.json"))

    index = commands.add_parser("index", help="Mã hóa ảnh bằng SigLIP 2 trên CPU")
    add_index_arguments(index)
    index.add_argument("--model", default=settings.model_name)
    index.add_argument("--revision", default=settings.model_revision)
    index.add_argument("--batch-size", type=int, default=8)

    search = commands.add_parser("search", help="Tìm bằng một câu tiếng Việt")
    add_index_arguments(search)
    add_search_arguments(search)
    search.add_argument("text")
    search.add_argument("--top-k", type=int, default=10)
    search.add_argument("--output-dir", type=Path)

    run = commands.add_parser("run", help="Tìm kiếm 3 vòng rồi chấm điểm một split")
    add_index_arguments(run)
    add_search_arguments(run)
    run.add_argument("--split", choices=["dev", "test"], default="dev")
    run.add_argument("--seed", type=int, default=42)
    run.add_argument("--output-dir", type=Path)

    evaluate = commands.add_parser("evaluate", help="Chấm file dự đoán đã có")
    evaluate.add_argument("predictions", type=Path)
    evaluate.add_argument("--manifest", type=Path, default=Path("var/benchmark.json"))
    evaluate.add_argument("--split", choices=["dev", "test"], default="dev")
    return parser


def main():
    try:
        parser = make_parser()
    except ValueError as error:
        argparse.ArgumentParser().exit(1, f"Cấu hình không hợp lệ: {error}\n")
    args = parser.parse_args()
    try:
        if args.command == "prepare":
            prepare_records(args.csv_path, args.output_dir)
        elif args.command == "download":
            download_records(
                args.records,
                args.output_dir,
                args.limit,
                args.workers,
                args.timeout,
                args.max_bytes,
                args.retries,
            )
        elif args.command == "draft":
            draft_benchmark(args.records, args.output_dir, args.per_type)
        elif args.command == "freeze":
            freeze_benchmark(args.csv, args.records, args.queries, args.answers, args.manifest)
        elif args.command == "index":
            build_index(
                args.manifest,
                args.collection,
                args.model,
                args.revision,
                args.batch_size,
                args.threads,
            )
        elif args.command == "search":
            search_index(
                args.manifest,
                args.collection,
                text=args.text,
                top_k=args.top_k,
                threads=args.threads,
                output_dir=args.output_dir,
                method=args.method,
                rrf_k=args.rrf_k,
                candidates=args.candidates,
            )
        elif args.command == "run":
            output = search_index(
                args.manifest,
                args.collection,
                split=args.split,
                seed=args.seed,
                threads=args.threads,
                output_dir=args.output_dir,
                method=args.method,
                rrf_k=args.rrf_k,
                candidates=args.candidates,
            )
            evaluate_predictions(args.manifest, output / "predictions.jsonl", args.split)
        elif args.command == "evaluate":
            evaluate_predictions(args.manifest, args.predictions, args.split)
    except ImportError as error:
        parser.exit(1, f"Thiếu dependency: {error}. Chạy uv sync --extra baseline\n")
    except (OSError, ValueError, csv.Error, KeyError) as error:
        parser.exit(1, f"Lỗi: {error}\n")


if __name__ == "__main__":
    main()
