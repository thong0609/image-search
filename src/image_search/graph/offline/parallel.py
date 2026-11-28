"""Bounded parallel extraction, global circuit breaker and live tracking."""

import html
import json
import threading
import time
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from datetime import UTC, datetime
from pathlib import Path

import httpx

from image_search.files import read_json
from image_search.graph.offline.extract import atomic_json, prepare
from image_search.graph.offline.models import Extraction, digest, output_schema


def prepare_files(paths, max_chars=9000, max_records=8):
    """Namespace CSV row IDs across files; preserve the original row ID for audit."""
    names = [Path(p).name for p in paths]
    if len(names) != len(set(names)):
        raise ValueError("Tên file nguồn trùng")
    queues = []
    for path in paths:
        groups = []
        for group in prepare(path, max_chars):
            for start in range(0, len(group["records"]), max_records):
                rows = []
                for row in group["records"][start : start + max_records]:
                    rows.append(
                        {
                            **row,
                            "source_record_id": row["record_id"],
                            "record_id": f"{Path(path).name}:{row['record_id']}",
                        }
                    )
                groups.append({**group, "source_file": Path(path).name, "records": rows})
        queues.append(groups)
    # Interleave files so tracking and pilot feedback cover every selected file early.
    return [queue[i] for i in range(max(map(len, queues))) for queue in queues if i < len(queue)]


class Tracker:
    def __init__(self, groups, output, workers, max_requests, error_limit=10):
        self.output = Path(output)
        self.lock = threading.RLock()
        self.stop = threading.Event()
        self.started = time.monotonic()
        self.data = {
            "state": "running",
            "workers": workers,
            "max_requests": max_requests,
            "error_limit": error_limit,
            "consecutive_api_errors": 0,
            "requests": 0,
            "api_errors": 0,
            "validation_errors": 0,
            "completed_batches": 0,
            "completed_records": 0,
            "cached_batches": 0,
            "failed_batches": 0,
            "in_flight": 0,
            "retry_waiting": 0,
            "input_tokens": 0,
            "output_tokens": 0,
            "reasoning_tokens": 0,
            "cost_usd": None,
            "triples": 0,
            "total_batches": len(groups),
            "total_records": sum(len(g["records"]) for g in groups),
            "files": {},
            "pause_reason": None,
        }
        for group in groups:
            row = self.data["files"].setdefault(
                group.get("source_file", "input"),
                {
                    "total_batches": 0,
                    "total_records": 0,
                    "completed_batches": 0,
                    "completed_records": 0,
                    "failed_batches": 0,
                },
            )
            row["total_batches"] += 1
            row["total_records"] += len(group["records"])
        self.event("started")

    def event(self, event, **fields):
        with self.lock:
            self.data["elapsed_seconds"] = round(time.monotonic() - self.started, 2)
            self.data["updated_at"] = datetime.now(UTC).isoformat()
            new = self.data["completed_batches"] - self.data["cached_batches"]
            elapsed = self.data["elapsed_seconds"]
            self.data["batches_per_minute"] = round(new * 60 / elapsed, 2) if elapsed else 0
            self.data["estimated_remaining_seconds"] = (
                round((self.data["total_batches"] - self.data["completed_batches"]) * elapsed / new)
                if new and self.data["state"] == "running"
                else None
            )
            row = {"event": event, "at": self.data["updated_at"], **fields}
            self.output.mkdir(parents=True, exist_ok=True)
            with (self.output / "events.jsonl").open("a") as stream:
                stream.write(json.dumps(row, ensure_ascii=False) + "\n")
            atomic_json(self.output / "progress.json", self.data)
            summary = json.dumps(self.data, ensure_ascii=False, indent=2)
            page = '<meta charset="utf-8"><meta http-equiv="refresh" content="5">'
            page += "<title>Offline graph tracking</title><h1>Offline graph tracking</h1>"
            page += "<p>Tự cập nhật 5 giây. Token bao gồm output lỗi nếu API có trả usage.</p>"
            page += "<pre>" + html.escape(summary) + "</pre>"
            temporary = self.output / "tracking.tmp"
            temporary.write_text(page)
            temporary.replace(self.output / "tracking.html")
            print(json.dumps(row, ensure_ascii=False), flush=True)

    def pause(self, reason):
        with self.lock:
            if not self.stop.is_set():
                self.data.update(
                    state="pausing",
                    pause_reason=reason,
                    errors_at_pause=self.data["consecutive_api_errors"],
                )
                self.stop.set()
                self.event("pausing", reason=reason)

    def reserve(self, key):
        with self.lock:
            if (self.output / "PAUSE").exists():
                self.pause("manual_pause_file")
            if self.stop.is_set():
                return False
            if self.data["requests"] >= self.data["max_requests"]:
                self.pause("request_budget_reached")
                return False
            self.data["requests"] += 1
            self.data["in_flight"] += 1
            self.event("request_started", batch=key)
            return True

    def api_result(self, key, status=None, usage=None, error=None):
        with self.lock:
            self.data["in_flight"] -= 1
            if error or status != 200:
                self.data["api_errors"] += 1
                self.data["consecutive_api_errors"] += 1
                if self.data["consecutive_api_errors"] >= self.data["error_limit"]:
                    self.pause("consecutive_api_errors")
            else:
                self.data["consecutive_api_errors"] = 0
            usage = usage or {}
            self.data["input_tokens"] += usage.get("prompt_tokens", 0)
            self.data["output_tokens"] += usage.get("completion_tokens", 0)
            self.data["reasoning_tokens"] += (usage.get("completion_tokens_details") or {}).get(
                "reasoning_tokens", 0
            )
            self.event("api_result", batch=key, status=status, error=error)

    def complete(self, group, saved, cached=False):
        with self.lock:
            self.data["completed_batches"] += 1
            self.data["completed_records"] += len(group["records"])
            self.data["cached_batches"] += int(cached)
            self.data["triples"] += sum(len(r["triples"]) for r in saved["output"]["records"])
            row = self.data["files"][group.get("source_file", "input")]
            row["completed_batches"] += 1
            row["completed_records"] += len(group["records"])
            self.event("batch_completed", source=group.get("source_file"), cached=cached)


def run_parallel(
    groups, output, settings, max_requests, workers=16, error_limit=10, attempts=10, backoff=2
):
    if not 1 <= workers <= 64 or max_requests < 1 or backoff <= 0:
        raise ValueError("workers 1..64, max_requests >=1, backoff >0")
    if settings.base_url.rstrip("/") != "https://api.shopaikey.com/v1":
        raise ValueError("Endpoint không đúng ShopAIKey")
    output = Path(output)
    prompt = Path(__file__).with_name("prompt.txt").read_text()
    config = {
        "model": settings.model,
        "base_url": settings.base_url,
        "prompt": prompt,
        "schema": output_schema(),
        "max_tokens": settings.max_tokens,
    }
    manifest = {"groups_sha256": digest(groups), "config": config}
    if (output / "run.json").exists() and read_json(output / "run.json") != manifest:
        raise ValueError("Thư mục run có input/cấu hình khác; dùng thư mục mới")
    atomic_json(output / "run.json", manifest)
    keys = [digest({"config": config, "input": g}) for g in groups]
    if len(keys) != len(set(keys)):
        raise ValueError("Batch input trùng")
    tracker = Tracker(groups, output, workers, max_requests, error_limit)
    results = {}
    pending_groups = []
    for group, key in zip(groups, keys, strict=True):
        path = output / "responses" / f"{key}.json"
        if path.exists():
            saved = read_json(path)
            if saved["input"] != group or saved["config"] != config:
                raise ValueError("Checkpoint không khớp")
            Extraction.model_validate(saved["output"]).check_input(group)
            results[key] = saved
            tracker.complete(group, saved, cached=True)
        else:
            pending_groups.append((group, key))

    with httpx.Client(
        base_url=settings.base_url.rstrip("/") + "/",
        headers={"Authorization": "Bearer " + settings.api_key.get_secret_value()},
        timeout=settings.timeout,
        follow_redirects=False,
        limits=httpx.Limits(max_connections=workers, max_keepalive_connections=workers),
    ) as client:

        def process(pair):
            group, key = pair
            body = {
                "model": settings.model,
                "messages": [
                    {"role": "system", "content": prompt},
                    {"role": "user", "content": json.dumps(group, ensure_ascii=False)},
                ],
                "max_tokens": settings.max_tokens,
                "stream": False,
                "response_format": {
                    "type": "json_schema",
                    "json_schema": {
                        "name": "RecordTriples",
                        "strict": True,
                        "schema": output_schema(),
                    },
                },
            }
            validation_errors = 0
            for attempt in range(attempts):
                if not tracker.reserve(key):
                    return None
                started = time.monotonic()
                log = {"input": group, "request": body, "attempt": attempt + 1}
                retry_after = 0
                try:
                    response = client.post("chat/completions", json=body)
                except httpx.HTTPError as error:
                    log.update(error_type=type(error).__name__, seconds=time.monotonic() - started)
                    tracker.api_result(key, error=type(error).__name__)
                else:
                    log.update(status=response.status_code, seconds=time.monotonic() - started)
                    try:
                        raw = response.json()
                    except ValueError:
                        raw = {}
                    log["raw_response"] = raw
                    tracker.api_result(
                        key,
                        status=response.status_code,
                        usage=raw.get("usage") if isinstance(raw, dict) else None,
                    )
                    if response.status_code == 200:
                        try:
                            choice = raw["choices"][0]
                            if choice["finish_reason"] != "stop":
                                raise ValueError("unfinished_output")
                            extracted = Extraction.model_validate_json(choice["message"]["content"])
                            extracted.check_input(group)
                            saved = {
                                "input": group,
                                "config": config,
                                "output": extracted.model_dump(),
                                "usage": raw.get("usage", {}),
                                "seconds": log["seconds"],
                            }
                            atomic_json(output / "attempts" / f"{key}-{time.time_ns()}.json", log)
                            atomic_json(output / "responses" / f"{key}.json", saved)
                            tracker.complete(group, saved)
                            return saved
                        except (ValueError, KeyError, TypeError, IndexError) as error:
                            validation_errors += 1
                            log.update(validation_error=type(error).__name__)
                            with tracker.lock:
                                tracker.data["validation_errors"] += 1
                            if validation_errors >= 3:
                                tracker.pause("repeated_invalid_output")
                    try:
                        retry_after = float(response.headers.get("Retry-After", "0"))
                    except ValueError:
                        pass
                atomic_json(output / "attempts" / f"{key}-{time.time_ns()}.json", log)
                if tracker.stop.is_set():
                    return None
                if attempt + 1 == attempts:
                    tracker.pause("batch_retry_limit")
                    return None
                delay = max(backoff * 2**attempt, retry_after)
                with tracker.lock:
                    tracker.data["retry_waiting"] += 1
                    tracker.event("retry_wait", batch=key, seconds=delay, next_attempt=attempt + 2)
                interrupted = tracker.stop.wait(delay)
                with tracker.lock:
                    tracker.data["retry_waiting"] -= 1
                if interrupted:
                    return None
            return None

        iterator = iter(pending_groups)
        with ThreadPoolExecutor(max_workers=workers) as pool:
            pending = {}

            def submit():
                if tracker.stop.is_set():
                    return
                pair = next(iterator, None)
                if pair is not None:
                    pending[pool.submit(process, pair)] = pair[1]

            for _ in range(workers):
                submit()
            while pending:
                finished, _ = wait(pending, timeout=1, return_when=FIRST_COMPLETED)
                if (output / "PAUSE").exists():
                    tracker.pause("manual_pause_file")
                for future in finished:
                    key = pending.pop(future)
                    try:
                        saved = future.result()
                    except Exception:
                        tracker.pause("unexpected_worker_error")
                        raise
                    if saved is not None:
                        results[key] = saved
                    submit()
    complete = len(results) == len(groups)
    tracker.data["state"] = "completed" if complete else "paused"
    tracker.event("run_finished", complete=complete)
    atomic_json(output / "usage.json", tracker.data)
    if complete:
        atomic_json(output / "extractions.json", [results[key] for key in keys])
    return tracker.data
