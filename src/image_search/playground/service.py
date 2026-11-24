"""Tái sử dụng pipeline hiện tại; chỉ nạp model khi người dùng tìm ảnh."""

import logging
import time
from pathlib import Path
from threading import Lock

from image_search.planner.schemas import QueryPlan
from image_search.planner.settings import PlannerSettings


class PlaygroundBusy(Exception):
    pass


class PlaygroundService:
    def __init__(self):
        self.lock = Lock()
        self.engine = None
        self.encoder = None
        self.images = {}

    def load(self, needs_encoder):
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

    def run(self, text, mode, method):
        # Không xếp hàng thêm các lượt gọi có phí nếu người dùng bấm nhiều lần.
        if not self.lock.acquire(blocking=False):
            raise PlaygroundBusy
        try:
            return self._run(text, mode, method)
        finally:
            self.lock.release()

    def _run(self, text, mode, method):
        from image_search.planner.router import make_client, route_query

        started = time.perf_counter()
        settings = PlannerSettings()
        with make_client(settings) as client:
            planner = route_query(text, settings, client)
        # Kết quả chẩn đoán không chứa credentials hoặc đường dẫn file ảnh.
        result = {
            "text": text,
            "mode": mode,
            "method": method,
            "planner": planner,
            "execution": None,
            "timing_ms": {
                "planner": planner["latency_ms"],
                "startup": 0,
                "embedding": 0,
                "retrieval": 0,
                "total": 0,
            },
        }
        if mode == "search":
            from image_search.retrieval.listing import search_list

            # Planner lỗi vẫn tìm bằng nguyên câu để luôn có danh sách ảnh.
            ok = planner["status"] == "ok"
            plan = QueryPlan.model_validate(planner["plan"]) if ok else None
            if plan is not None and plan.needs_clarification:
                result["execution"] = {
                    "status": "needs_clarification",
                    "question": plan.clarification_question,
                    "groups": [],
                    "trace": [],
                }
            else:
                try:
                    begin = time.perf_counter()
                    self.load(method != "keyword")
                    result["timing_ms"]["startup"] = (time.perf_counter() - begin) * 1000
                    execution = search_list(self.engine, self.encoder, text, plan, method)
                    result["timing_ms"].update(execution.pop("timing_ms"))
                    for group in execution["groups"]:
                        scope = set(group.get("entity_scope") or [])
                        for row in group["results"]:
                            records = self.engine.catalog.records[row["image_id"]]
                            # Ảnh từ câu tìm chung có thể nằm ngoài phạm vi nơi chứa.
                            matched = [r for r in records if r["entity_id"] in scope] or records
                            row["image_url"] = f"/v1/playground/images/{row['image_id']}"
                            row["entity_names"] = sorted({r["entity_name"] for r in matched})
                            row["caption"] = matched[0].get("mo_ta", "") if matched else ""
                    result["execution"] = execution
                except Exception as error:
                    logging.getLogger(__name__).warning(
                        "Playground retrieval failed: %s", type(error).__name__
                    )
                    result["execution"] = {
                        "status": "execution_error",
                        "message": (
                            "Retrieval chưa sẵn sàng. Kiểm tra dữ liệu, Qdrant, Neo4j và encoder."
                        ),
                        "groups": [],
                        "trace": [],
                    }
        result["timing_ms"]["total"] = (time.perf_counter() - started) * 1000
        return result

    def image_path(self, image_id):
        path = self.images.get(image_id)
        if path is None or not path.is_file():
            return None
        return path

    def close(self):
        if self.encoder is not None:
            self.encoder.vector_store.client.close()
        if self.engine is not None:
            self.engine.vector_store.client.close()
            self.engine.graph_store.driver.close()
