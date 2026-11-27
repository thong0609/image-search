"""Tìm ảnh cho giao diện: giữ engine/encoder dùng chung, phục vụ ảnh trong corpus."""

import copy
import logging
import os
import tempfile
import time
from pathlib import Path
from threading import Lock

from PIL import Image, ImageOps

from image_search.planner.cache import PlanCache, normalize_query
from image_search.planner.heuristic import Decision, HeuristicPlanner
from image_search.planner.schemas import QueryPlan
from image_search.planner.settings import PlannerSettings
from image_search.timing import profile_result, span, timed

THUMBNAIL_SIZE = (640, 480)


class SearchService:
    def __init__(self, thumbnail_dir):
        # Encoder/engine chỉ chạy một lượt tại một thời điểm; planner không bị khóa.
        self.lock = Lock()
        self.thumbnail_dir = Path(thumbnail_dir)
        self.engine = None
        self.encoder = None
        self.images = {}
        self.library = None
        self.index = None
        self.local_planner = HeuristicPlanner()
        self.plans = PlanCache(PlannerSettings().cache_size)

    def load(self, needs_encoder=True):
        from image_search.embedding.settings import EmbeddingSettings
        from image_search.embedding.siglip2 import Siglip2Embedding
        from image_search.retrieval.runtime import load_engine
        from image_search.retrieval.settings import RetrievalSettings

        embedding = EmbeddingSettings()
        retrieval = RetrievalSettings()
        graph_settings = None
        active = None
        if self.library is not None:
            from image_search.graph.settings import GraphSettings

            with self.library.engine.connect() as conn:
                active = self.library.active_config(conn)
            collection = active["vector_index"].get("collection", retrieval.qdrant_collection)
            retrieval = retrieval.model_copy(update={"qdrant_collection": collection})
            graph_settings = GraphSettings().model_copy(
                update={
                    "dataset_id": active["graph_config"].get(
                        "dataset_id", GraphSettings().dataset_id
                    )
                }
            )
            if self.engine is not None and self.engine.vector_store.collection != collection:
                self.engine.vector_store.client.close()
                self.engine.graph_store.driver.close()
                self.engine = None
                if self.encoder is not None:
                    self.encoder.vector_store.client.close()
                    self.encoder = None
        if self.engine is None:
            engine, corpus, index = load_engine(embedding, retrieval, graph_settings=graph_settings)
            self.engine = engine
            self.index = index
            self.local_planner = HeuristicPlanner(
                getattr(engine.graph_store, "planner_entities", ())
            )
            self.images = {r["image_id"]: Path(r["local_path"]) for r in corpus["images"]}
        if self.library is not None:
            self.library.validate_index(self.index)
        if needs_encoder and self.encoder is None:
            self.encoder = Siglip2Embedding(embedding, collection=retrieval.qdrant_collection)

    def prepare(self):
        """Load corpus/BM25/graph/model and warm inference before accepting searches."""
        with self.lock:
            self.load()
            vectors, _ = self.encoder.encode_texts(["ảnh"])
            self.engine.search("ảnh", vectors[0], "hybrid", 1)

    def local_plan(self, text):
        if PlannerSettings().local_mode == "off":
            return Decision(None, "disabled")
        # Refresh active snapshot before using its names. No per-query graph name lookup.
        with self.lock:
            self.load(False)
            return self.local_planner.decide(text)

    @timed("planner_ms")
    def plan(self, text, diagnostics=None):
        """(Kế hoạch hoặc None nếu planner không dùng được, có lấy từ cache không)."""
        from image_search.planner.router import PROMPT, make_client, route_query

        settings = PlannerSettings()
        decision = self.local_plan(text)
        if diagnostics is not None:
            diagnostics.update(decision.metadata())
        if decision.plan is not None:
            return decision.plan, False

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

    def retrieve(self, text, plan, method="hybrid", filters=None):
        from image_search.retrieval.listing import search_list

        waiting = time.perf_counter()
        with self.lock:
            wait_ms = (time.perf_counter() - waiting) * 1000
            prepared = time.perf_counter()
            self.load(method != "keyword")
            engine = copy.copy(self.engine)
            if self.library is not None:
                engine.visible_images = self.library.visible()
            if filters:
                engine.filtered_images = self.matching_images(filters)
            prepare_ms = (time.perf_counter() - prepared) * 1000
            result = search_list(engine, self.encoder, text, plan, method)
            result["timing_ms"].update(queue=wait_ms, preparation=prepare_ms)
            return result

    def records_for(self, image_id, scope):
        """Record thuộc nơi chứa; ảnh từ câu tìm chung có thể nằm ngoài phạm vi đó."""
        records = self.engine.catalog.records[image_id]
        return [r for r in records if r["entity_id"] in scope] or records

    def matching_images(self, filters):
        allowed = (
            self.library.visible(filters["collection_ids"])
            if self.library and filters.get("collection_ids")
            else set(self.images)
        )
        result = set()
        for iid in allowed:
            rows = self.engine.catalog.records.get(iid, [])
            if not rows:
                continue
            row = rows[0]
            width, height = row.get("actual_width"), row.get("actual_height")
            if filters.get("min_width") and (not width or width < filters["min_width"]):
                continue
            if filters.get("min_height") and (not height or height < filters["min_height"]):
                continue
            orientation = filters.get("orientation")
            if orientation:
                if not width or not height:
                    continue
                actual = (
                    "landscape" if width > height else "portrait" if height > width else "square"
                )
                if actual != orientation:
                    continue
            result.add(iid)
        return result

    @profile_result
    def search(self, text, filters=None):
        started = time.perf_counter()
        planner = {}
        with span("plan_total_ms"):
            plan, cached = self.plan(text, diagnostics=planner)
        result = (
            self.retrieve(text, plan, filters=filters) if filters else self.retrieve(text, plan)
        )
        groups = []
        for group in result["groups"]:
            scope = set(group.get("entity_scope") or [])
            items = []
            for row in group["results"]:
                record = self.records_for(row["image_id"], scope)[0]
                items.append(
                    {
                        "id": row["image_id"],
                        "record_id": record.get("record_id"),
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
            "planner": {**planner, "cached": cached},
            "timing_ms": result.get("timing_ms", {}),
            "groups": groups,
            "took_ms": (time.perf_counter() - started) * 1000,
        }

    def image_path(self, image_id):
        if self.library is not None:
            self.library.require_visible(image_id)
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
