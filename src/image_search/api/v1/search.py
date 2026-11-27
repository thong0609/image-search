"""API màn hình tìm ảnh; chỉ phục vụ ảnh có trong corpus."""

import logging
import re
import unicodedata
from typing import Annotated, Any, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import FileResponse
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from image_search.api.v1.auth import User

router = APIRouter(prefix="/v1", tags=["search"])
IMAGE_HEADERS = {"X-Content-Type-Options": "nosniff", "Cache-Control": "no-store"}


class SearchFilters(BaseModel):
    model_config = ConfigDict(extra="forbid")
    collection_ids: list[UUID] | None = Field(default=None, min_length=1, max_length=50)
    orientation: Literal["landscape", "portrait", "square"] | None = None
    min_width: int | None = Field(default=None, gt=0, strict=True)
    min_height: int | None = Field(default=None, gt=0, strict=True)

    @field_validator("collection_ids")
    @classmethod
    def unique_collections(cls, value):
        if value and len(set(value)) != len(value):
            raise ValueError("Collection trùng")
        return value


class SearchQuery(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    query: str | None = Field(default=None, min_length=1, max_length=500)
    filters: SearchFilters | None = None
    cursor: str | None = Field(default=None, max_length=2000)
    limit: int = Field(default=20, ge=1, le=50)

    @field_validator("query", mode="before")
    @classmethod
    def normalize(cls, value):
        return unicodedata.normalize("NFC", value).strip() if isinstance(value, str) else value

    @model_validator(mode="after")
    def query_or_cursor(self):
        if bool(self.query) == bool(self.cursor) or (self.cursor and self.filters is not None):
            raise ValueError("Cần query hoặc cursor, không đồng thời cả hai")
        return self


class SearchItem(BaseModel):
    id: str
    title: str
    caption: str
    width: int | None
    height: int | None
    source_url: str | None
    source_name: str | None


class SearchGroup(BaseModel):
    id: str
    label: str
    approximate: bool = Field(description="Không xác định được nơi chứa; tìm bằng nguyên câu")
    items: list[SearchItem]


class SearchResponse(BaseModel):
    request_id: str
    search_id: str | None = None
    next_cursor: str | None = None
    expires_at: str | None = None
    query: str
    question: str | None = Field(description="Câu hỏi làm rõ; khi có thì groups rỗng")
    planned: bool = Field(description="False khi planner lỗi và chỉ tìm bằng nguyên câu")
    plan_cached: bool = Field(description="Dùng lại kế hoạch của câu đã hỏi, không gọi model")
    groups: list[SearchGroup]
    took_ms: float


def get_search(request: Request):
    return request.app.state.search


Service = Annotated[Any, Depends(get_search)]


@router.post("/search")
def search(body: SearchQuery, request: Request, service: Service) -> SearchResponse:
    try:
        owner = request.headers.get("x-search-owner", "")
        library = service.library
        if library is not None:
            if not re.fullmatch(r"[A-Za-z0-9_-]{32,128}", owner):
                raise HTTPException(
                    400, {"code": "INVALID_SEARCH_OWNER", "message": "Thiếu mã lượt tìm kiếm."}
                )
            if body.cursor:
                sid, offset = library.parse_cursor(body.cursor, owner)
                result = library.page(sid, owner, offset, body.limit)
            else:
                filters = (
                    body.filters.model_dump(mode="json", exclude_none=True) if body.filters else {}
                )
                result = service.search(body.query, filters)
                library.validate_index(service.index)
                sid = library.save_search(result, owner, filters)
                result = library.page(UUID(sid), owner, 0, body.limit)
        else:
            result = service.search(body.query)
        if library is not None:
            with service.lock:
                service.load(False)
                for group in result["groups"]:
                    for item in group["items"]:
                        records = service.records_for(item["id"], set())
                        record = next(
                            (r for r in records if r.get("record_id") == item.get("record_id")),
                            records[0],
                        )
                        item.pop("record_id", None)
                        item.update(
                            title=record["entity_name"],
                            caption=record.get("mo_ta") or "",
                            width=record.get("actual_width"),
                            height=record.get("actual_height"),
                            source_url=record.get("page_url") or None,
                            source_name=record.get("image_domain") or None,
                        )
        return {**result, "request_id": request.state.request_id}
    except HTTPException:
        raise
    except Exception as error:
        logging.getLogger(__name__).warning("Search failed: %s", type(error).__name__)
        raise HTTPException(503, "Tìm kiếm chưa sẵn sàng. Vui lòng thử lại sau.") from None


@router.get("/collections")
def collections(request: Request):
    return {"items": request.app.state.library.collection_list()}


@router.get("/images/{image_id}")
def image(image_id: str, service: Service, user: User):
    with service.lock:
        service.load(False)
        path = service.image_path(image_id)
        if path is None:
            raise HTTPException(404, "Không tìm thấy ảnh.")
        record = service.records_for(image_id, set())[0]
    return {
        "id": image_id,
        "title": record["entity_name"],
        "caption": record.get("mo_ta", ""),
        "width": record.get("actual_width"),
        "height": record.get("actual_height"),
        "source_url": record.get("page_url"),
        "source_name": record.get("image_domain"),
        "thumbnail_url": f"/v1/images/{image_id}/thumbnail",
    }


@router.get("/images/{image_id}/preview")
def preview(image_id: str, service: Service, user: User):
    with service.lock:
        service.load(False)
        path = service.image_path(image_id)
    if path is None:
        raise HTTPException(404, "Không tìm thấy ảnh.")
    return FileResponse(
        path, headers={"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff"}
    )


@router.post("/images/{image_id}/download")
def download(image_id: str, service: Service, user: User):
    with service.lock:
        service.load(False)
        path = service.image_path(image_id)
    if path is None:
        raise HTTPException(404, "Không tìm thấy ảnh.")
    return FileResponse(
        path,
        filename=f"{image_id}{path.suffix}",
        headers={"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff"},
    )


@router.get("/images/{image_id}/thumbnail")
def thumbnail(image_id: str, service: Service):
    with service.lock:
        if not service.images:
            service.load(False)
        path = service.thumbnail_path(image_id)
    if path is None:
        raise HTTPException(404, "Không tìm thấy ảnh.")
    return FileResponse(path, headers=IMAGE_HEADERS)
