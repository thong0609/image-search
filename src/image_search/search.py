"""Tìm ảnh cho giao diện: giữ engine/encoder dùng chung, phục vụ ảnh trong corpus."""

import logging
import os
import tempfile
import time
from pathlib import Path
from threading import Lock

from PIL import Image, ImageOps

from image_search.planner.cache import PlanCache, normalize_query
from image_search.planner.schemas import QueryPlan
from image_search.planner.settings import PlannerSettings

THUMBNAIL_SIZE = (640, 480)


class SearchService:
    def __init__(self, thumbnail_dir):
        # Encoder/engine chỉ chạy một lượt tại một thời điểm; planner không bị khóa.
        self.lock = Lock()
        self.thumbnail_dir = Path(thumbnail_dir)
        self.engine = None
        self.encoder = None
        self.images = {}
        self.plans = PlanCache(PlannerSettings().cache_size)

    def load(self, needs_encoder=True):
        from image_search.embedding.settings import EmbeddingSettings
        from image_search.embedding.siglip2 import Siglip2Embedding
        from image_search.retrieval.runtime import load_engine
        from image_search.retrieval.settings import RetrievalSettings

        embedding = EmbeddingSettings()
        if self.engine is None:
            engine, corpus, _ = load_engine(embedding, RetrievalSettings())
            self.engine = engine
            self.images = {r["image_id"]: Path(r["local_path"]) for r in corpus["images"]}
        if needs_encoder and self.encoder is None:
            self.encoder = Siglip2Embedding(embedding)

    def plan(self, text):
        """(Kế hoạch hoặc None nếu planner không dùng được, có lấy từ cache không)."""
        from image_search.planner.router import PROMPT, make_client, route_query

        settings = PlannerSettings()

        def create():
            with make_client(settings) as client:
                result = route_query(text, settings, client)
            if result["status"] != "ok":
                logging.getLogger(__name__).warning("Planner error: %s", result["error_code"])
                return None
            return QueryPlan.model_validate(result["plan"])

        # Đổi prompt/model/mức suy luận thì kế hoạch cũ không được dùng lại.
        key = (normalize_query(text), PROMPT, settings.model, settings.reasoning_effort)
        try:
            return self.plans.get_or_create(key, create)
        except ValueError as error:
            logging.getLogger(__name__).warning("Planner unavailable: %s", type(error).__name__)
            return None, False

    def retrieve(self, text, plan, method="hybrid"):
        from image_search.retrieval.listing import search_list

        with self.lock:
            self.load(method != "keyword")
            return search_list(self.engine, self.encoder, text, plan, method)

    def records_for(self, image_id, scope):
        """Record thuộc nơi chứa; ảnh từ câu tìm chung có thể nằm ngoài phạm vi đó."""
        records = self.engine.catalog.records[image_id]
        return [r for r in records if r["entity_id"] in scope] or records

    def search(self, text):
        started = time.perf_counter()
        plan, cached = self.plan(text)
        result = self.retrieve(text, plan)
        groups = []
        for group in result["groups"]:
            scope = set(group.get("entity_scope") or [])
            items = []
            for row in group["results"]:
                record = self.records_for(row["image_id"], scope)[0]
                items.append(
                    {
                        "id": row["image_id"],
                        "title": record["entity_name"],
                        "caption": record.get("mo_ta") or "",
                        "width": record.get("actual_width"),
                        "height": record.get("actual_height"),
                        "source_url": record.get("page_url") or None,
                        "source_name": record.get("image_domain") or None,
                    }
                )
            groups.append(
                {
                    "id": group["target_id"],
                    "label": group["search_text"],
                    "approximate": group["status"] == "fallback_results",
                    "items": items,
                }
            )
        return {
            "query": text,
            "question": result.get("question"),
            "planned": plan is not None,
            "plan_cached": cached,
            "groups": groups,
            "took_ms": (time.perf_counter() - started) * 1000,
        }

    def image_path(self, image_id):
        path = self.images.get(image_id)
        return path if path is not None and path.is_file() else None

    def thumbnail_path(self, image_id):
        """Ảnh thu nhỏ tạo khi cần, lưu lại trên đĩa."""
        source = self.image_path(image_id)
        if source is None:
            return None
        target = self.thumbnail_dir / f"{image_id}.jpg"
        if target.is_file():
            return target
        self.thumbnail_dir.mkdir(parents=True, exist_ok=True)
        with Image.open(source) as image:
            image.draft("RGB", THUMBNAIL_SIZE)
            thumbnail = ImageOps.exif_transpose(image).convert("RGB")
        thumbnail.thumbnail(THUMBNAIL_SIZE)
        # Ghi file tạm rồi đổi tên để request song song không đọc ảnh dở dang.
        handle, name = tempfile.mkstemp(dir=self.thumbnail_dir, suffix=".tmp")
        try:
            with os.fdopen(handle, "wb") as stream:
                thumbnail.save(stream, "JPEG", quality=82, optimize=True)
            os.replace(name, target)
        except Exception:
            Path(name).unlink(missing_ok=True)
            raise
        return target

    def close(self):
        if self.encoder is not None:
            self.encoder.vector_store.client.close()
        if self.engine is not None:
            self.engine.vector_store.client.close()
            self.engine.graph_store.driver.close()
