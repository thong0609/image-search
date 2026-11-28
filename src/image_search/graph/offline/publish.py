"""Stage a complete generation without modifying the serving graph."""

from uuid import NAMESPACE_URL, uuid5

from qdrant_client import models

from image_search.adapters.qdrant.vectors import save_metadata
from image_search.graph.offline.models import digest


def stage(artifact, encoder, driver, database):
    generation = artifact["generation"]
    if generation != digest({k: v for k, v in artifact.items() if k != "generation"}):
        raise ValueError("Artifact hash không khớp")
    client = encoder.vector_store.client
    collection = "graph_registry_" + generation
    rows = [
        dict(r, registry_kind=kind) for kind in ("entities", "relations") for r in artifact[kind]
    ]
    if not rows:
        raise ValueError("Registry rỗng")
    texts = [r["name"] + (". " + r["definition"] if r.get("definition") else "") for r in rows]
    vectors, details = encoder.encode_texts(texts)
    if any(d["truncated"] for d in details):
        raise ValueError("Registry text bị cắt; cần rút gọn định nghĩa")
    if not client.collection_exists(collection):
        client.create_collection(
            collection,
            vectors_config=models.VectorParams(
                size=encoder.dimensions, distance=models.Distance.COSINE
            ),
        )
    for start in range(0, len(rows), 64):
        client.upsert(
            collection,
            points=[
                models.PointStruct(
                    id=str(uuid5(NAMESPACE_URL, row["id"])), vector=vector.tolist(), payload=row
                )
                for row, vector in zip(
                    rows[start : start + 64], vectors[start : start + 64], strict=True
                )
            ],
            wait=True,
        )
    if client.count(collection, exact=True).count != len(rows):
        raise ValueError("Registry Qdrant thiếu/thừa point")

    save_metadata(
        client,
        collection,
        {
            "generation": generation,
            "encoder": encoder.index["config"],
            "processor_sha256": encoder.index["processor_sha256"],
            "dimensions": encoder.dimensions,
            "registry_sha256": digest(rows),
        },
    )

    # Separate labels and generation: the current GraphStore never reads staging nodes.
    def write(tx):
        tx.run(
            "UNWIND $rows AS r MERGE (e:OfflineEntity {generation:$g,id:r.id}) "
            "SET e.name=r.name,e.aliases=r.aliases,e.scope=r.scope,e.kind=r.kind,"
            "e.source_entity_id=r.source_entity_id,e.record_ids=r.record_ids",
            rows=artifact["entities"],
            g=generation,
        ).consume()
        tx.run(
            "UNWIND $rows AS r MERGE (p:OfflinePredicate {generation:$g,id:r.id}) "
            "SET p.name=r.name,p.aliases=r.aliases,p.definition=r.definition,"
            "p.direction=r.direction",
            rows=artifact["relations"],
            g=generation,
        ).consume()
        tx.run(
            "UNWIND $rows AS r MATCH (a:OfflineEntity {generation:$g,id:r.source}),"
            "(b:OfflineEntity {generation:$g,id:r.target}) "
            "MERGE (a)-[f:OFFLINE_FACT {generation:$g,id:r.id}]->(b) "
            "SET f.predicate_id=r.relation,f.record_ids=r.record_ids",
            rows=artifact["facts"],
            g=generation,
        ).consume()
        counts = tx.run(
            "MATCH (e:OfflineEntity {generation:$g}) RETURN count(e) AS n", g=generation
        ).single()["n"]
        facts = tx.run(
            "MATCH ()-[f:OFFLINE_FACT {generation:$g}]->() RETURN count(f) AS n", g=generation
        ).single()["n"]
        if counts != len(artifact["entities"]) or facts != len(artifact["facts"]):
            raise ValueError("Graph staging không khớp artifact")
        tx.run(
            'MERGE (g:OfflineGeneration {id:$g}) SET g.state="staged",'
            "g.registry_collection=$collection",
            g=generation,
            collection=collection,
        ).consume()

    with driver.session(database=database) as session:
        session.execute_write(write)
    return {
        "generation": generation,
        "state": "staged",
        "registry_collection": collection,
        "encoder": encoder.index["config"],
        "processor_sha256": encoder.index["processor_sha256"],
    }
