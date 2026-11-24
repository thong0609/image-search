# ruff: noqa: E402
import copy

import pytest

np = pytest.importorskip("numpy")

from image_search.baseline.keyword import build_documents, prepare_bm25
from image_search.baseline.utils import file_hash, write_json, write_jsonl
from image_search.baseline.vectors import normalize
from image_search.embedding.siglip2 import plan_steps
from image_search.retrieval.catalog import Catalog
from image_search.retrieval.engine import RetrievalEngine
from image_search.retrieval.runtime import load_query_vectors
from image_search.retrieval.settings import RetrievalSettings


def make_step(sid="s1", target="t1", action="retrieve_images", mention=None, deps=None):
    return {
        "id": sid,
        "target_id": target,
        "action": action,
        "search_text": "cổng đỏ" if action == "resolve_entity" else "bên trong",
        "entity_mention": mention,
        "conditions": [],
        "count": None,
        "depends_on": deps or [],
    }


def make_plan(steps, kind="single", clarify=False):
    return {
        "query_type": "unclear" if clarify else kind,
        "needs_clarification": clarify,
        "clarification_question": "Nơi nào?" if clarify else None,
        "steps": [] if clarify else steps,
    }


@pytest.fixture
def engine():
    rows = []
    for iid, eid, caption in [
        ("ag", "A", "cổng đỏ"),
        ("ai", "A", "bên trong"),
        ("bg", "B", "cổng đỏ"),
        ("bi", "B", "bên trong"),
        ("00-conflict", "A", "ảnh"),
        ("00-conflict", "B", "ảnh"),
        ("other", "C", "bên trong"),
    ]:
        rows.append(
            {
                "record_id": str(len(rows)),
                "image_id": iid,
                "entity_id": eid,
                "entity_name": "Cửa hàng " + eid,
                "mo_ta": caption,
                "download_status": "success",
            }
        )
    ids = ["ag", "ai", "bg", "bi", "00-conflict", "other"]
    vectors = normalize([[1, 0], [0, 1], [0.99, 0.01], [0.01, 0.99], [1, 0], [-1, 0]])
    keyword = prepare_bm25(build_documents(rows, ids), 1.2, 0.75)
    settings = RetrievalSettings(_env_file=None, bridge_candidates=3, bridge_entities=2)
    return RetrievalEngine(ids, vectors, keyword, Catalog(rows, ids), settings)


@pytest.mark.parametrize("method", ["vector", "keyword", "hybrid"])
def test_entity_scope_is_applied_before_top_k(engine, method):
    plan = make_plan([make_step(mention="Cửa hàng B")])
    result = engine.execute(plan, method, {"s1": np.array([0, 1])})
    group = result["groups"][0]
    assert group["entity_scope"] == ["B"]
    assert group["results"][0]["image_id"] == "bi"
    assert all("B" in row["entity_ids"] for row in group["candidates"])


def test_unknown_named_entity_never_falls_back_to_global_search(engine):
    result = engine.execute(make_plan([make_step(mention="Không có trong kho")]), "keyword")
    assert result["groups"][0]["status"] == "entity_not_found"
    assert result["groups"][0]["results"] == []


def test_multi_target_groups_and_counts_are_preserved(engine):
    a, b = make_step(mention="Cửa hàng A"), make_step("s2", "t2", mention="Không có")
    a["count"] = 1
    result = engine.execute(make_plan([a, b], "multi-target"), "keyword")
    assert len(result["groups"]) == 2
    assert len(result["groups"][0]["results"]) == 1
    assert result["groups"][1]["results"] == []


def test_hop_keeps_multiple_entity_hypotheses_and_excludes_bridge_images(engine):
    bridge = make_step(action="resolve_entity")
    end = make_step("s2", deps=["s1"])
    result = engine.execute(
        make_plan([bridge, end], "multi-hop"),
        "vector",
        {"s1": np.array([1, 0]), "s2": np.array([0, 1])},
    )
    assert set(result["trace"][0]["entity_hypotheses"]) == {"A", "B"}
    assert "00-conflict" in result["trace"][0]["rejected_bridge_images"]
    group = result["groups"][0]
    assert group["entity_hypotheses_unverified"]
    assert {r["image_id"] for r in group["candidates"]} >= {"ai", "bi"}
    assert all(r["image_id"] not in ("ag", "bg", "other") for r in group["candidates"])
    assert next(r for r in group["candidates"] if r["image_id"] == "bi")["bridge_image_ids"] == [
        "bg"
    ]


def test_missing_bridge_stops_dependency_without_inventing_entity(engine):
    bridge = make_step(action="resolve_entity", mention="Không có")
    end = make_step("s2", deps=["s1"])
    result = engine.execute(make_plan([bridge, end], "multi-hop"), "keyword")
    assert result["trace"][0]["entity_hypotheses"] == {}
    assert result["groups"][0]["status"] == "dependency_unresolved"
    assert result["groups"][0]["results"] == []


def test_clarification_does_not_search(engine, monkeypatch):
    monkeypatch.setattr(engine, "search", lambda *_: pytest.fail("Không được tìm ảnh"))
    result = engine.execute(make_plan([], clarify=True))
    assert result["status"] == "needs_clarification"


def test_vector_step_ids_and_invalid_vectors_are_rejected(engine):
    plan = make_plan([make_step()])
    with pytest.raises(ValueError, match="step ID"):
        engine.execute(plan, "vector", {})
    with pytest.raises(ValueError, match="vector"):
        engine.execute(plan, "vector", {"s1": np.array([np.nan, 1])})


def test_aliases_are_explicit_and_validate_catalog_ids(engine):
    rows = [r for rs in engine.catalog.records.values() for r in rs]
    catalog = Catalog(rows, engine.image_ids, {"Chi nhánh An": ["A"]})
    assert catalog.resolve("chi nhanh an") == {"A"}
    with pytest.raises(ValueError, match="Alias"):
        Catalog(rows, engine.image_ids, {"An": ["unknown"]})


def test_query_embeddings_cannot_be_reused_for_different_plans(tmp_path):
    predictions = [{"query_id": "q1", "status": "ok", "plan": make_plan([make_step()])}]
    source = tmp_path / "plans.jsonl"
    write_jsonl(source, predictions)
    rows, _ = plan_steps(predictions)
    rows[0].update(truncated=False)
    write_jsonl(tmp_path / "steps.jsonl", rows)
    np.save(tmp_path / "vectors.npy", np.array([[1, 0]], dtype=np.float32))
    index = {
        "config": {"model": "test", "revision": "a" * 40, "preprocessing": "test", "libraries": {}},
        "vector_sha256": "images",
        "processor_sha256": "processor",
        "shape": [2, 2],
    }
    metadata = {
        **index["config"],
        "input_sha256": file_hash(source),
        "image_vectors_sha256": "images",
        "processor_sha256": "processor",
        "vectors_sha256": file_hash(tmp_path / "vectors.npy"),
        "steps_sha256": file_hash(tmp_path / "steps.jsonl"),
    }
    write_json(tmp_path / "embedding.json", metadata)
    mapping = load_query_vectors(tmp_path, source, predictions, index)
    assert np.array_equal(mapping["q1"]["s1"], [1, 0])
    changed = copy.deepcopy(predictions)
    changed[0]["plan"]["steps"][0]["search_text"] = "khác"
    with pytest.raises(ValueError, match="mapping"):
        load_query_vectors(tmp_path, source, changed, index)
    with (tmp_path / "vectors.npy").open("ab") as output:
        output.write(b"changed")
    with pytest.raises(ValueError, match="thay đổi"):
        load_query_vectors(tmp_path, source, predictions, index)


@pytest.mark.parametrize("method", ["vector", "keyword", "hybrid"])
def test_filter_does_not_drop_entity_candidate_outside_global_top_one(engine, method):
    # Global best is ag/00-conflict; the requested eligible set contains only bg.
    found = engine.search("cổng đỏ", np.array([1, 0]), method, 1, allowed={"bg"})
    assert [r["image_id"] for r in found] == ["bg"]


def test_keyword_path_does_not_require_vectors(engine):
    result = engine.execute(make_plan([make_step(mention="Cửa hàng A")]), "keyword")
    assert result["groups"][0]["results"][0]["image_id"] == "ai"


def test_uncertain_caption_cannot_be_used_as_confirmed_bridge(engine):
    engine.catalog.uncertain.update(engine.image_ids)
    bridge = make_step(action="resolve_entity")
    end = make_step("s2", deps=["s1"])
    result = engine.execute(make_plan([bridge, end], "multi-hop"), "keyword")
    assert not result["trace"][0]["entity_hypotheses"]
    assert result["groups"][0]["status"] == "dependency_unresolved"


def test_unspecified_count_is_a_display_limit_not_a_requirement(engine):
    result = engine.execute(make_plan([make_step(mention="Cửa hàng A")]), "keyword")
    assert result["groups"][0]["requested_count"] is None
    assert result["groups"][0]["selection_limit"] == 10
    assert result["groups"][0]["status"] == "candidates"


def test_explicit_count_reports_insufficient_candidates(engine):
    step = make_step(mention="Cửa hàng A")
    step["count"] = 100
    result = engine.execute(make_plan([step]), "keyword")
    assert result["groups"][0]["status"] == "insufficient_candidates"
    assert len(result["groups"][0]["results"]) < 100


def test_ambiguous_entities_do_not_pool_counts_or_publish_mixed_results(engine):
    bridge = make_step(action="resolve_entity")
    bridge["conditions"] = ["cổng đỏ"]
    end = make_step("s2", deps=["s1"])
    end.update(count=2, conditions=["bên trong"])
    result = engine.execute(
        make_plan([bridge, end], "multi-hop"),
        "vector",
        {"s1": np.array([1, 0]), "s2": np.array([0, 1])},
    )
    group = result["groups"][0]
    assert group["status"] == "ambiguous_entity"
    assert group["count_status"] == "unresolved_entity"
    assert group["results"] == []
    assert {h["entity_id"] for h in group["hypotheses"]} == {"A", "B"}
    assert all(h["count_status"] == "insufficient_candidates" for h in group["hypotheses"])
    assert sum(len(h["results"]) for h in group["hypotheses"]) == 2


def test_evidence_keeps_record_provenance_without_claiming_visual_verification(engine):
    from image_search.retrieval.evidence import inspect_evidence

    evidence = inspect_evidence(engine.catalog, "ag", "A", ["cổng đỏ"])
    assert evidence["identity_status"] == "supported_by_metadata"
    assert evidence["conditions_status"] == "supported_by_metadata"
    assert evidence["condition_checks"][0]["sources"][0]["record_id"] == "0"
    assert evidence["visual_verification"] == "not_performed"
    assert evidence["identity_sources"][0]["entity_id"] == "A"


def test_absence_of_caption_words_never_proves_negation(engine):
    from image_search.retrieval.evidence import inspect_evidence

    evidence = inspect_evidence(engine.catalog, "ag", "A", ["không có người"])
    assert evidence["conditions_status"] == "unverified"
    assert evidence["condition_checks"][0]["sources"] == []


def test_unknown_target_condition_is_not_reported_as_verified_count(engine):
    step = make_step(mention="Cửa hàng A")
    step.update(count=1, conditions=["bàn thờ"])
    group = engine.execute(make_plan([step]), "keyword")["groups"][0]
    assert group["results"]
    assert group["verification_status"] == "unverified"
    assert group["count_status"] == "unverified"
    assert group["hypotheses"][0]["metadata_supported_count"] == 0


def test_conflicting_identity_is_quarantined_in_scoped_target_search(engine):
    step = make_step(mention="Cửa hàng A")
    step["search_text"] = "ảnh"
    group = engine.execute(make_plan([step]), "keyword")["groups"][0]
    assert group["results"] == []
    rejected = group["hypotheses"][0]["rejected_candidates"]
    assert rejected[0]["image_id"] == "00-conflict"
    assert rejected[0]["evidence"]["identity_status"] == "conflicting"


def test_partial_multi_target_does_not_claim_all_targets_resolved(engine):
    a = make_step(mention="Cửa hàng A")
    b = make_step("s2", "t2", mention="Không có")
    result = engine.execute(make_plan([a, b], "multi-target"), "keyword")
    assert result["status"] == "partial_results"
    assert result["groups"][0]["results"]
    assert not result["groups"][1]["results"]


def test_join_paths_requires_same_entity_and_consistent_shared_ancestor():
    from image_search.retrieval.executor import join_paths

    a = {"A": [[{"step_id": "root", "image_id": "ag"}]]}
    b = {"B": [[{"step_id": "other", "image_id": "bg"}]]}
    assert join_paths([a, b], 2) == ({}, False)
    conflict = {"A": [[{"step_id": "root", "image_id": "another_image"}]]}
    assert join_paths([a, conflict], 2) == ({}, False)
    consistent = {
        "A": [[{"step_id": "root", "image_id": "ag"}, {"step_id": "second", "image_id": "ai"}]]
    }
    joined, truncated = join_paths([a, consistent], 2)
    assert not truncated
    assert len(joined["A"][0]) == 2


def test_join_paths_has_bounded_work_and_reports_truncation():
    from image_search.retrieval.executor import join_paths

    a = {"A": [[{"step_id": "root", "image_id": f"a{i}"}] for i in range(5)]}
    b = {"A": [[{"step_id": "root", "image_id": f"b{i}"}] for i in range(5)]}
    joined, truncated = join_paths([a, b], 2, combination_limit=3)
    assert truncated and joined == {}


def test_unique_hop_preserves_both_bridge_and_target_evidence(engine):
    bridge = make_step(action="resolve_entity", mention="Cửa hàng A")
    bridge["conditions"] = ["cổng đỏ"]
    end = make_step("s2", deps=["s1"])
    end.update(count=1, conditions=["bên trong"])
    result = engine.execute(make_plan([bridge, end], "multi-hop"), "keyword")
    group = result["groups"][0]
    assert group["count_status"] == "supported_by_metadata"
    assert group["verification_status"] == "supported_by_metadata"
    assert group["results"][0]["image_id"] == "ai"
    path = group["results"][0]["evidence_paths"][0]
    assert path["bridge_steps"][0]["image_id"] == "ag"
    assert path["target_evidence"]["image_id"] == "ai"
    assert path["target_evidence"]["visual_verification"] == "not_performed"


def test_condition_evidence_keeps_vietnamese_diacritics(engine):
    from image_search.retrieval.evidence import inspect_evidence

    engine.catalog.records["ag"][0]["mo_ta"] = "Cổng có cây đa."
    evidence = inspect_evidence(engine.catalog, "ag", "A", ["đá"])
    assert evidence["conditions_status"] == "unverified"
