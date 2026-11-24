"""API cho giao diện thử nghiệm local; không tự đổi prompt hoặc model."""

from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import FileResponse
from pydantic import BaseModel, ConfigDict, Field

router = APIRouter(prefix="/v1/playground", tags=["playground"])


class PlaygroundQuery(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    text: str = Field(min_length=1, max_length=4000)
    mode: Literal["planner", "search"] = "planner"
    method: Literal["hybrid", "vector", "keyword"] = "hybrid"


def get_playground(request: Request):
    return request.app.state.playground


@router.post("/run")
def run_query(query: PlaygroundQuery, service: Annotated[Any, Depends(get_playground)]):
    from image_search.playground.service import PlaygroundBusy

    try:
        return service.run(query.text, query.mode, query.method)
    except PlaygroundBusy:
        raise HTTPException(409, "Một truy vấn đang chạy. Hãy đợi lượt đó hoàn tất.") from None
    except ValueError:
        raise HTTPException(
            503, "Không chạy được pipeline. Kiểm tra cấu hình và dữ liệu backend."
        ) from None
    except Exception:
        # Không trả exception của DB/provider vì có thể chứa đường dẫn hoặc thông tin cấu hình.
        raise HTTPException(
            503, "Backend chưa sẵn sàng. Kiểm tra OpenAI, Qdrant và Neo4j."
        ) from None


@router.get("/images/{image_id}")
def preview_image(image_id: str, service: Annotated[Any, Depends(get_playground)]):
    # Chỉ phục vụ ID đã có trong corpus, không nhận đường dẫn từ trình duyệt.
    path = service.image_path(image_id)
    if path is None:
        raise HTTPException(404, "Không tìm thấy ảnh.")
    return FileResponse(path, headers={"X-Content-Type-Options": "nosniff"})
