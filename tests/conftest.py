"""Graph fixture nhỏ; không chứa dữ liệu riêng của dataset thật."""

import pytest

from image_search.adapters.qdrant.metadata import name_key
from image_search.modules.graph.extraction import digest


@pytest.fixture
def graph_case():
    def node(eid, name, kind, category, source_ids):
        return {
            "entity_id": eid,
            "name": name,
            "kind": kind,
            "context": "",
            "aliases": [name],
            "name_keys": [name_key(name)],
            "categories": [category],
            "category_keys": [name_key(category)],
            "source_ids": source_ids,
        }

    entities = [
        node("a", "Cửa hàng A", "place", "cửa hàng", ["A", "A-alias"]),
        node("b", "Cửa hàng B", "place", "cửa hàng", ["B"]),
        node("brand", "Thương hiệu X", "brand", "thương hiệu", []),
        node("city", "Thành phố H", "area", "thành phố", []),
        node("mall", "Trung tâm M", "place", "trung tâm thương mại", []),
        node("part", "Tầng một Trung tâm M", "part", "tầng", ["P"]),
    ]
    graph = {
        "metadata_sha256": "fixture-snapshot",
        "image_ids": ["one", "two"],
        "entities": entities,
        "image_links": [["one", "a"], ["one", "b"], ["two", "a"]],
        "relations": [
            ["a", "BRANCH_OF", "brand"],
            ["a", "LOCATED_IN", "mall"],
            ["b", "BRANCH_OF", "brand"],
            ["mall", "LOCATED_IN", "city"],
            ["part", "PART_OF", "mall"],
        ],
    }
    graph["graph_sha256"] = digest(graph)
    payloads = {
        "one": {"records": [{"entity_id": "A"}, {"entity_id": "B"}]},
        "two": {"records": [{"entity_id": "A-alias"}]},
    }
    return (
        graph,
        {"image_ids": ["one", "two"], "search_metadata_sha256": "fixture-snapshot"},
        payloads,
    )
