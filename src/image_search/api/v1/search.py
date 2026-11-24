"""API màn hình tìm ảnh; chỉ phục vụ ảnh có trong corpus."""

import logging
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import FileResponse
from pydantic import BaseModel, ConfigDict, Field

router = APIRouter(prefix="/v1", tags=["search"])
IMAGE_HEADERS = {"X-Content-Type-Options": "nosniff", "Cache-Control": "private, max-age=86400"}


class SearchQuery(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    query: str = Field(min_length=1, max_length=500)


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
def search(body: SearchQuery, service: Service) -> SearchResponse:
    try:
        return service.search(body.query)
    except Exception as error:
        # Không trả exception của DB/provider vì có thể chứa cấu hình hoặc đường dẫn.
        logging.getLogger(__name__).warning("Search failed: %s", type(error).__name__)
        raise HTTPException(503, "Tìm kiếm chưa sẵn sàng. Vui lòng thử lại sau.") from None


@router.get("/images/{image_id}")
def image(image_id: str, service: Service):
    path = service.image_path(image_id)
    if path is None:
        raise HTTPException(404, "Không tìm thấy ảnh.")
    return FileResponse(path, headers=IMAGE_HEADERS)


@router.get("/images/{image_id}/thumbnail")
def thumbnail(image_id: str, service: Service):
    path = service.thumbnail_path(image_id)
    if path is None:
        raise HTTPException(404, "Không tìm thấy ảnh.")
    return FileResponse(path, headers=IMAGE_HEADERS)
