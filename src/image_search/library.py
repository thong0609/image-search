"""SQL publication registry for the existing, validated Qdrant corpus.

Metadata and embeddings stay in Qdrant. This registry supplies lifecycle checks,
collections and finite search snapshots for the website.
"""

import base64
import hashlib
import json
import secrets
from datetime import UTC, datetime, timedelta
from uuid import NAMESPACE_URL, UUID, uuid4, uuid5

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import insert

from image_search.adapters.postgres.schema import (
    audit_events,
    collections,
    image_versions,
    images,
    search_configs,
    search_sessions,
)
from image_search.adapters.qdrant.vectors import point_id
from image_search.auth.service import fail, token_hash

SOURCE = "approved-corpus"
COLLECTION = uuid5(NAMESPACE_URL, "image-search:approved-corpus")


class Library:
    def __init__(self, engine, signing_key):
        self.engine = engine
        self.signing_key = signing_key

    def bootstrap(self, index):
        """Register only a validated existing index; never revive deleted images."""
        config_id = uuid5(NAMESPACE_URL, index["index_sha256"] + index["search_metadata_sha256"])
        with self.engine.begin() as conn:
            conn.execute(sa.text("SELECT pg_advisory_xact_lock(1948602)"))
            active = (
                conn.execute(sa.select(search_configs).where(search_configs.c.status == "active"))
                .mappings()
                .first()
            )
            if active and active["id"] != config_id:
                fail("CONFIG_CHANGED", "Cần bảo trì để chuyển index khác.", 409)
            conn.execute(
                insert(collections)
                .values(id=COLLECTION, name="Kho ảnh đã duyệt")
                .on_conflict_do_nothing()
            )
            conn.execute(
                insert(search_configs)
                .values(
                    id=config_id,
                    status="active",
                    encoder_config=index["config"],
                    vector_index={
                        "index_sha256": index["index_sha256"],
                        "metadata_sha256": index["search_metadata_sha256"],
                    },
                    fusion_config={"branches": ["image", "keyword"], "rrf_k": 60},
                    activated_at=datetime.now(UTC),
                )
                .on_conflict_do_nothing()
            )
            for iid in index["image_ids"]:
                uid = UUID(point_id(iid))
                created = conn.execute(
                    insert(images)
                    .values(
                        id=uid,
                        collection_id=COLLECTION,
                        source_id=SOURCE,
                        source_item_key=iid,
                    )
                    .on_conflict_do_nothing()
                    .returning(images.c.id)
                ).scalar()
                if created is None:
                    continue
                conn.execute(
                    image_versions.insert().values(
                        image_id=uid,
                        version=1,
                        input_revision=1,
                        input_payload_hash=index["search_metadata_sha256"],
                        source_config_ref=SOURCE,
                        source_config_hash=index["index_sha256"],
                        processing_status="ready",
                        index_state={
                            "point_id": point_id(iid),
                            "config_id": str(config_id),
                            "vector": "ready",
                            "graph": "ready",
                        },
                    )
                )
                conn.execute(images.update().where(images.c.id == uid).values(current_version=1))
        return len(index["image_ids"])

    def active_config(self, conn):
        row = (
            conn.execute(sa.select(search_configs).where(search_configs.c.status == "active"))
            .mappings()
            .first()
        )
        if not row:
            fail("CATALOG_NOT_READY", "Kho ảnh chưa được khởi tạo cho website.", 503)
        if row["maintenance"].get("search_blocked"):
            fail("MAINTENANCE_MODE", "Kho ảnh đang bảo trì. Vui lòng thử lại sau.", 503)
        return row

    def validate_index(self, index):
        with self.engine.connect() as conn:
            active = self.active_config(conn)["vector_index"]
            if (
                active.get("index_sha256") != index["index_sha256"]
                or active.get("metadata_sha256") != index["search_metadata_sha256"]
            ):
                fail("CONFIG_CHANGED", "Catalog và index chưa đồng bộ. Cần bảo trì.", 503)

    def visible(self, collection_ids=None):
        with self.engine.connect() as conn:
            self.active_config(conn)
            query = sa.select(images.c.source_item_key).where(
                images.c.source_id == SOURCE,
                images.c.lifecycle == "active",
                images.c.current_version.is_not(None),
            )
            if collection_ids is not None:
                query = query.where(images.c.collection_id.in_(collection_ids))
            return set(conn.scalars(query))

    def require_visible(self, iid):
        with self.engine.connect() as conn:
            found = conn.scalar(
                sa.select(images.c.id).where(
                    images.c.source_id == SOURCE,
                    images.c.source_item_key == iid,
                    images.c.lifecycle == "active",
                    images.c.current_version.is_not(None),
                )
            )
            if not found:
                fail("RESOURCE_NOT_FOUND", "Không tìm thấy ảnh.", 404)

    def collection_list(self):
        with self.engine.connect() as conn:
            rows = conn.execute(
                sa.select(collections)
                .where(collections.c.status == "active")
                .order_by(collections.c.name)
            ).mappings()
            return [{"id": str(r["id"]), "name": r["name"]} for r in rows]

    def delete(self, iid, revision, actor):
        with self.engine.begin() as conn:
            conn.execute(sa.text("SELECT pg_advisory_xact_lock(1948602)"))
            config = self.active_config(conn)
            if config["maintenance"].get("writes_blocked"):
                fail("MAINTENANCE_MODE", "Kho ảnh đang bảo trì.", 503)
            row = (
                conn.execute(
                    sa.select(images)
                    .where(images.c.source_id == SOURCE, images.c.source_item_key == iid)
                    .with_for_update()
                )
                .mappings()
                .first()
            )
            if not row:
                fail("RESOURCE_NOT_FOUND", "Không tìm thấy ảnh.", 404)
            if row["metadata_revision"] != revision:
                fail("STALE_VERSION", "Ảnh đã thay đổi. Hãy tải lại.", 409)
            if row["lifecycle"] != "deleted":
                conn.execute(
                    images.update()
                    .where(images.c.id == row["id"])
                    .values(
                        lifecycle="deleted",
                        deleted_at=datetime.now(UTC),
                        updated_at=datetime.now(UTC),
                        metadata_revision=revision + 1,
                    )
                )
                conn.execute(
                    audit_events.insert().values(
                        id=uuid4(),
                        actor_id=actor,
                        action="image.delete",
                        resource_type="image",
                        resource_id=iid,
                        safe_context={"revision": revision + 1},
                    )
                )
            return {
                "image_id": iid,
                "lifecycle": "deleted",
                "metadata_revision": revision + (row["lifecycle"] != "deleted"),
                "purge_status": "retained",
            }

    def admin_images(self, cursor=None, limit=50):
        with self.engine.connect() as conn:
            query = sa.select(images).where(images.c.source_id == SOURCE).order_by(images.c.id)
            if cursor:
                query = query.where(images.c.id > cursor)
            rows = conn.execute(query.limit(limit + 1)).mappings().all()
            items = [
                {
                    "id": r["source_item_key"],
                    "lifecycle": r["lifecycle"],
                    "collection_id": str(r["collection_id"]),
                    "metadata_revision": r["metadata_revision"],
                    "current_version": r["current_version"],
                }
                for r in rows[:limit]
            ]
            return {
                "items": items,
                "next_cursor": str(rows[limit - 1]["id"]) if len(rows) > limit else None,
            }

    def save_search(self, result, owner, filters):
        now, sid = datetime.now(UTC), uuid4()
        with self.engine.begin() as conn:
            config = self.active_config(conn)
            conn.execute(search_sessions.delete().where(search_sessions.c.expires_at < now))
            conn.execute(
                search_sessions.insert().values(
                    id=sid,
                    owner_key_hash=token_hash(owner),
                    query_hash=hashlib.sha256(result["query"].encode()).hexdigest(),
                    filters=filters,
                    config_id=config["id"],
                    graph_revision=config["graph_revision"],
                    query_plan={k: v for k, v in result.items() if k != "groups"},
                    items=[
                        {
                            **g,
                            "items": [
                                {"id": r["id"], "record_id": r.get("record_id")} for r in g["items"]
                            ],
                        }
                        for g in result["groups"]
                    ],
                    expires_at=now + timedelta(minutes=15),
                )
            )
        return str(sid)

    def page(self, sid, owner, offset, limit):
        with self.engine.connect() as conn:
            config = self.active_config(conn)
            row = (
                conn.execute(sa.select(search_sessions).where(search_sessions.c.id == sid))
                .mappings()
                .first()
            )
            if not row or row["owner_key_hash"] != token_hash(owner):
                fail("INVALID_CURSOR", "Lượt tìm kiếm không hợp lệ.", 400)
            if row["expires_at"] <= datetime.now(UTC) or row["config_id"] != config["id"]:
                fail("SEARCH_EXPIRED", "Lượt tìm kiếm đã hết hạn. Hãy tìm lại.", 410)
            visible = set(
                conn.scalars(
                    sa.select(images.c.source_item_key).where(
                        images.c.source_id == SOURCE,
                        images.c.lifecycle == "active",
                        images.c.current_version.is_not(None),
                    )
                )
            )
            groups, more, next_positions = [], False, {}
            for group in row["items"]:
                items = group["items"]
                position = offset.get(group["id"], 0) if isinstance(offset, dict) else offset
                selected = []
                while position < len(items) and len(selected) < limit:
                    item = items[position]
                    position += 1
                    if item["id"] in visible:
                        selected.append(item)
                more |= position < len(items)
                next_positions[group["id"]] = position
                groups.append({**group, "items": selected})
            return {
                **row["query_plan"],
                "groups": groups,
                "search_id": str(sid),
                "expires_at": row["expires_at"].isoformat(),
                "next_cursor": self.cursor(sid, next_positions, owner) if more else None,
            }

    def cursor(self, sid, positions, owner):
        import hmac

        payload = json.dumps([str(sid), positions], separators=(",", ":"))
        data = base64.urlsafe_b64encode(payload.encode()).decode().rstrip("=")
        signature = hmac.new(
            self.signing_key.read_bytes(), (data + owner).encode(), "sha256"
        ).hexdigest()
        return f"{data}.{signature}"

    def parse_cursor(self, value, owner):
        try:
            data, signature = value.split(".")
            sid, positions = json.loads(base64.urlsafe_b64decode(data + "=" * (-len(data) % 4)))
            if not secrets.compare_digest(self.cursor(sid, positions, owner), value):
                raise ValueError
            if not isinstance(positions, dict) or len(positions) > 5:
                raise ValueError
            if any(
                not isinstance(k, str) or type(v) is not int or not 0 <= v <= 200
                for k, v in positions.items()
            ):
                raise ValueError
            return UUID(sid), positions
        except (ValueError, TypeError, UnicodeError):
            fail("INVALID_CURSOR", "Con trỏ tìm kiếm không hợp lệ.", 400)
