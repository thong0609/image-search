"""Tái sử dụng encoder đã pin theo image index; mỗi instance chỉ nạp model một lần."""

import time
from pathlib import Path

import numpy as np
import torch
from PIL import Image

from image_search.baseline.vectors import load_encoder, load_index, normalize, processor_hash
from image_search.planner.schemas import QueryPlan


def plan_steps(predictions):
    items, skipped, seen = [], [], set()
    for row in predictions:
        qid = row.get("query_id")
        if not isinstance(qid, str) or not qid.strip() or qid in seen:
            raise ValueError("Query ID rỗng/trùng")
        seen.add(qid)
        if row.get("status") == "error":
            skipped.append({"query_id": qid, "reason": "planner_error"})
            continue
        if row.get("status") != "ok":
            raise ValueError(f"{qid}: status cần là ok/error")
        plan = QueryPlan.model_validate(row["plan"])
        if plan.needs_clarification:
            skipped.append({"query_id": qid, "reason": "needs_clarification"})
            continue
        for step in plan.steps:
            items.append(
                {
                    "row_index": len(items),
                    "query_id": qid,
                    "step_id": step.id,
                    "target_id": step.target_id,
                    "action": step.action,
                    "search_text": step.search_text,
                    "depends_on": step.depends_on,
                    "entity_mention": step.entity_mention,
                    "conditions": step.conditions,
                    "count": step.count,
                }
            )
    return items, skipped


class Siglip2Embedding:
    def __init__(self, settings):
        self.settings = settings
        started = time.perf_counter()
        self.corpus, self.index, self.vector_store = load_index()
        self.index_check_seconds = time.perf_counter() - started
        config = self.index["config"]
        started = time.perf_counter()
        self.model, self.processor = load_encoder(
            config["model"], config["revision"], settings.cache_dir, settings.threads
        )
        self.model_load_seconds = time.perf_counter() - started
        if processor_hash(self.processor) != self.index["processor_sha256"]:
            raise ValueError("Processor không khớp image index; cần index phiên bản mới")
        self.dimensions = self.vector_store.dimensions
        self.max_length = self.model.config.text_config.max_position_embeddings

    def encode_texts(self, texts):
        if not texts or any(not isinstance(t, str) or not t.strip() for t in texts):
            raise ValueError("Danh sách text rỗng hoặc có text không hợp lệ")
        batches, details = [], []
        for start in range(0, len(texts), self.settings.batch_size):
            batch = texts[start : start + self.settings.batch_size]
            # Đếm token bằng cùng processor để ghi rõ query nào bị cắt.
            raw = self.processor(text=batch, padding=False, truncation=False)["input_ids"]
            details.extend(
                {"token_count": len(ids), "truncated": len(ids) > self.max_length} for ids in raw
            )
            inputs = self.processor(
                text=batch,
                padding="max_length",
                truncation=True,
                max_length=self.max_length,
                return_tensors="pt",
            )
            with torch.inference_mode():
                features = self.model.get_text_features(**inputs)
            vectors = normalize(features.cpu().numpy())
            if vectors.shape != (len(batch), self.dimensions):
                raise ValueError("Text vector không cùng số chiều với image index")
            batches.append(vectors)
        return np.concatenate(batches), details

    def verify_image_samples(self, count=3):
        if not 1 <= count <= len(self.corpus["images"]):
            raise ValueError("Số ảnh kiểm tra không hợp lệ")
        positions = np.linspace(0, len(self.corpus["images"]) - 1, count, dtype=int)
        checks = []
        for position in positions:
            row = self.corpus["images"][int(position)]
            with Image.open(Path(row["local_path"])) as source:
                image = source.convert("RGB")
            try:
                inputs = self.processor(images=[image], return_tensors="pt")
                with torch.inference_mode():
                    features = self.model.get_image_features(**inputs)
                vector = normalize(features.cpu().numpy())[0]
            finally:
                image.close()
            stored = self.vector_store.vector_for(row["image_id"])
            error = float(np.max(np.abs(vector - stored)))
            if not np.allclose(vector, stored, atol=1e-5, rtol=1e-4):
                raise ValueError(f"Mã hóa lại không khớp index: {row['image_id']}")
            checks.append(
                {
                    "image_id": row["image_id"],
                    "max_abs_error": error,
                    "cosine": float(vector @ stored),
                }
            )
        return checks
