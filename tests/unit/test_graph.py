from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from pydantic import ValidationError

from image_search.adapters.neo4j.store import GraphStore
from image_search.graph.build import build_graph, validate_graph
from image_search.graph.extraction import Extraction, digest, run_extraction
from image_search.graph.query import GraphQuery, strict_schema
from image_search.graph.settings import GraphSettings
from image_search.planner.schemas import QueryPlan


def test_graph_values_are_parameters_and_failures_are_not_hidden():
    driver = Mock()
    driver.execute_query.return_value = SimpleNamespace(records=[])
    graph = GraphStore(driver, GraphSettings(_env_file=None, password="test"), "pinned")
    value = "x' MATCH (n) DETACH DELETE n //"
    assert graph.resolve(value) == set()
    query = driver.execute_query.call_args.args[0]
    params = driver.execute_query.call_args.kwargs["parameters_"]
    assert value not in query.text
    assert params["snapshot"] == "pinned"
    driver.execute_query.side_effect = ConnectionError("unavailable")
    with pytest.raises(ConnectionError):
        graph.resolve("Cửa hàng A")


def test_unsupported_edges_cycles_and_wrong_ids_are_rejected(graph_case):
    graph, _, _ = graph_case
    for edge in (
        ["a", "NEAR", "b"],
        ["a", "PART_OF", "missing"],
        ["city", "LOCATED_IN", "a"],
        ["a", "PART_OF", "a"],
    ):
        bad = deepcopy(graph)
        bad["relations"].append(edge)
        with pytest.raises(ValueError):
            validate_graph(bad)


def test_import_rejects_bad_artifact_before_touching_db(graph_case):
    graph, _, _ = graph_case
    driver = Mock()
    store = GraphStore(driver, GraphSettings(_env_file=None, password="test"), "other")
    with pytest.raises(ValueError, match="snapshot"):
        store.import_graph(graph)
    driver.execute_query.assert_not_called()


def test_extraction_requires_self_and_valid_relation_endpoints():
    entity = dict(key="self", name="A", kind="place", category="cửa hàng", aliases=[], context="")
    assert Extraction(entities=[entity], relations=[], unresolved=[])
    with pytest.raises(ValidationError):
        Extraction(
            entities=[entity],
            relations=[dict(subject="self", predicate="PART_OF", object="bad")],
            unresolved=[],
        )


def test_query_schema_rejects_unknown_relation_and_ambiguous_anchor():
    query = dict(
        target_name=None,
        target_kind=None,
        target_category=None,
        match="all",
        conditions=[
            dict(relations=["LOCATED_IN"], direction="out", anchor_name="A", anchor_step_id="s1")
        ],
    )
    with pytest.raises(ValidationError):
        GraphQuery.model_validate(query)
    query["conditions"][0].update(anchor_step_id=None, relations=["NEAR"])
    with pytest.raises(ValidationError):
        GraphQuery.model_validate(query)
    schema = strict_schema(QueryPlan)
    assert "graph" in schema["$defs"]["Step"]["required"]
    assert "within_step_id" in schema["$defs"]["GraphQuery"]["required"]


def test_build_preserves_shared_images_and_deduplicates_relations():
    records = [
        dict(entity_id=eid, entity_name=name, leaf_label="Cửa hàng")
        for eid, name in [("A", "Cửa hàng A"), ("B", "Cửa hàng B")]
    ]
    groups = [dict(entity_id=eid, part=0, records=[]) for eid in ("A", "B")]
    responses = []
    for group, row in zip(groups, records, strict=True):
        extraction = {
            "entities": [
                dict(
                    key="self",
                    name=row["entity_name"],
                    kind="place",
                    category="cửa hàng",
                    aliases=[],
                    context="",
                ),
                dict(
                    key="brand",
                    name="X",
                    kind="brand",
                    category="thương hiệu",
                    aliases=[],
                    context="",
                ),
            ],
            "relations": [dict(subject="self", predicate="BRANCH_OF", object="brand")] * 2,
            "unresolved": [],
        }
        responses.append({**group, "input_sha256": digest(group), "extraction": extraction})
    index = {"image_ids": ["one"], "search_metadata_sha256": "snapshot"}
    payloads = {"one": {"records": records}}
    graph = build_graph(records, groups, responses, index, payloads)
    assert len(graph["entities"]) == 3
    assert len(graph["image_links"]) == 2
    assert len(graph["relations"]) == 2
    assert graph == build_graph(records, groups, list(reversed(responses)), index, payloads)
    with pytest.raises(ValueError, match="Thiếu/trùng"):
        build_graph(records, groups, responses[:1], index, payloads)


def test_resume_reuses_completed_entity_without_api(tmp_path, monkeypatch):
    from image_search.files import write_json
    from image_search.graph import extraction

    groups = [dict(entity_id="A", part=0, records=[]), dict(entity_id="B", part=0, records=[])]
    monkeypatch.setattr(extraction, "inputs", lambda *args: ([], groups, "csv"))
    calls = []

    def extract(group, settings):
        calls.append(group["entity_id"])
        return {
            **group,
            "input_sha256": digest(group),
            "input_tokens": 10,
            "output_tokens": 10,
            "estimated_cost_usd": None,
            "extraction": {
                "entities": [
                    dict(
                        key="self",
                        name=group["entity_id"],
                        kind="place",
                        category="",
                        aliases=[],
                        context="",
                    )
                ],
                "relations": [],
                "unresolved": [],
            },
        }

    monkeypatch.setattr(extraction, "extract_one", extract)
    settings = GraphSettings(_env_file=None, password="test", workers=1)
    index = {"search_metadata_sha256": "snapshot"}
    assert not run_extraction(index, {}, settings, tmp_path, limit=1)[-1]["complete"]
    assert run_extraction(index, {}, settings, tmp_path)[-1]["complete"]
    assert calls == ["A", "B"]
    cached = tmp_path / "responses/A-0.json"
    write_json(cached, {"input_sha256": "tampered"})
    with pytest.raises(ValueError, match="Cache"):
        run_extraction(index, {}, settings, tmp_path)


def test_api_failure_stops_scheduling_more_entities(tmp_path, monkeypatch):
    from image_search.graph import extraction

    groups = [dict(entity_id=str(i), part=0, records=[]) for i in range(10)]
    monkeypatch.setattr(extraction, "inputs", lambda *args: ([], groups, "csv"))
    calls = []

    def exhausted(group, settings):
        calls.append(group["entity_id"])
        raise ConnectionError("quota")

    monkeypatch.setattr(extraction, "extract_one", exhausted)
    with pytest.raises(ConnectionError):
        run_extraction(
            {"search_metadata_sha256": "snapshot"},
            {},
            GraphSettings(_env_file=None, password="test", workers=1),
            tmp_path,
        )
    assert calls == ["0"]
    assert not (tmp_path / "graph.json").exists()


def test_grouping_keeps_record_pairs_deduplicates_and_includes_no_image_metadata(
    tmp_path, monkeypatch
):
    import csv

    from image_search.baseline.records import REQUIRED_COLUMNS
    from image_search.files import file_hash, write_json
    from image_search.graph import extraction

    rows = []
    for eid, caption, title in [
        ("A", "cảnh 1", "trang 1"),
        ("A", "cảnh 1", "trang 1"),
        ("A", "cảnh 2", "trang 2"),
        ("B", "chưa có ảnh", "trang 3"),
    ]:
        row = dict.fromkeys(REQUIRED_COLUMNS, "")
        row.update(
            entity_id=eid,
            entity_name=eid,
            leaf_label="Cửa hàng",
            mo_ta=caption,
            page_title=title,
            image_url="https://example.com/image",
            approve="yes",
        )
        rows.append(row)
    csv_path = tmp_path / "source.csv"
    with csv_path.open("w") as stream:
        writer = csv.DictWriter(stream, fieldnames=REQUIRED_COLUMNS)
        writer.writeheader()
        writer.writerows(rows)
    manifest = tmp_path / "manifest.json"
    write_json(
        manifest,
        {
            "files": {
                "csv": {"path": str(csv_path), "sha256": file_hash(csv_path)},
                "records": {"sha256": "source"},
            }
        },
    )
    monkeypatch.setattr(extraction, "EmbeddingSettings", lambda: SimpleNamespace(manifest=manifest))
    records, groups, _ = extraction.inputs({"records_sha256": "source"}, {}, 24000)
    assert len(records) == 4
    assert len(groups) == 2
    assert groups[0]["records"] == [
        {"caption": "cảnh 1", "page_title": "trang 1"},
        {"caption": "cảnh 2", "page_title": "trang 2"},
    ]
    assert groups[1]["entity_id"] == "B"
    with pytest.raises(ValueError, match="không tự cắt"):
        extraction.inputs({"records_sha256": "source"}, {}, 10)


def test_build_cli_uses_reviewed_input_without_api_or_neo4j(tmp_path, monkeypatch):
    from image_search.files import read_json, write_jsonl
    from image_search.graph import cli

    group = {"entity_id": "A", "part": 0, "records": []}
    records = [{"entity_id": "A", "entity_name": "A", "leaf_label": "Cửa hàng"}]
    index = {"image_ids": ["one"], "search_metadata_sha256": "snapshot"}
    store = SimpleNamespace(payloads={"one": {"records": records}}, client=Mock())
    reviewed = tmp_path / "reviewed.jsonl"
    output = tmp_path / "graph.json"
    write_jsonl(
        reviewed,
        [
            {
                **group,
                "input_sha256": digest(group),
                "extraction": {
                    "entities": [
                        dict(
                            key="self",
                            name="A",
                            kind="place",
                            category="cửa hàng",
                            aliases=[],
                            context="",
                        )
                    ],
                    "relations": [],
                    "unresolved": [],
                },
            }
        ],
    )
    monkeypatch.setattr(cli, "load_index", lambda: (None, index, store))
    monkeypatch.setattr(cli, "inputs", lambda *args: (records, [group], "csv"))
    monkeypatch.setattr(cli, "run_extraction", lambda *args: pytest.fail("Không gọi API"))
    monkeypatch.setattr(cli, "create_graph_driver", lambda *args: pytest.fail("Không ghi Neo4j"))
    monkeypatch.setattr("sys.argv", ["graph", "build", str(reviewed), "--output", str(output)])
    cli.main()
    assert read_json(output)["image_ids"] == ["one"]
    assert len(read_json(output)["image_links"]) == 1
    store.client.close.assert_called_once()
    with pytest.raises(SystemExit):
        cli.main()
