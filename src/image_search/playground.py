"""Công cụ xem kế hoạch và kết quả từng bước; dùng chung SearchService."""

import logging
import time
from threading import Lock

from image_search.planner.schemas import QueryPlan
from image_search.planner.settings import PlannerSettings


class PlaygroundBusy(Exception):
    pass


class PlaygroundService:
    def __init__(self, search):
        self.search = search
        self.lock = Lock()

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
                    result["execution"] = self.execute(text, plan, method, result["timing_ms"])
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

    def execute(self, text, plan, method, timing):
        begin = time.perf_counter()
        execution = self.search.retrieve(text, plan, method)
        timing.update(execution.pop("timing_ms"))
        elapsed = (time.perf_counter() - begin) * 1000
        timing["startup"] = elapsed - timing["embedding"] - timing["retrieval"]
        for group in execution["groups"]:
            scope = set(group.get("entity_scope") or [])
            for row in group["results"]:
                matched = self.search.records_for(row["image_id"], scope)
                row["image_url"] = f"/v1/images/{row['image_id']}/thumbnail"
                row["entity_names"] = sorted({r["entity_name"] for r in matched})
                row["caption"] = matched[0].get("mo_ta", "")
        return execution
