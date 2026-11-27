"""Build immutable Qdrant/Neo4j generations, then activate their SQL pointer."""

import copy
from datetime import UTC, datetime
from uuid import NAMESPACE_URL, UUID, uuid5

import numpy as np
import sqlalchemy as sa

from image_search.adapters.neo4j.client import create_graph_driver
from image_search.adapters.neo4j.store import GraphStore
from image_search.adapters.postgres.schema import image_versions, images, jobs, search_configs
from image_search.adapters.qdrant.metadata import name_key, sync_metadata
from image_search.adapters.qdrant.vectors import QdrantVectors, point_id
from image_search.embedding.index import load_index
from image_search.graph.extraction import digest
from image_search.graph.settings import GraphSettings
from image_search.library import SOURCE
from image_search.retrieval.catalog import Catalog
from image_search.retrieval.settings import RetrievalSettings


class Publisher:
    def __init__(self, engine, client, settings, root):
        self.engine, self.client, self.settings, self.root = engine, client, settings, root

    def active(self):
        with self.engine.connect() as conn:
            return dict(
                conn.execute(sa.select(search_configs).where(search_configs.c.status == "active"))
                .mappings()
                .one()
            )

    def base_index(self):
        active = self.active()
        _, index, store = load_index(
            collection=active["vector_index"].get(
                "collection", RetrievalSettings().qdrant_collection
            )
        )
        store.client.close()
        return index

    def publish(self, stage):
        active = self.active()
        old_collection = active["vector_index"].get(
            "collection", RetrievalSettings().qdrant_collection
        )
        _, old, source = load_index(collection=old_collection)
        gs = GraphSettings()
        driver = create_graph_driver(
            gs.model_copy(
                update={"dataset_id": active["graph_config"].get("dataset_id", gs.dataset_id)}
            )
        )
        try:
            old_graph = GraphStore(
                driver,
                gs.model_copy(
                    update={"dataset_id": active["graph_config"].get("dataset_id", gs.dataset_id)}
                ),
                old["search_metadata_sha256"],
            ).export()
            staged, offset = [], None
            while True:
                points, offset = self.client.scroll(
                    stage, limit=256, offset=offset, with_vectors=True, with_payload=True
                )
                staged.extend(points)
                if offset is None:
                    break
            if not staged:
                return
            stage_hash = digest(
                sorted([p.payload for p in staged], key=lambda p: p["record"]["record_id"])
            )
            if active["vector_index"].get("staging_hash") == stage_hash:
                self.finish_items()
                return
            staged.sort(key=lambda p: p.payload["record"]["record_id"])
            payloads = copy.deepcopy(source.payloads)
            vectors = {iid: source.vector_for(iid) for iid in old["image_ids"]}
            collections = {}
            # New revisions replace the previous logical record wherever it lived.
            changed = {
                (p.payload["record"]["entity_id"], p.payload["record"]["image_url"]) for p in staged
            }
            for payload in payloads.values():
                payload["records"] = [
                    r for r in payload["records"] if (r["entity_id"], r["image_url"]) not in changed
                ]
            for point in staged:
                data, vector = point.payload, point.vector
                row, image = data["record"], data["image"]
                iid = row["image_id"]
                payloads.setdefault(iid, {"records": [], "image": image})["records"].append(row)
                vectors[iid] = np.array(vector, dtype=np.float32)
                collections[iid] = UUID(data["collection_id"])
            payloads = {iid: p for iid, p in payloads.items() if p["records"]}
            ids = sorted(payloads)
            generation = (
                "image_search_web_" + self.root["id"].hex + digest([p.payload for p in staged])[:12]
            )
            index = {**old, "image_ids": ids, "shape": [len(ids), old["shape"][1]]}
            index["index_sha256"] = digest(
                [old["index_sha256"], str(self.root["id"]), ids, [p.payload for p in staged]]
            )
            store = QdrantVectors(self.client, generation, index["index_sha256"], old["shape"][1])
            records = [r for p in payloads.values() for r in p["records"]]
            catalog = Catalog(records, ids)
            store.upload(
                ids,
                np.array([vectors[i] for i in ids]),
                catalog,
                old["config"]["model"],
                old["config"]["revision"],
            )
            index = sync_metadata(
                store, index, catalog, [payloads[i]["image"] for i in ids], digest(records)
            )
            graph = self.extend_graph(old_graph, index, records)
            new_gs = gs.model_copy(update={"dataset_id": generation})
            target_graph = GraphStore(driver, new_gs, index["search_metadata_sha256"])
            target_graph.import_graph(graph, index, payloads)
            target_graph.validate(index, payloads)
            config_id = uuid5(NAMESPACE_URL, generation)
            with self.engine.begin() as conn:
                conn.execute(sa.text("SELECT pg_advisory_xact_lock(1948602)"))
                current = (
                    conn.execute(
                        sa.select(search_configs)
                        .where(search_configs.c.status == "active")
                        .with_for_update()
                    )
                    .mappings()
                    .one()
                )
                if current["id"] != active["id"]:
                    raise ValueError("Active config changed during import")
                removed = set(old["image_ids"]) - set(ids)
                if removed:
                    conn.execute(
                        images.update()
                        .where(images.c.source_item_key.in_(removed), images.c.source_id == SOURCE)
                        .values(
                            lifecycle="deleted",
                            deleted_at=datetime.now(UTC),
                            metadata_revision=images.c.metadata_revision + 1,
                        )
                    )
                for iid in ids:
                    uid = UUID(point_id(iid))
                    row = (
                        conn.execute(sa.select(images).where(images.c.id == uid).with_for_update())
                        .mappings()
                        .first()
                    )
                    if row:
                        # Byte identity is immutable; never revive a tombstone.
                        continue
                    conn.execute(
                        images.insert().values(
                            id=uid,
                            collection_id=collections[iid],
                            source_id=SOURCE,
                            source_item_key=iid,
                        )
                    )
                    conn.execute(
                        image_versions.insert().values(
                            image_id=uid,
                            version=1,
                            input_revision=1,
                            input_payload_hash=digest(payloads[iid]),
                            source_config_ref="csv",
                            source_config_hash=index["index_sha256"],
                            processing_status="ready",
                            index_state={
                                "vector": "ready",
                                "graph": "ready",
                                "point_id": point_id(iid),
                                "config_id": str(config_id),
                            },
                        )
                    )
                    conn.execute(
                        images.update().where(images.c.id == uid).values(current_version=1)
                    )
                conn.execute(
                    search_configs.update()
                    .where(search_configs.c.id == active["id"])
                    .values(status="retired")
                )
                conn.execute(
                    search_configs.insert().values(
                        id=config_id,
                        status="active",
                        encoder_config=index["config"],
                        vector_index={
                            "collection": generation,
                            "index_sha256": index["index_sha256"],
                            "metadata_sha256": index["search_metadata_sha256"],
                            "import_id": str(self.root["id"]),
                            "staging_hash": stage_hash,
                        },
                        graph_config={"dataset_id": generation},
                        graph_revision=active["graph_revision"] + 1,
                        fusion_config={"branches": ["image", "keyword"], "rrf_k": 60},
                        activated_at=datetime.now(UTC),
                    )
                )
            self.finish_items()
        finally:
            source.client.close()
            driver.close()

    def finish_items(self):
        with self.engine.begin() as conn:
            conn.execute(
                jobs.update()
                .where(jobs.c.parent_id == self.root["id"], jobs.c.status == "running")
                .values(status="succeeded", result={"stage": "published"})
            )

    @staticmethod
    def extend_graph(old, index, records):
        graph = copy.deepcopy(old)
        mapping = {sid: e["entity_id"] for e in graph["entities"] for sid in e["source_ids"]}
        nodes = {e["entity_id"]: e for e in graph["entities"]}
        for row in records:
            sid = row["entity_id"]
            if sid not in mapping:
                eid = str(uuid5(NAMESPACE_URL, "csv-entity:" + sid))
                mapping[sid] = eid
                nodes[eid] = {
                    "entity_id": eid,
                    "name": row["entity_name"],
                    "kind": "place",
                    "context": "",
                    "aliases": [],
                    "categories": [],
                    "source_ids": [sid],
                    "name_keys": [],
                    "category_keys": [],
                }
            node = nodes[mapping[sid]]
            node["aliases"] = sorted(set(node["aliases"]) | {row["entity_name"]})
            node["categories"] = sorted(set(node["categories"]) | {row.get("leaf_label", "")})
            node["name_keys"] = sorted({name_key(n) for n in [node["name"], *node["aliases"]]})
            node["category_keys"] = sorted({name_key(n) for n in node["categories"]})
        graph.update(
            metadata_sha256=index["search_metadata_sha256"],
            image_ids=sorted(index["image_ids"]),
            entities=sorted(nodes.values(), key=lambda e: e["entity_id"]),
            image_links=[
                list(x) for x in sorted({(r["image_id"], mapping[r["entity_id"]]) for r in records})
            ],
        )
        graph.pop("graph_sha256", None)
        return {**graph, "graph_sha256": digest(graph)}
