"""Admin lifecycle actions for the published corpus."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Header, Request, Response

from image_search.api.v1.auth import Admin
from image_search.api.v1.search import Service
from image_search.auth.service import fail

router = APIRouter(prefix="/v1/admin", tags=["library"])


@router.get("/images")
def list_images(
    request: Request, service: Service, admin: Admin, cursor: UUID | None = None, limit: int = 50
):
    if not 1 <= limit <= 100:
        fail("INVALID_LIMIT", "Giới hạn phải từ 1 đến 100.", 422)
    result = request.app.state.library.admin_images(cursor, limit)
    with service.lock:
        service.load(False)
        for item in result["items"]:
            records = service.engine.catalog.records.get(item["id"], [])
            item["title"] = records[0]["entity_name"] if records else item["id"]
    return result


@router.delete("/images/{image_id}", status_code=202)
def delete_image(
    image_id: str, request: Request, admin: Admin, if_match: Annotated[str | None, Header()] = None
):
    if if_match is None:
        fail("PRECONDITION_REQUIRED", "Thiếu phiên bản ảnh.", 428)
    try:
        revision = int(if_match.strip('"'))
    except ValueError:
        fail("STALE_VERSION", "Phiên bản không hợp lệ.", 409)
    return request.app.state.library.delete(image_id, revision, admin["id"])


@router.get("/images/{image_id}")
def image_status(image_id: str, request: Request, response: Response, admin: Admin):
    import sqlalchemy as sa

    from image_search.adapters.postgres.schema import image_versions, images
    from image_search.library import SOURCE

    with request.app.state.library.engine.connect() as conn:
        row = (
            conn.execute(
                sa.select(images).where(
                    images.c.source_id == SOURCE, images.c.source_item_key == image_id
                )
            )
            .mappings()
            .first()
        )
        if not row:
            fail("RESOURCE_NOT_FOUND", "Không tìm thấy ảnh.", 404)
        version = (
            conn.execute(
                sa.select(image_versions).where(
                    image_versions.c.image_id == row["id"],
                    image_versions.c.version == row["current_version"],
                )
            )
            .mappings()
            .first()
        )
        response.headers["ETag"] = f'"{row["metadata_revision"]}"'
        state = version["index_state"] if version else {}
        return {
            "image_id": image_id,
            "collection_id": str(row["collection_id"]),
            "lifecycle": row["lifecycle"],
            "current_version": row["current_version"],
            "desired_version": row["desired_version"],
            "metadata_revision": row["metadata_revision"],
            "processing_status": version["processing_status"] if version else "pending",
            "vector_projection_status": state.get("vector", "pending"),
            "graph_projection_status": state.get("graph", "pending"),
            "purge_status": "retained" if row["lifecycle"] == "deleted" else None,
            "updated_at": row["updated_at"],
        }
