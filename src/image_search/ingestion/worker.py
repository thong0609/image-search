"""Single-admission local importer; PostgreSQL advisory lock survives no process crash.

Staging artifacts contain source metadata/media only. Vectors persist in Qdrant.
Each item is checkpointed before publication; retries reuse staged vectors.
"""

import hashlib
import io
import json

import httpx
import sqlalchemy as sa
from PIL import Image, ImageOps
from qdrant_client import models

from image_search.adapters.postgres.schema import jobs, search_configs
from image_search.adapters.qdrant.vectors import point_id
from image_search.baseline.download import fetch_bytes
from image_search.embedding.encoder import load_encoder, normalize, processor_hash
from image_search.embedding.settings import EmbeddingSettings


class ImportWorker:
    def __init__(self, engine, client, settings):
        self.engine, self.client, self.settings = engine, client, settings
        self.model = self.processor = None

    def update(self, uid, **values):
        with self.engine.begin() as conn:
            conn.execute(jobs.update().where(jobs.c.id == uid).values(**values))

    def run_once(self):
        # One writer for a local machine. OS/database connection loss releases the lock.
        with self.engine.connect() as lock:
            if not lock.scalar(sa.text("SELECT pg_try_advisory_lock(1948603)")):
                return False
            try:
                return self.process_next()
            finally:
                lock.execute(sa.text("SELECT pg_advisory_unlock(1948603)"))
                lock.commit()

    def process_next(self):
        from image_search.ingestion.publish import Publisher

        with self.engine.begin() as conn:
            root = (
                conn.execute(
                    sa.select(jobs)
                    .where(jobs.c.type == "csv_import", jobs.c.status.in_(["pending", "running"]))
                    .order_by(jobs.c.created_at)
                    .limit(1)
                    .with_for_update()
                )
                .mappings()
                .first()
            )
            if not root:
                return False
            root = dict(root)
            conn.execute(jobs.update().where(jobs.c.id == root["id"]).values(status="running"))
        publisher = Publisher(self.engine, self.client, self.settings, root)
        try:
            with self.engine.begin() as conn:
                conn.execute(sa.text("SELECT pg_advisory_xact_lock(1948602)"))
                active = (
                    conn.execute(
                        sa.select(search_configs)
                        .where(search_configs.c.status == "active")
                        .with_for_update()
                    )
                    .mappings()
                    .one()
                )
                gate = dict(active["maintenance"])
                if gate.get("writes_blocked") and gate.get("import_id") != str(root["id"]):
                    raise ValueError("Maintenance is owned by another operation")
                conn.execute(
                    search_configs.update()
                    .where(search_configs.c.id == active["id"])
                    .values(
                        maintenance={**gate, "writes_blocked": True, "import_id": str(root["id"])}
                    )
                )
            index = publisher.base_index()
            from image_search.embedding.index import load_index

            active = publisher.active()
            from image_search.retrieval.settings import RetrievalSettings

            _, _, existing = load_index(
                collection=active["vector_index"].get(
                    "collection", RetrievalSettings().qdrant_collection
                )
            )
            from image_search.baseline.records import REQUIRED_COLUMNS

            known = {
                (r["entity_id"], r["image_url"]): r
                for p in existing.payloads.values()
                for r in p["records"]
            }
            existing.client.close()
            embedding = EmbeddingSettings()
            stage = f"image_search_import_{root['id'].hex}"
            if not self.client.collection_exists(stage):
                self.client.create_collection(
                    stage,
                    vectors_config=models.VectorParams(
                        size=index["shape"][1], distance=models.Distance.COSINE
                    ),
                )
            with self.engine.connect() as conn:
                items = [
                    dict(r)
                    for r in conn.execute(
                        sa.select(jobs).where(
                            jobs.c.parent_id == root["id"],
                            jobs.c.type == "csv_item",
                            jobs.c.status.in_(["pending", "running"]),
                        )
                    ).mappings()
                ]
            for start in range(0, len(items), embedding.batch_size):
                batch = items[start : start + embedding.batch_size]
                prepared = []
                for item in batch:
                    incoming = item["payload"]["record"]
                    prior = known.get((incoming["entity_id"], incoming["image_url"]))
                    if prior and all(
                        incoming.get(k, "") == str(prior.get(k) or "") for k in REQUIRED_COLUMNS
                    ):
                        self.update(item["id"], status="skipped", result={"stage": "unchanged"})
                        continue
                    self.update(item["id"], status="running", attempts=item["attempts"] + 1)
                    try:
                        prepared.append((item, self.prepare(item, root)))
                    except Exception as error:
                        self.item_error(item, error)
                if prepared:
                    self.encode(prepared, stage, index, embedding)
            publisher.publish(stage)
            with self.engine.connect() as conn:
                failed = conn.scalar(
                    sa.select(sa.func.count())
                    .select_from(jobs)
                    .where(jobs.c.parent_id == root["id"], jobs.c.status == "failed")
                )
            self.update(root["id"], status="failed" if failed else "succeeded", last_error=None)
        except Exception as error:
            # Staging checkpoints remain; retry root can finish publication after dependency repair.
            self.update(
                root["id"],
                status="failed",
                last_error=f"Công bố chưa hoàn tất ({type(error).__name__}). Có thể thử lại.",
            )
        finally:
            with self.engine.begin() as conn:
                active = (
                    conn.execute(
                        sa.select(search_configs)
                        .where(search_configs.c.status == "active")
                        .with_for_update()
                    )
                    .mappings()
                    .one()
                )
                gate = dict(active["maintenance"])
                if gate.get("import_id") == str(root["id"]):
                    gate.pop("import_id", None)
                    gate["writes_blocked"] = False
                    conn.execute(
                        search_configs.update()
                        .where(search_configs.c.id == active["id"])
                        .values(maintenance=gate)
                    )
        return True

    def prepare(self, item, root):
        folder = self.settings.storage_root / "imports" / str(root["id"])
        folder.mkdir(parents=True, exist_ok=True)
        checkpoint = folder / f"{item['id']}.json"
        if checkpoint.exists():
            return json.loads(checkpoint.read_text())
        row = item["payload"]["record"]
        with httpx.Client(timeout=30, trust_env=False) as client:
            data = fetch_bytes(client, row["image_url"], 25 * 1024 * 1024)
        iid = hashlib.sha256(data).hexdigest()
        with Image.open(io.BytesIO(data)) as image:
            if image.format not in ("JPEG", "PNG", "WEBP") or getattr(image, "is_animated", False):
                raise ValueError("Chỉ nhận JPEG, PNG, WebP tĩnh")
            if image.width * image.height > 40_000_000:
                raise ValueError("Ảnh vượt giới hạn 40 megapixel")
            extension = {"JPEG": "jpg", "PNG": "png", "WEBP": "webp"}[image.format]
            image.load()
            rotated = ImageOps.exif_transpose(image).convert("RGB")
        path = folder / f"{iid}.{extension}"
        path.write_bytes(data)
        thumb = folder / f"{iid}.jpg"
        width, height = rotated.size
        rotated.thumbnail((640, 480))
        rotated.save(thumb, "JPEG", quality=82)
        rotated.close()
        record = {
            **row,
            "record_id": "import-" + item["payload"]["source_key"],
            "image_id": iid,
            "download_status": "success",
            "local_path": str(path.resolve()),
            "actual_width": width,
            "actual_height": height,
        }
        result = {
            "record": record,
            "image": {"image_id": iid, "local_path": str(path.resolve())},
            "collection_id": root["payload"]["collection_id"],
        }
        temporary = checkpoint.with_suffix(".tmp")
        temporary.write_text(json.dumps(result, ensure_ascii=False))
        temporary.replace(checkpoint)
        return result

    def encode(self, prepared, stage, index, embedding):
        import torch

        pending = []
        for item, data in prepared:
            points = self.client.retrieve(stage, [point_id(str(item["id"]))])
            if points:
                self.update(item["id"], status="running", result={"stage": "staged"})
            else:
                pending.append((item, data))
        if not pending:
            return
        if self.model is None:
            self.model, self.processor = load_encoder(
                index["config"]["model"],
                index["config"]["revision"],
                embedding.cache_dir,
                embedding.threads,
            )
        if processor_hash(self.processor) != index["processor_sha256"]:
            raise ValueError("Processor khác index đang phục vụ")
        decoded = []
        try:
            for _, data in pending:
                with Image.open(data["image"]["local_path"]) as image:
                    decoded.append(image.convert("RGB"))
            inputs = self.processor(images=decoded, return_tensors="pt")
            with torch.inference_mode():
                vectors = normalize(self.model.get_image_features(**inputs).cpu().numpy())
            self.client.upsert(
                stage,
                [
                    models.PointStruct(
                        id=point_id(str(item["id"])),
                        vector=vector.tolist(),
                        payload=data,
                    )
                    for (item, data), vector in zip(pending, vectors, strict=True)
                ],
                wait=True,
            )
            for item, _ in pending:
                self.update(item["id"], result={"stage": "staged"})
        finally:
            for image in decoded:
                image.close()

    def item_error(self, item, error):
        permanent = isinstance(error, (ValueError, Image.DecompressionBombError))
        self.update(
            item["id"],
            status="failed",
            last_error="Ảnh/URL không hợp lệ."
            if permanent
            else "Tải ảnh thất bại. Có thể thử lại.",
            result={"stage": "download", "retryable": not permanent},
        )
