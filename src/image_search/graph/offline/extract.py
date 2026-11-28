"""Approved CSV batches, resumable provider requests and bounded retries."""

import json
import time
from collections import defaultdict
from pathlib import Path

import httpx
from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

from image_search.baseline.records import read_approved_records
from image_search.files import read_json, write_json
from image_search.graph.offline.models import Extraction, digest, output_schema


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_prefix="SHOPAIKEY_", extra="ignore")
    api_key: SecretStr
    base_url: str = "https://api.shopaikey.com/v1"
    model: str = "gpt-6-luna"
    max_tokens: int = Field(default=4096, ge=128)
    timeout: float = Field(default=180, gt=0)
    retries: int = Field(default=1, ge=0, le=3)


def atomic_json(path, value):
    path = Path(path)
    temporary = path.with_suffix(".tmp")
    write_json(temporary, value)
    temporary.replace(path)


def prepare(csv_path, max_chars=18000):
    grouped = defaultdict(list)
    for row in read_approved_records(csv_path):
        grouped[row["entity_id"]].append(row)
    groups = []
    for eid, rows in sorted(grouped.items()):
        current = []
        for row in rows:
            record = {k: row[k] for k in ("record_id", "entity_name", "leaf_label", "page_title")}
            record.update(caption=row["mo_ta"], image_url=row["image_url"])
            candidate = {"entity_id": eid, "records": current + [record]}
            if len(json.dumps(candidate, ensure_ascii=False)) > max_chars:
                if current:
                    groups.append({"entity_id": eid, "records": current})
                current = []
                if (
                    len(json.dumps({"entity_id": eid, "records": [record]}, ensure_ascii=False))
                    > max_chars
                ):
                    raise ValueError("Record vượt giới hạn batch; không tự cắt metadata")
            current.append(record)
        if current:
            groups.append({"entity_id": eid, "records": current})
    if not groups:
        raise ValueError("Không có record approve=yes")
    return groups


def run(groups, output, settings, max_requests):
    if settings.base_url.rstrip("/") != "https://api.shopaikey.com/v1":
        raise ValueError("Endpoint không đúng ShopAIKey đã chọn")
    output = Path(output)
    prompt = Path(__file__).with_name("prompt.txt").read_text()
    config = {
        "model": settings.model,
        "base_url": settings.base_url,
        "prompt": prompt,
        "schema": output_schema(),
        "max_tokens": settings.max_tokens,
    }
    responses, calls = [], 0
    with httpx.Client(
        base_url=settings.base_url.rstrip("/") + "/",
        headers={"Authorization": "Bearer " + settings.api_key.get_secret_value()},
        timeout=settings.timeout,
        follow_redirects=False,
    ) as client:
        for group in groups:
            key = digest({"config": config, "input": group})
            path = output / "responses" / f"{key}.json"
            if path.exists():
                saved = read_json(path)
                if saved["input"] != group or saved["config"] != config:
                    raise ValueError("Checkpoint không khớp")
                Extraction.model_validate(saved["output"]).check_input(group)
                responses.append(saved)
                continue
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
            for attempt in range(settings.retries + 1):
                if calls >= max_requests:
                    raise ValueError("Đạt giới hạn request; kết quả đã lưu để tiếp tục")
                calls += 1
                started = time.perf_counter()
                log = {"input": group, "request": body}
                try:
                    response = client.post("chat/completions", json=body)
                    log = {
                        "input": group,
                        "request": body,
                        "status": response.status_code,
                        "seconds": time.perf_counter() - started,
                    }
                    if response.status_code != 200:
                        raise ValueError(f"Provider HTTP {response.status_code}")
                    raw = response.json()
                    log["raw_response"] = raw
                    choice = raw["choices"][0]
                    if choice["finish_reason"] != "stop":
                        raise ValueError("Model trả output chưa hoàn tất")
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
                    atomic_json(path, saved)
                    responses.append(saved)
                    break
                except (httpx.HTTPError, ValueError, KeyError, TypeError) as error:
                    # Avoid serializing exception text containing request credentials.
                    failure = log | {"error_type": type(error).__name__}
                    atomic_json(output / "attempts" / f"{key}-{time.time_ns()}.json", failure)
                    if attempt == settings.retries:
                        raise ValueError("Batch lỗi; xem attempts, chạy lại để tiếp tục") from None
                    time.sleep(min(2**attempt, 4))
    atomic_json(output / "extractions.json", responses)
    atomic_json(
        output / "usage.json",
        {
            "requests_this_run": calls,
            "input_tokens": sum(r["usage"].get("prompt_tokens", 0) for r in responses),
            "output_tokens": sum(r["usage"].get("completion_tokens", 0) for r in responses),
            "cost_usd": None,
        },
    )
    return responses
