"""CSV admission and progress backed by the existing jobs table."""

from collections import Counter
from datetime import UTC, datetime
from uuid import uuid4

import sqlalchemy as sa

from image_search.adapters.postgres.schema import collections, jobs, search_configs
from image_search.auth.service import fail
from image_search.ingestion.csv_input import digest, parse_csv


class Imports:
    def __init__(self, engine):
        self.engine = engine

    def submit(self, data, collection_id, actor, key):
        rows = parse_csv(data)
        request_hash = digest([str(collection_id), digest(data.hex())])
        with self.engine.begin() as conn:
            conn.execute(sa.text("SELECT pg_advisory_xact_lock(1948602)"))
            config = (
                conn.execute(sa.select(search_configs).where(search_configs.c.status == "active"))
                .mappings()
                .first()
            )
            if not config:
                fail("CATALOG_NOT_READY", "Kho ảnh chưa sẵn sàng.", 503)
            if config["maintenance"].get("writes_blocked"):
                fail("MAINTENANCE_MODE", "Kho ảnh đang công bố dữ liệu. Hãy thử lại sau.", 503)
            if not conn.scalar(
                sa.select(collections.c.id).where(
                    collections.c.id == collection_id, collections.c.status == "active"
                )
            ):
                fail("INVALID_COLLECTION", "Collection không hợp lệ.", 422)
            dedupe = f"csv:{actor}:{key}"
            existing = (
                conn.execute(sa.select(jobs).where(jobs.c.dedupe_key == dedupe)).mappings().first()
            )
            if existing:
                if existing["request_hash"] != request_hash:
                    fail("IDEMPOTENCY_CONFLICT", "Mã nhập đã dùng với file khác.", 409)
                return str(existing["id"])
            root = uuid4()
            conn.execute(
                jobs.insert().values(
                    id=root,
                    type="csv_import",
                    dedupe_key=dedupe,
                    request_hash=request_hash,
                    created_by=actor,
                    payload={"collection_id": str(collection_id), "total": len(rows)},
                )
            )
            conn.execute(
                jobs.insert(),
                [
                    dict(
                        id=uuid4(),
                        parent_id=root,
                        type="csv_item",
                        dedupe_key=f"{root}:{r['line']}",
                        created_by=actor,
                        status=r["status"],
                        last_error=r["error"],
                        payload=r,
                        result={"stage": "validation", "retryable": False} if r["error"] else {},
                    )
                    for r in rows
                ],
            )
        return str(root)

    def report(self, root, details=False):
        with self.engine.connect() as conn:
            job = (
                conn.execute(sa.select(jobs).where(jobs.c.id == root, jobs.c.type == "csv_import"))
                .mappings()
                .first()
            )
            if not job:
                fail("RESOURCE_NOT_FOUND", "Không tìm thấy lượt nhập.", 404)
            rows = (
                conn.execute(
                    sa.select(jobs)
                    .where(jobs.c.parent_id == root, jobs.c.type == "csv_item")
                    .order_by(jobs.c.created_at, jobs.c.id)
                )
                .mappings()
                .all()
            )
            result = {
                "import_id": str(root),
                "status": job["status"],
                "counts": dict(Counter(r["status"] for r in rows)),
                "total": len(rows),
                "error": job["last_error"],
                "created_at": job["created_at"].isoformat(),
            }
            if details:
                result["items"] = [
                    {
                        "id": str(r["id"]),
                        "line": r["payload"]["line"],
                        "entity_name": r["payload"]["record"].get("entity_name", ""),
                        "status": r["status"],
                        "stage": r["result"].get("stage"),
                        "error": r["last_error"],
                        "retryable": r["result"].get("retryable", False),
                    }
                    for r in sorted(rows, key=lambda r: r["payload"]["line"])
                ]
            return result

    def retry(self, root, ids):
        with self.engine.begin() as conn:
            parent = (
                conn.execute(
                    sa.select(jobs)
                    .where(jobs.c.id == root, jobs.c.type == "csv_import")
                    .with_for_update()
                )
                .mappings()
                .first()
            )
            if not parent or parent["status"] != "failed":
                fail("JOB_NOT_RETRYABLE", "Lượt nhập đang chạy hoặc không tồn tại.", 409)
            rows = (
                conn.execute(
                    sa.select(jobs)
                    .where(jobs.c.parent_id == root, jobs.c.id.in_(ids))
                    .with_for_update()
                )
                .mappings()
                .all()
            )
            if len(rows) != len(ids) or any(
                r["status"] != "failed" or not r["result"].get("retryable") for r in rows
            ):
                fail("JOB_NOT_RETRYABLE", "Có dòng không thể retry.", 409)
            conn.execute(
                jobs.update()
                .where(jobs.c.id.in_(ids))
                .values(
                    status="pending", attempts=0, last_error=None, next_attempt_at=datetime.now(UTC)
                )
            )
            conn.execute(jobs.update().where(jobs.c.id == root).values(status="pending"))
