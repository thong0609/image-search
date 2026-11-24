"""Graph Image/Entity: import nguyên tử và truy vấn quan hệ có tham số."""

from collections import Counter

from neo4j import Query

from image_search.adapters.qdrant.metadata import name_key
from image_search.modules.graph.build import validate_graph
from image_search.modules.graph.extraction import digest

RELATIONS = ("LOCATED_IN", "PART_OF", "BRANCH_OF")


def graph_content(graph):
    return {
        k: graph[k]
        for k in ("metadata_sha256", "image_ids", "entities", "image_links", "relations")
    }


def validate_mapping(graph, index, payloads):
    if graph["image_ids"] != sorted(index["image_ids"]):
        raise ValueError("Image graph không khớp Qdrant")
    mapping = {}
    for e in graph["entities"]:
        for sid in e["source_ids"]:
            if sid in mapping:
                raise ValueError("Một ID nguồn bị gán hai entity")
            mapping[sid] = e["entity_id"]
    try:
        expected = sorted(
            {(iid, mapping[r["entity_id"]]) for iid, p in payloads.items() for r in p["records"]}
        )
    except KeyError as exc:
        raise ValueError("Graph thiếu entity Qdrant") from exc
    if expected != [tuple(x) for x in graph["image_links"]]:
        raise ValueError("Ánh xạ Image/Entity lệch Qdrant")


class GraphStore:
    def __init__(self, driver, settings, metadata_hash):
        self.driver, self.settings = driver, settings
        self.snapshot, self.dataset = metadata_hash, settings.dataset_id
        self.graph_hash = None

    def read(self, query, **parameters):
        result = self.driver.execute_query(
            Query(query, timeout=self.settings.timeout),
            parameters_={"dataset": self.dataset, "snapshot": self.snapshot, **parameters},
            database_=self.settings.database,
            routing_="r",
        )
        return [r.data() for r in result.records]

    def _export(self, run):
        params = {"dataset": self.dataset}
        nodes = run(
            "MATCH (n {dataset_id:$dataset}) RETURN labels(n) AS labels, properties(n) AS p",
            **params,
        ).data()
        if not nodes or any(set(n["labels"]) not in ({"Image"}, {"Entity"}) for n in nodes):
            raise ValueError("Graph rỗng hoặc còn node nguồn; cần import graph quan hệ")
        if any(n["p"].get("metadata_sha256") != self.snapshot for n in nodes):
            raise ValueError("Graph khác snapshot Qdrant")
        hashes = {n["p"].get("graph_sha256") for n in nodes}
        if len(hashes) != 1 or None in hashes:
            raise ValueError("Graph hash không nhất quán")
        entities = []
        images = []
        for n in nodes:
            p = dict(n["p"])
            for key in ("dataset_id", "metadata_sha256", "graph_sha256"):
                p.pop(key)
            if n["labels"] == ["Image"]:
                images.append(p["image_id"])
            else:
                entities.append(p)
        links = run(
            "MATCH (a {dataset_id:$dataset})-[r]->(b) "
            "RETURN labels(a) AS a_labels, a.image_id AS image_id, "
            "a.entity_id AS subject, type(r) AS predicate, b.entity_id AS object, "
            "b.dataset_id AS target_dataset",
            **params,
        ).data()
        image_links, relations = [], []
        for r in links:
            if r["target_dataset"] != self.dataset:
                raise ValueError("Cạnh vượt dataset")
            if r["predicate"] == "DEPICTS" and r["a_labels"] == ["Image"]:
                image_links.append([r["image_id"], r["object"]])
            elif r["predicate"] in RELATIONS and r["a_labels"] == ["Entity"]:
                relations.append([r["subject"], r["predicate"], r["object"]])
            else:
                raise ValueError("Cạnh ngoài schema")
        graph = {
            "metadata_sha256": self.snapshot,
            "image_ids": sorted(images),
            "entities": sorted(entities, key=lambda e: e["entity_id"]),
            "image_links": sorted(image_links),
            "relations": sorted(relations),
        }
        validate_graph(graph)
        if digest(graph) != next(iter(hashes)):
            raise ValueError("Nội dung graph lệch graph hash")
        return {**graph, "graph_sha256": next(iter(hashes))}

    def export(self):
        with self.driver.session(database=self.settings.database) as session:
            return session.execute_read(lambda tx: self._export(tx.run))

    def validate(self, index, payloads):
        graph = self.export()
        validate_mapping(graph, index, payloads)
        self.graph_hash = graph["graph_sha256"]
        return {
            "nodes": {"Image": len(graph["image_ids"]), "Entity": len(graph["entities"])},
            "relationships": {
                "DEPICTS": len(graph["image_links"]),
                **dict(Counter(r[1] for r in graph["relations"])),
            },
            "graph_sha256": self.graph_hash,
            "metadata_sha256": self.snapshot,
        }

    def import_graph(self, graph, index=None, payloads=None):
        validate_graph(graph)
        if index is not None:
            validate_mapping(graph, index, payloads)
        if (
            graph["metadata_sha256"] != self.snapshot
            or digest(graph_content(graph)) != graph["graph_sha256"]
        ):
            raise ValueError("Sai snapshot hoặc hash artifact graph")
        for label, field in (("Entity", "entity_id"), ("Image", "image_id")):
            self.driver.execute_query(
                f"CREATE CONSTRAINT relation_{label}_id IF NOT EXISTS FOR (n:{label}) "
                f"REQUIRE (n.dataset_id, n.{field}) IS UNIQUE",
                database_=self.settings.database,
            )

        def write(tx):
            params = {
                "dataset": self.dataset,
                "snapshot": self.snapshot,
                "hash": graph["graph_sha256"],
            }
            # Thay duy nhất dataset này, xóa node nguồn cũ trong cùng transaction.
            tx.run(
                "MATCH (n {dataset_id:$dataset}) DETACH DELETE n", dataset=self.dataset
            ).consume()
            for start in range(0, len(graph["entities"]), self.settings.batch_size):
                tx.run(
                    "UNWIND $rows AS row CREATE (n:Entity) SET n=row, n.dataset_id=$dataset, "
                    "n.metadata_sha256=$snapshot, n.graph_sha256=$hash",
                    rows=graph["entities"][start : start + self.settings.batch_size],
                    **params,
                ).consume()
            tx.run(
                "UNWIND $ids AS id CREATE (:Image {dataset_id:$dataset, image_id:id, "
                "metadata_sha256:$snapshot, graph_sha256:$hash})",
                ids=graph["image_ids"],
                **params,
            ).consume()
            tx.run(
                "UNWIND $rows AS row MATCH (i:Image {dataset_id:$dataset,image_id:row[0]}), "
                "(e:Entity {dataset_id:$dataset,entity_id:row[1]}) CREATE (i)-[:DEPICTS]->(e)",
                rows=graph["image_links"],
                dataset=self.dataset,
            ).consume()
            for kind in RELATIONS:
                rows = [r for r in graph["relations"] if r[1] == kind]
                tx.run(
                    "UNWIND $rows AS row MATCH (a:Entity {dataset_id:$dataset,entity_id:row[0]}), "
                    "(b:Entity {dataset_id:$dataset,entity_id:row[2]}) "
                    f"CREATE (a)-[:{kind}]->(b)",
                    rows=rows,
                    dataset=self.dataset,
                ).consume()
            saved = self._export(tx.run)
            if graph_content(saved) != graph_content(graph):
                raise ValueError("Import graph không đầy đủ")
            return saved["graph_sha256"]

        with self.driver.session(database=self.settings.database) as session:
            self.graph_hash = session.execute_write(write)
        return self.graph_hash

    def named(self, name):
        return self.read(
            "MATCH (e:Entity {dataset_id:$dataset,metadata_sha256:$snapshot}) "
            "WHERE $name IN e.name_keys RETURN e.entity_id AS entity_id",
            name=name_key(name),
        )

    def resolve(self, normalized_name):
        ids = {r["entity_id"] for r in self.named(normalized_name)}
        return self.source_ids(ids)

    def source_ids(self, ids):
        if not ids:
            return set()
        rows = self.read(
            "MATCH (e:Entity {dataset_id:$dataset,metadata_sha256:$snapshot}) "
            "WHERE e.entity_id IN $ids UNWIND e.source_ids AS id RETURN DISTINCT id",
            ids=sorted(ids),
        )
        return {r["id"] for r in rows}

    def canonical_ids(self, source_ids):
        if not source_ids:
            return set()
        rows = self.read(
            "MATCH (e:Entity {dataset_id:$dataset,metadata_sha256:$snapshot}) "
            "WHERE any(id IN e.source_ids WHERE id IN $ids) RETURN e.entity_id AS entity_id",
            ids=sorted(source_ids),
        )
        return {r["entity_id"] for r in rows}

    def images_for(self, entity_ids):
        if not entity_ids:
            return set()
        rows = self.read(
            "MATCH (i:Image {dataset_id:$dataset,metadata_sha256:$snapshot})"
            "-[:DEPICTS]->(e:Entity {dataset_id:$dataset,metadata_sha256:$snapshot}) "
            "WHERE any(id IN e.source_ids WHERE id IN $ids) RETURN DISTINCT i.image_id AS image_id",
            ids=sorted(entity_ids),
        )
        return {r["image_id"] for r in rows}

    def entity_links(self, image_ids):
        """image_id -> {entity_id: tên} theo DEPICTS."""
        rows = self.read(
            "MATCH (i:Image {dataset_id:$dataset,metadata_sha256:$snapshot})"
            "-[:DEPICTS]->(e:Entity {dataset_id:$dataset,metadata_sha256:$snapshot}) "
            "WHERE i.image_id IN $ids "
            "RETURN i.image_id AS image_id, e.entity_id AS entity_id, e.name AS name",
            ids=sorted(image_ids),
        )
        links = {}
        for row in rows:
            links.setdefault(row["image_id"], {})[row["entity_id"]] = row["name"]
        return links

    def select(self, query, previous, for_visual=False, allow_unknown=False):
        """Đường đi giới hạn, loại cạnh cố định; không nhận Cypher từ LLM.

        for_visual: phạm vi cho bước nhận diện bằng ảnh; loại/category do planner đặt tên có
        thể khác metadata nên không lọc. allow_unknown: giữ cả entity chưa có vị trí nào, vì
        thiếu thông tin không có nghĩa là nằm ở nơi khác.
        """
        clauses, params = (
            [],
            {
                "name": name_key(query.target_name) if query.target_name else None,
                "kind": None if for_visual else query.target_kind,
                "category": name_key(query.target_category)
                if query.target_category and not for_visual
                else None,
            },
        )
        for i, condition in enumerate(query.conditions):
            if condition.anchor_step_id:
                anchors = sorted(previous[condition.anchor_step_id])
            else:
                anchors = [r["entity_id"] for r in self.named(condition.anchor_name)]
                if len(anchors) > 1:
                    return {"status": "ambiguous_entity", "entity_ids": []}
            if for_visual and not anchors:
                # Graph không biết anchor: không được biến thành tìm toàn kho.
                return {"status": "no_graph_match", "entity_ids": []}
            params[f"anchor{i}"] = anchors
            if condition.relations == ["LOCATED_IN"] and condition.direction == "out":
                # Nằm trong quận thì cũng nằm trong tỉnh; bộ phận nằm nơi công trình nằm.
                clause = (
                    "EXISTS { MATCH (e)-[:LOCATED_IN|PART_OF*0..3]->()"
                    f"-[:LOCATED_IN]->(p{i}:Entity "
                    "{dataset_id:$dataset,metadata_sha256:$snapshot}) "
                    f"WHERE p{i}.entity_id IN $anchor{i} }}"
                )
                if allow_unknown:
                    clause = (
                        f"({clause} OR NOT EXISTS "
                        "{ MATCH (e)-[:LOCATED_IN|PART_OF*0..3]->()-[:LOCATED_IN]->() })"
                    )
                clauses.append(clause)
                continue
            pattern = "(e)"
            for j, kind in enumerate(condition.relations):
                if kind not in RELATIONS:
                    raise ValueError("Quan hệ ngoài schema")
                arrow = f"-[:{kind}]->" if condition.direction == "out" else f"<-[:{kind}]-"
                pattern += (
                    arrow + f"(p{i}_{j}:Entity {{dataset_id:$dataset,metadata_sha256:$snapshot}})"
                )
            clauses.append(
                f"EXISTS {{ MATCH {pattern} "
                f"WHERE p{i}_{len(condition.relations) - 1}.entity_id IN $anchor{i} }}"
            )
        where = " AND ".join(
            [
                "($name IS NULL OR $name IN e.name_keys)",
                "($kind IS NULL OR e.kind=$kind)",
                "($category IS NULL OR any(c IN e.category_keys WHERE c CONTAINS $category))",
            ]
        )
        if query.within_step_id:
            params["within"] = sorted(previous[query.within_step_id])
            where += " AND e.entity_id IN $within"
        if clauses:
            join = " AND " if query.match == "all" else " OR "
            where += " AND (" + join.join(clauses) + ")"
        rows = self.read(
            "MATCH (e:Entity {dataset_id:$dataset,metadata_sha256:$snapshot}) "
            f"WHERE {where} RETURN DISTINCT e.entity_id AS entity_id ORDER BY entity_id",
            **params,
        )
        ids = [r["entity_id"] for r in rows]
        status = (
            "ambiguous_entity"
            if query.target_name and len(ids) > 1
            else "resolved"
            if ids
            else "no_graph_match"
        )
        return {"status": status, "entity_ids": ids if status != "ambiguous_entity" else []}
