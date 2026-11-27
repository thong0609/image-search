"""Admin CSV upload, validation preview and durable import progress."""

from typing import Annotated
from uuid import UUID

import sqlalchemy as sa
from fastapi import APIRouter, File, Form, Header, Request, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel, ConfigDict, Field

from image_search.adapters.postgres.schema import jobs
from image_search.api.v1.auth import Admin
from image_search.auth.service import fail
from image_search.ingestion.csv_input import MAX_BYTES, parse_csv
from image_search.ingestion.service import Imports

router = APIRouter(prefix="/v1/admin/imports", tags=["imports"])


async def csv_bytes(file):
    if not (file.filename or "").lower().endswith(".csv"):
        fail("INVALID_MANIFEST", "Chọn file .csv UTF-8.", 422)
    data = await file.read(MAX_BYTES + 1)
    await file.close()
    if len(data) > MAX_BYTES:
        fail("INVALID_MANIFEST", "CSV vượt giới hạn 10 MiB.", 422)
    return data


@router.post("/preview")
async def preview(admin: Admin, file: Annotated[UploadFile, File()]):
    try:
        rows = parse_csv(await csv_bytes(file))
    except ValueError as error:
        fail("INVALID_MANIFEST", str(error), 422)
    from collections import Counter

    return {
        "total": len(rows),
        "counts": dict(Counter(r["status"] for r in rows)),
        "errors": [{"line": r["line"], "message": r["error"]} for r in rows if r["error"]],
    }


@router.post("", status_code=202)
async def submit(
    request: Request,
    admin: Admin,
    file: Annotated[UploadFile, File()],
    collection_id: Annotated[UUID, Form()],
    idempotency_key: Annotated[str, Header(min_length=1, max_length=128)],
):
    try:
        root = Imports(request.app.state.auth.engine).submit(
            await csv_bytes(file), collection_id, admin["id"], idempotency_key
        )
    except ValueError as error:
        fail("INVALID_MANIFEST", str(error), 422)
    return {"import_id": root, "status_url": f"/v1/admin/imports/{root}"}


@router.get("")
def recent(request: Request, admin: Admin):
    with request.app.state.auth.engine.connect() as conn:
        ids = list(
            conn.scalars(
                sa.select(jobs.c.id)
                .where(jobs.c.type == "csv_import")
                .order_by(jobs.c.created_at.desc())
                .limit(30)
            )
        )
    service = Imports(request.app.state.auth.engine)
    return {"items": [service.report(i) for i in ids]}


@router.get("/{root}")
def report(root: UUID, request: Request, admin: Admin):
    return Imports(request.app.state.auth.engine).report(root, True)


class Retry(BaseModel):
    model_config = ConfigDict(extra="forbid")
    item_ids: list[UUID] = Field(default_factory=list, max_length=100)


@router.post("/{root}/retry", status_code=202)
def retry(root: UUID, body: Retry, request: Request, admin: Admin):
    if len(set(body.item_ids)) != len(body.item_ids):
        fail("JOB_NOT_RETRYABLE", "ID dòng bị trùng.", 422)
    Imports(request.app.state.auth.engine).retry(root, body.item_ids)
    return {"queued_item_count": len(body.item_ids)}


@router.get("/{root}/errors.csv")
def errors(root: UUID, request: Request, admin: Admin):
    import csv
    import io

    rows = Imports(request.app.state.auth.engine).report(root, True)["items"]
    stream = io.StringIO()
    writer = csv.writer(stream)
    writer.writerow(["line", "status", "error"])
    for row in rows:
        if row["error"]:
            writer.writerow([row["line"], row["status"], row["error"]])
    return Response(
        content="\ufeff" + stream.getvalue(),
        media_type="text/csv",
        headers={"Content-Disposition": 'attachment; filename="import-errors.csv"'},
    )
