"""Isolated ShopAIKey graph pilot. Never uses OPENAI_API_KEY or writes the live graph."""

import argparse
import hashlib
import importlib.util
import json
import time
from pathlib import Path

import httpx
from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_prefix="SHOPAIKEY_", extra="ignore")
    api_key: SecretStr | None = None
    base_url: str = "https://api.shopaikey.com/v1"
    model: str = "gpt-6-luna"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", type=Path, default=Path("var/kaggle-graph-pilot"))
    parser.add_argument("--output-dir", type=Path, default=Path("var/shopaikey-graph-pilot"))
    parser.add_argument("--limit", type=int, default=1, help="Groups to run; 0 = all 50 records")
    parser.add_argument("--list-models", action="store_true")
    parser.add_argument("--max-tokens", type=int, default=4096)
    args = parser.parse_args()
    settings = Settings()
    if not settings.api_key or not settings.api_key.get_secret_value().strip():
        parser.exit(1, "Điền SHOPAIKEY_API_KEY trong .env; không dùng key OpenAI.\n")
    if settings.base_url.rstrip("/") != "https://api.shopaikey.com/v1":
        parser.error("Pilot này chỉ gửi tới https://api.shopaikey.com/v1")
    if args.limit < 0 or args.max_tokens < 1:
        parser.error("limit >= 0; max-tokens > 0")
    with httpx.Client(
        base_url=settings.base_url.rstrip("/") + "/",
        headers={"Authorization": "Bearer " + settings.api_key.get_secret_value()},
        timeout=180,
        follow_redirects=False,
    ) as client:
        models = client.get("models")
        if models.status_code != 200:
            parser.exit(1, f"GET /models: HTTP {models.status_code}; chưa gọi inference.\n")
        ids = [row["id"] for row in models.json()["data"]]
        if args.list_models:
            print(json.dumps([x for x in ids if "luna" in x.lower()], indent=2))
            return
        if settings.model not in ids:
            print("Luna models:", [x for x in ids if "luna" in x.lower()])
            parser.exit(1, "SHOPAIKEY_MODEL không có trong /models; chưa gọi inference.\n")
        # Reuse the exact validator/repair used in the GPU pilot; jsonschema is a CLI-only extra.
        spec = importlib.util.spec_from_file_location(
            "pilot_validator", args.data_dir / "run_pilot.py"
        )
        validator = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(validator)
        schema = json.loads((args.data_dir / "schema.json").read_text())
        prompt = (args.data_dir / "prompt.txt").read_text()
        groups = json.loads((args.data_dir / "inputs.json").read_text())
        if args.limit:
            groups = groups[: args.limit]
        config = {
            "base_url": settings.base_url,
            "model": settings.model,
            "max_tokens": args.max_tokens,
            "groups": groups,
            "prompt": prompt,
            "schema": schema,
        }
        digest = hashlib.sha256(json.dumps(config, sort_keys=True).encode()).hexdigest()
        args.output_dir.mkdir(parents=True, exist_ok=True)
        manifest = args.output_dir / "run.json"
        if manifest.exists() and json.loads(manifest.read_text())["sha256"] != digest:
            parser.error("Output đã có cấu hình khác; chọn output-dir mới")
        manifest.write_text(json.dumps({"sha256": digest, **config}, ensure_ascii=False, indent=2))
        rows = []
        for i, group in enumerate(groups):
            path = args.output_dir / f"response-{i:03}.json"
            if path.exists():
                rows.append(json.loads(path.read_text()))
                continue
            body = {
                "model": settings.model,
                "messages": [
                    {"role": "system", "content": prompt},
                    {"role": "user", "content": json.dumps(group, ensure_ascii=False)},
                ],
                "max_tokens": args.max_tokens,
                "stream": False,
                "response_format": {
                    "type": "json_schema",
                    "json_schema": {"name": "OpenGraph", "strict": True, "schema": schema},
                },
            }
            started = time.perf_counter()
            response = client.post("chat/completions", json=body)
            if response.status_code != 200:
                parser.exit(
                    1, f"Inference HTTP {response.status_code}; dừng, không tự retry/fallback.\n"
                )
            raw = response.json()
            errors, repairs, normalized = [], [], None
            try:
                choice = raw["choices"][0]
                output = json.loads(choice["message"]["content"])
                normalized, repairs = validator.repair_references(output)
                errors = validator.validate(normalized, group, schema)
                if choice["finish_reason"] != "stop":
                    errors.append("truncated_or_unfinished")
            except (ValueError, TypeError, KeyError):
                errors = ["invalid_json_or_response"]
            row = {
                "group": i,
                "records": len(group["records"]),
                "seconds": time.perf_counter() - started,
                "raw_response": raw,
                "normalized_output": normalized,
                "repairs": repairs,
                "errors": errors,
            }
            path.write_text(json.dumps(row, ensure_ascii=False, indent=2))
            rows.append(row)
            print(i, "seconds", round(row["seconds"], 2), "errors", errors, flush=True)
            summary = {
                "requests": len(rows),
                "records": sum(r["records"] for r in rows),
                "valid": sum(not r["errors"] for r in rows),
                "total_seconds": sum(r["seconds"] for r in rows),
                "usage": [r["raw_response"].get("usage") for r in rows],
                "cost": None,
                "note": "No price assumed; structural validity is not semantic accuracy",
            }
            (args.output_dir / "summary.json").write_text(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
