"""API cho giao diện thử nghiệm local; không tự đổi prompt hoặc model."""

from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field

from image_search.api.v1.auth import Admin

router = APIRouter(prefix="/v1/playground", tags=["playground"])


class PlaygroundQuery(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    text: str = Field(min_length=1, max_length=4000)
    mode: Literal["planner", "search"] = "planner"
    method: Literal["hybrid", "vector", "keyword"] = "hybrid"


def get_playground(request: Request):
    return request.app.state.playground


@router.post("/run")
def run_query(
    query: PlaygroundQuery, admin: Admin, service: Annotated[Any, Depends(get_playground)]
):
    from image_search.playground import PlaygroundBusy

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
