"""Hợp nhất kết quả trích xuất, giữ ánh xạ ID nguồn và ảnh Qdrant."""

from collections import defaultdict
from uuid import NAMESPACE_URL, uuid5

from image_search.adapters.qdrant.metadata import name_key
from image_search.modules.graph.extraction import Extraction, digest


def entity_key(entity):
    return str(
        uuid5(
            NAMESPACE_URL,
            "graph-entity:"
            + "|".join((entity.kind, name_key(entity.name), name_key(entity.context))),
        )
    )


def build_graph(records, groups, responses, index, payloads):
    expected = {(g["entity_id"], g["part"]): digest(g) for g in groups}
    actual = {(r["entity_id"], r["part"]): r["input_sha256"] for r in responses}
    if actual != expected or len(responses) != len(expected):
        raise ValueError("Thiếu/trùng extraction hoặc input khác snapshot")
    source = defaultdict(list)
    for r in records:
        source[r["entity_id"]].append(r)
    extracted = [
        (r["entity_id"], Extraction.model_validate(r["extraction"]))
        for r in sorted(responses, key=lambda r: (r["entity_id"], r["part"]))
    ]
    # Khớp exact alias + kind; ngữ cảnh xung đột không bị gộp.
    mains = {}
    aliases = defaultdict(set)
    for _, output in extracted:
        main = next(e for e in output.entities if e.key == "self")
        key = entity_key(main)
        mains[key] = main
        for name in [main.name, *main.aliases]:
            aliases[(main.kind, name_key(name))].add(key)
    nodes, links, edges, mapping, unresolved = {}, set(), set(), defaultdict(set), []
    for eid, output in extracted:
        local = {}
        for entity in output.entities:
            key = entity_key(entity)
            candidates = aliases.get((entity.kind, name_key(entity.name)), set())
            compatible = [
                k
                for k in candidates
                if not entity.context
                or not mains[k].context
                or name_key(entity.context) == name_key(mains[k].context)
            ]
            if entity.key != "self" and len(compatible) == 1:
                key = compatible[0]
            base = mains.get(key, entity)
            node = nodes.setdefault(
                key,
                {
                    "entity_id": key,
                    "name": base.name,
                    "kind": base.kind,
                    "context": base.context,
                    "aliases": set(),
                    "categories": set(),
                    "source_ids": set(),
                },
            )
            node["aliases"].update([entity.name, *entity.aliases])
            if entity.category:
                node["categories"].add(entity.category)
            if entity.key == "self":
                mapping[eid].add(key)
                node["source_ids"].add(eid)
                node["aliases"].update(r["entity_name"] for r in source[eid])
                node["categories"].update(r["leaf_label"] for r in source[eid])
            local[entity.key] = key
        for r in output.relations:
            start, end = local[r.subject], local[r.object]
            if start == end:
                raise ValueError("Chuẩn hóa tạo self-loop; cần sửa extraction")
            edges.add((start, r.predicate, end))
        unresolved.extend({"entity_id": eid, "reason": reason} for reason in output.unresolved)
    if any(len(ids) != 1 for ids in mapping.values()):
        raise ValueError("Các chunk cùng entity không thống nhất danh tính")
    for iid, payload in payloads.items():
        for r in payload["records"]:
            if r["entity_id"] not in mapping:
                raise ValueError("Thiếu entity của ảnh Qdrant")
            links.add((iid, next(iter(mapping[r["entity_id"]]))))
    entities = []
    for node in nodes.values():
        for field in ("aliases", "categories", "source_ids"):
            node[field] = sorted(node[field])
        node["name_keys"] = sorted({name_key(n) for n in [node["name"], *node["aliases"]]})
        node["category_keys"] = sorted({name_key(n) for n in node["categories"]})
        entities.append(node)
    graph = {
        "metadata_sha256": index["search_metadata_sha256"],
        "image_ids": sorted(index["image_ids"]),
        "entities": sorted(entities, key=lambda e: e["entity_id"]),
        "image_links": [list(x) for x in sorted(links)],
        "relations": [list(x) for x in sorted(edges)],
    }
    validate_graph(graph)
    return {**graph, "graph_sha256": digest(graph), "unresolved": unresolved}


def validate_graph(graph):
    ids = {n["entity_id"] for n in graph["entities"]}
    if not ids or len(ids) != len(graph["entities"]):
        raise ValueError("Entity rỗng/trùng ID")
    for iid, eid in graph["image_links"]:
        if iid not in graph["image_ids"] or eid not in ids:
            raise ValueError("Liên kết ảnh sai ID")
    for start, relation, end in graph["relations"]:
        if start not in ids or end not in ids or start == end:
            raise ValueError("Quan hệ sai ID hoặc self-loop")
        if relation not in ("LOCATED_IN", "PART_OF", "BRANCH_OF"):
            raise ValueError("Quan hệ ngoài schema")
    for kind in ("LOCATED_IN", "PART_OF"):
        neighbors = defaultdict(set)
        for start, relation, end in graph["relations"]:
            if relation == kind:
                neighbors[start].add(end)
        visited, active = set(), set()

        def visit(node, active=active, visited=visited, neighbors=neighbors, kind=kind):
            if node in active:
                raise ValueError(f"Chu trình {kind}")
            if node in visited:
                return
            active.add(node)
            for child in neighbors[node]:
                visit(child)
            active.remove(node)
            visited.add(node)

        for node in ids:
            visit(node)
