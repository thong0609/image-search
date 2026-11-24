"""Thử một câu, chạy JSONL và đánh giá kế hoạch đã lưu."""

import argparse
import hashlib
import json
from pathlib import Path

from image_search.files import file_hash, read_json, read_jsonl, write_json, write_jsonl
from image_search.planner.evaluate import evaluate_cases
from image_search.planner.router import PROMPT, PROMPT_VERSION, make_client, route_query
from image_search.planner.schemas import QueryPlan
from image_search.planner.settings import PlannerSettings


def validate_inputs(rows, max_chars):
    seen, families = set(), {}
    if not rows:
        raise ValueError("File câu hỏi rỗng")
    for row in rows:
        qid, text = row.get("query_id"), row.get("text")
        if not isinstance(qid, str) or not qid.strip() or qid in seen:
            raise ValueError("Query ID rỗng/trùng")
        seen.add(qid)
        if not isinstance(text, str) or not text.strip() or len(text) > max_chars:
            raise ValueError(f"{qid}: query rỗng hoặc quá dài")
        if row.get("split") not in ("dev", "test"):
            raise ValueError(f"{qid}: split cần là dev/test")
        if "expected" in row:
            QueryPlan.model_validate(row["expected"])
        family = row.get("intent_id", qid)
        if families.setdefault(family, row["split"]) != row["split"]:
            raise ValueError("Một họ ý định không được vượt dev/test")


def make_parser():
    parser = argparse.ArgumentParser(description="Planner OpenAI — chưa thực thi retrieval")
    commands = parser.add_subparsers(dest="command", required=True)
    single = commands.add_parser("route")
    single.add_argument("text")
    batch = commands.add_parser("run")
    batch.add_argument("queries", type=Path)
    batch.add_argument("--split", choices=("dev", "test"), default="dev")
    batch.add_argument("--limit", type=int)
    batch.add_argument("--output-dir", type=Path, default=Path("var/planner-v1/dev"))
    for command in (single, batch):
        command.add_argument("--model")
    check = commands.add_parser("check")
    check.add_argument("queries", type=Path)
    evaluation = commands.add_parser("evaluate")
    evaluation.add_argument("queries", type=Path)
    evaluation.add_argument("predictions", type=Path)
    evaluation.add_argument("--split", choices=("dev", "test"), default="dev")
    return parser


def main():
    parser = make_parser()
    args = parser.parse_args()
    try:
        settings = PlannerSettings()
        if args.command == "check":
            rows = read_jsonl(args.queries)
            validate_inputs(rows, settings.max_query_chars)
            print(f"Hợp lệ: {len(rows)} câu; có expected: {sum('expected' in row for row in rows)}")
            return
        if args.command == "evaluate":
            cases = read_jsonl(args.queries)
            validate_inputs(cases, settings.max_query_chars)
            cases = [c for c in cases if c["split"] == args.split]
            predictions = read_jsonl(args.predictions)
            if not predictions:
                raise ValueError("Prediction rỗng")
            run_path = args.predictions.parent / "run.json"
            if run_path.exists():
                run = read_json(run_path)
                if run["queries_sha256"] != file_hash(args.queries) or run["split"] != args.split:
                    raise ValueError("Run không khớp file câu hỏi/split")
                if run["query_ids"][: len(predictions)] != [p["query_id"] for p in predictions]:
                    raise ValueError("Prediction không khớp thứ tự/query ID của run")
            completed_path = args.predictions.parent / "completed.json"
            if completed_path.exists():
                completed = read_json(completed_path)
                if completed["predictions_sha256"] != file_hash(args.predictions):
                    raise ValueError("Prediction đã thay đổi sau khi chạy")
            ids = {p["query_id"] for p in predictions}
            cases = [c for c in cases if c["query_id"] in ids]
            if not all("expected" in c for c in cases):
                raise ValueError("Cần nhãn expected riêng cho planner để chấm")
            report = evaluate_cases(cases, predictions)
            report.update(
                queries_sha256=file_hash(args.queries),
                predictions_sha256=file_hash(args.predictions),
                split=args.split,
                evaluated_queries=len(cases),
                available_queries=sum(r["split"] == args.split for r in read_jsonl(args.queries)),
            )
            path = args.predictions.parent / "report.json"
            write_json(path, report)
            print(json.dumps(report, ensure_ascii=False, indent=2))
            return
        if args.model:
            settings.model = args.model
        if args.command == "route":
            if not args.text.strip() or len(args.text) > settings.max_query_chars:
                raise ValueError("Query rỗng hoặc quá dài")
            with make_client(settings) as client:
                result = route_query(args.text, settings, client)
            print(json.dumps(result, ensure_ascii=False, indent=2))
            if result["status"] != "ok":
                parser.exit(1)
            return
        rows = read_jsonl(args.queries)
        validate_inputs(rows, settings.max_query_chars)
        rows = [r for r in rows if r["split"] == args.split]
        if args.limit is not None:
            if args.limit < 1:
                raise ValueError("limit phải >= 1")
            rows = rows[: args.limit]
        if not rows:
            raise ValueError("Không có query trong split")
        if args.output_dir.exists():
            raise ValueError("Output đã tồn tại; dùng thư mục mới để giữ kết quả")
        # Tạo client trước output để thiếu key không để lại lần chạy rỗng.
        with make_client(settings) as client:
            args.output_dir.mkdir(parents=True)
            write_json(
                args.output_dir / "run.json",
                {
                    "queries_sha256": file_hash(args.queries),
                    "split": args.split,
                    "query_ids": [r["query_id"] for r in rows],
                    "prompt_version": PROMPT_VERSION,
                    "prompt_sha256": hashlib.sha256(PROMPT.encode()).hexdigest(),
                    "settings": settings.model_dump(mode="json", exclude={"api_key"}),
                    "source_hashes": {
                        p.name: file_hash(p) for p in Path(__file__).parent.glob("*.py")
                    },
                    "expected_sent_to_model": False,
                },
            )
            predictions = []
            for row in rows:
                prediction = {
                    "query_id": row["query_id"],
                    **route_query(row["text"], settings, client),
                }
                predictions.append(prediction)
                # Lưu sau từng câu để giữ tiến độ khi tiến trình bị ngắt.
                write_jsonl(args.output_dir / "predictions.jsonl", predictions)
                print(row["query_id"], prediction["status"], flush=True)
                if prediction["error_code"] in ("api_http_401", "api_http_403", "api_http_429"):
                    parser.exit(1, "Dừng batch: kiểm tra key/quyền/quota. Kết quả đã lưu.\n")
        write_json(
            args.output_dir / "completed.json",
            {
                "queries": len(predictions),
                "errors": sum(p["status"] != "ok" for p in predictions),
                "predictions_sha256": file_hash(args.output_dir / "predictions.jsonl"),
            },
        )
        if any(p["status"] != "ok" for p in predictions):
            parser.exit(1, "Batch hoàn tất nhưng có lỗi; xem predictions.jsonl.\n")
    except (OSError, ValueError, KeyError) as error:
        parser.exit(1, f"Lỗi: {error}\n")
