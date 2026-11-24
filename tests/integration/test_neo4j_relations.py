"""Neo4j thật, chỉ thay/xóa namespace test riêng."""

import os
from uuid import uuid4

import pytest

from image_search.adapters.neo4j.client import create_graph_driver
from image_search.adapters.neo4j.store import GraphStore
from image_search.modules.graph.query import GraphQuery
from image_search.modules.graph.settings import GraphSettings

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(os.getenv("RUN_NEO4J_INTEGRATION") != "1", reason="Needs local Neo4j"),
]


@pytest.fixture
def graph(graph_case):
    settings = GraphSettings(dataset_id="test-" + uuid4().hex)
    driver = create_graph_driver(settings)
    store = GraphStore(driver, settings, "fixture-snapshot")
    artifact, index, payloads = graph_case
    try:
        store.import_graph(artifact)
        store.validate(index, payloads)
        yield store, artifact, index, payloads
    finally:
        driver.execute_query(
            "MATCH (n {dataset_id:$dataset}) DETACH DELETE n",
            parameters_={"dataset": settings.dataset_id},
            database_=settings.database,
        )
        driver.close()


def query(conditions, **kwargs):
    return GraphQuery(
        target_name=None,
        target_kind=None,
        target_category=None,
        match="all",
        conditions=conditions,
        **kwargs,
    )


def condition(relations, name=None, direction="out", step=None):
    return dict(relations=relations, direction=direction, anchor_name=name, anchor_step_id=step)


def test_idempotent_import_retains_shared_images_and_alias_mapping(graph):
    store, artifact, index, payloads = graph
    before = store.validate(index, payloads)
    store.import_graph(artifact)
    assert store.validate(index, payloads) == before
    assert before["nodes"] == {"Image": 2, "Entity": 6}
    assert store.resolve("cua hang a") == {"A", "A-alias"}
    assert store.images_for({"A", "A-alias"}) == {"one", "two"}
    assert store.images_for({"B"}) == {"one"}
    assert store.images_for({"P"}) == set()
    assert not store.resolve("x' MATCH (n) DETACH DELETE n //")


def test_graph_intersection_union_direction_and_two_hops(graph):
    store, *_ = graph
    q = query([condition(["BRANCH_OF"], "Thương hiệu X"), condition(["LOCATED_IN"], "Trung tâm M")])
    assert store.select(q, {})["entity_ids"] == ["a"]
    q.match = "any"
    assert store.select(q, {})["entity_ids"] == ["a", "b"]
    two = query([condition(["LOCATED_IN", "LOCATED_IN"], "Thành phố H")])
    assert store.select(two, {})["entity_ids"] == ["a"]
    inverse = query([condition(["PART_OF"], "Tầng một Trung tâm M", direction="in")])
    assert store.select(inverse, {})["entity_ids"] == ["mall"]
    dependent = query([condition(["BRANCH_OF"], step="s1")], within_step_id="s2")
    assert store.select(dependent, {"s1": {"brand"}, "s2": {"b"}})["entity_ids"] == ["b"]
    missing = query([condition(["LOCATED_IN"], "Không có")])
    assert store.select(missing, {})["status"] == "no_graph_match"


def test_bad_import_rolls_back_and_hash_detects_tampering(graph, monkeypatch):
    store, artifact, index, payloads = graph
    before = store.export()
    original = store._export
    with monkeypatch.context() as patch:
        patch.setattr(
            store, "_export", lambda _: (_ for _ in ()).throw(ValueError("forced failure"))
        )
        with pytest.raises(ValueError, match="forced"):
            store.import_graph(artifact)
    assert store._export == original
    assert store.export() == before
    store.driver.execute_query(
        'MATCH (e:Entity {dataset_id:$dataset}) SET e.name="tampered"',
        parameters_={"dataset": store.dataset},
        database_=store.settings.database,
    )
    with pytest.raises(ValueError, match="hash"):
        store.validate(index, payloads)


def test_migration_deletes_source_nodes_only_in_selected_dataset(graph):
    store, artifact, index, payloads = graph
    store.driver.execute_query(
        'CREATE (:SourceRecord {dataset_id:$dataset, record_id:"old"})',
        parameters_={"dataset": store.dataset},
        database_=store.settings.database,
    )
    store.import_graph(artifact)
    assert store.validate(index, payloads)["nodes"] == {"Image": 2, "Entity": 6}
    rows = store.read("MATCH (n {dataset_id:$dataset}) RETURN DISTINCT labels(n) AS labels")
    assert {tuple(r["labels"]) for r in rows} == {("Image",), ("Entity",)}


def test_wrong_qdrant_mapping_is_rejected_before_replacing_graph(graph):
    store, artifact, index, payloads = graph
    before = store.export()
    with pytest.raises(ValueError, match="Ánh xạ"):
        store.import_graph(
            artifact, index, {"one": {"records": [{"entity_id": "B"}]}, "two": payloads["two"]}
        )
    assert store.export() == before
