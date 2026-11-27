# ruff: noqa: E402

import pytest

np = pytest.importorskip("numpy")

from image_search.embedding.encoder import normalize
from image_search.retrieval.catalog import Catalog
from image_search.retrieval.engine import RetrievalEngine
from image_search.retrieval.keyword import build_documents, prepare_bm25
from image_search.retrieval.settings import RetrievalSettings

pytestmark = [
    pytest.mark.filterwarnings("ignore:Payload indexes:UserWarning"),
    pytest.mark.filterwarnings("ignore:Local mode performs exact:UserWarning"),
]


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


class FakeGraph:
    """Graph nhỏ: entity chuẩn a/b/c ứng với nguồn A/B/C của fixture."""

    names = {"a": "Cửa hàng A", "b": "Cửa hàng B", "c": "Cửa hàng C"}

    def __init__(self, catalog, scope=None, confirmed=()):
        self.catalog, self.scope, self.confirmed = catalog, scope, list(confirmed)
        self.selects = []
        self.known = {"Thương hiệu X"}

    def named(self, name):
        return [{"entity_id": name}] if name in self.known else []

    def select(self, query, previous, for_visual=False, allow_unknown=False):
        if query.target_name and not query.conditions:
            ids = [e for e, name in self.names.items() if name == query.target_name]
        else:
            self.selects.append((for_visual, allow_unknown))
            ids = self.scope if allow_unknown else self.confirmed
        return {"status": "resolved" if ids else "no_graph_match", "entity_ids": ids}

    def source_ids(self, ids):
        return {i.upper() for i in ids}

    def canonical_ids(self, source_ids):
        return {i.lower() for i in source_ids}

    def images_for(self, source_ids):
        return {i for i, e in self.catalog.image_entities.items() if e & set(source_ids)}

    def entity_links(self, image_ids):
        return {
            i: {e.lower(): self.names[e.lower()] for e in self.catalog.image_entities[i]}
            for i in image_ids
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
    settings = RetrievalSettings(_env_file=None)
    from qdrant_client import QdrantClient

    from image_search.adapters.qdrant.vectors import QdrantVectors

    catalog = Catalog(rows, ids)
    store = QdrantVectors(QdrantClient(":memory:"), "test-images", "test-index", 2)
    store.upload(ids, vectors, catalog, "test", "test")
    from image_search.adapters.qdrant.metadata import sync_metadata

    sync_metadata(store, {"image_ids": ids}, catalog, [{"image_id": iid} for iid in ids], "source")
    return RetrievalEngine(ids, store, keyword, catalog, settings, FakeGraph(catalog))


@pytest.mark.parametrize("method", ["vector", "keyword", "hybrid"])
def test_entity_scope_is_applied_before_top_k(engine, method):
    plan = make_plan([make_step(mention="Cửa hàng B")])
    result = engine.execute(plan, method, {"s1": np.array([0, 1])})
    group = result["groups"][0]
    assert group["entity_scope"] == ["B"]
    assert group["results"][0]["image_id"] == "bi"
    entities = engine.catalog.image_entities
    assert all("B" in entities[row["image_id"]] for row in group["candidates"])


def test_unknown_named_entity_never_falls_back_to_global_search(engine):
    result = engine.execute(make_plan([make_step(mention="Không có trong kho")]), "keyword")
    assert result["groups"][0]["status"] == "no_graph_match"
    assert result["groups"][0]["results"] == []


def test_multi_target_groups_and_counts_are_preserved(engine):
    a, b = make_step(mention="Cửa hàng A"), make_step("s2", "t2", mention="Không có")
    a["count"] = 1
    result = engine.execute(make_plan([a, b], "multi-target"), "keyword")
    assert len(result["groups"]) == 2
    assert len(result["groups"][0]["results"]) == 1
    assert result["groups"][1]["results"] == []


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
    engine.graph_store, engine.catalog = FakeGraph(catalog), catalog
    group = engine.execute(make_plan([make_step(mention="chi nhanh an")]), "keyword")["groups"][0]
    assert group["entity_scope"] == ["A"]
    with pytest.raises(ValueError, match="Alias"):
        Catalog(rows, engine.image_ids, {"An": ["unknown"]})


@pytest.mark.parametrize("method", ["vector", "keyword", "hybrid"])
def test_filter_does_not_drop_entity_candidate_outside_global_top_one(engine, method):
    # Ảnh tốt nhất toàn kho thuộc A; phạm vi yêu cầu chỉ có C.
    found = engine.search("bên trong", np.array([0, 1]), method, 1, entity_ids={"C"})
    assert [r["image_id"] for r in found] == ["other"]


def test_keyword_path_does_not_require_vectors(engine):
    result = engine.execute(make_plan([make_step(mention="Cửa hàng A")]), "keyword")
    assert result["groups"][0]["results"][0]["image_id"] == "ai"


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


def test_partial_multi_target_does_not_claim_all_targets_resolved(engine):
    a = make_step(mention="Cửa hàng A")
    b = make_step("s2", "t2", mention="Không có")
    result = engine.execute(make_plan([a, b], "multi-target"), "keyword")
    assert result["status"] == "partial_results"
    assert result["groups"][0]["results"]
    assert not result["groups"][1]["results"]


@pytest.mark.parametrize("method", ["vector", "keyword", "hybrid"])
def test_relation_outside_graph_and_images_never_searches(engine, monkeypatch, method):
    bridge = make_step(action="resolve_entity")
    bridge["conditions"] = ["cùng thành phố với chợ"]
    target = make_step("s2", deps=["s1"])
    monkeypatch.setattr(engine, "search", lambda *a, **k: pytest.fail("Không chạy bridge cũ"))
    result = engine.execute(make_plan([bridge, target], "multi-hop"), method)
    assert result["status"] == "unsupported_graph_relation"
    assert result["groups"][0]["status"] == "unsupported_graph_relation"
    assert result["groups"][0]["results"] == []
    assert result["trace"][0]["entity_ids"] == []


def test_multi_target_keeps_direct_target_when_other_target_needs_relation(engine):
    direct = make_step(mention="Cửa hàng A")
    bridge = make_step("s2", "t2", action="resolve_entity")
    bridge["conditions"] = ["cách chợ 2 km"]
    target = make_step("s3", "t2", deps=["s2"])
    result = engine.execute(make_plan([direct, bridge, target], "multi-target"), "keyword")
    assert result["status"] == "partial_results"
    assert result["groups"][0]["results"]
    assert result["groups"][1]["status"] == "unsupported_graph_relation"


def test_graph_membership_is_applied_before_qdrant_top_k(engine):
    from unittest.mock import Mock

    graph = Mock()
    graph.images_for.return_value = {"ai"}
    engine.graph_store = graph
    result = engine.search("", np.array([1, 0]), "vector", 1, entity_ids={"A"})
    assert [r["image_id"] for r in result] == ["ai"]
    graph.images_for.assert_called_once_with({"A"})


def test_graph_failure_does_not_run_vector_fallback(engine, monkeypatch):
    from unittest.mock import Mock

    graph = Mock()
    graph.images_for.side_effect = ConnectionError("Neo4j unavailable")
    engine.graph_store = graph
    monkeypatch.setattr(
        engine.vector_store, "search", lambda *a, **k: pytest.fail("Không fallback khi graph lỗi")
    )
    with pytest.raises(ConnectionError, match="Neo4j unavailable"):
        engine.search("", np.array([1, 0]), "vector", 1, entity_ids={"A"})


def relation_query(anchor="Thương hiệu X", step=None):
    return {
        "target_name": None,
        "target_kind": "place",
        "target_category": "cửa hàng",
        "match": "all",
        "conditions": [
            {
                "relations": ["BRANCH_OF"],
                "direction": "out",
                "anchor_name": anchor,
                "anchor_step_id": step,
            }
        ],
    }


@pytest.mark.parametrize("method", ["vector", "keyword", "hybrid"])
def test_graph_selected_entities_share_one_ranked_pool_and_filter_before_topk(engine, method):
    from unittest.mock import Mock

    graph = Mock()
    graph.select.return_value = {"status": "resolved", "entity_ids": ["canonical-A", "canonical-B"]}
    graph.source_ids.return_value = {"A", "B"}
    graph.images_for.return_value = {"ag", "ai", "bg", "bi", "00-conflict"}
    engine.graph_store = graph
    bridge = make_step(action="resolve_entity")
    bridge["graph"] = relation_query()
    target = make_step("s2", deps=["s1"])
    target["count"] = 2
    result = engine.execute(
        make_plan([bridge, target], "multi-hop"), method, {"s2": np.array([0, 1])}
    )
    group = result["groups"][0]
    assert group["status"] == "candidates"
    assert {r["image_id"] for r in group["results"]} == {"ai", "bi"}
    assert group["requested_count"] == 2
    graph.images_for.assert_called_once_with({"A", "B"})
    assert "other" not in {r["image_id"] for r in group["candidates"]}


def test_graph_dependency_passes_resolved_ids_and_missing_match_never_searches(engine):
    from unittest.mock import Mock

    graph = Mock()
    graph.select.side_effect = [
        {"status": "resolved", "entity_ids": ["brand"]},
        {"status": "no_graph_match", "entity_ids": []},
    ]
    engine.graph_store = graph
    first = make_step(action="resolve_entity")
    first["graph"] = {**relation_query(), "target_name": "Thương hiệu X", "conditions": []}
    second = make_step("s2", action="resolve_entity", deps=["s1"])
    second["graph"] = relation_query(anchor=None, step="s1")
    target = make_step("s3", deps=["s2"])
    result = engine.execute(make_plan([first, second, target], "multi-hop"), "keyword")
    assert graph.select.call_args.args[1]["s1"] == {"brand"}
    assert result["groups"][0]["status"] == "no_graph_match"
    assert result["groups"][0]["results"] == []
    graph.source_ids.assert_not_called()


def bridge_plan(conditions=("cổng đỏ",), graph=None):
    bridge = make_step(action="resolve_entity")
    bridge.update(conditions=list(conditions), graph=graph)
    return make_plan([bridge, make_step("s2", deps=["s1"])], "multi-hop")


# Vector gần ảnh 'bg' (Cửa hàng B) nhất; ảnh đích gần 'bi'.
BRIDGE_VECTORS = {"s1": np.array([0.99, 0.141]), "s2": np.array([0, 1])}


def test_visual_bridge_identifies_entity_then_searches_only_its_images(engine):
    engine.graph_store = FakeGraph(engine.catalog)
    vectors = {k: v / np.linalg.norm(v) for k, v in BRIDGE_VECTORS.items()}
    result = engine.execute(bridge_plan(), "vector", vectors)
    (trace,), (group,) = result["trace"], result["groups"]
    assert trace["method"] == "visual_bridge" and trace["entity_ids"] == ["b"]
    assert trace["hypotheses"][0]["images"][0]["image_id"] == "bg"
    assert group["results"][0]["image_id"] == "bi"
    assert all("B" in engine.catalog.image_entities[r["image_id"]] for r in group["candidates"])


def test_visual_bridge_result_is_marked_as_unverified_hypothesis(engine):
    engine.graph_store = FakeGraph(engine.catalog)
    vectors = {k: v / np.linalg.norm(v) for k, v in BRIDGE_VECTORS.items()}
    group = engine.execute(bridge_plan(), "vector", vectors)["groups"][0]
    assert group["verification_status"] == "visual_bridge_unverified"


def test_visual_bridge_scope_is_applied_before_ranking(engine):
    engine.graph_store = graph = FakeGraph(engine.catalog, scope=["a"], confirmed=["a"])
    vectors = {k: v / np.linalg.norm(v) for k, v in BRIDGE_VECTORS.items()}
    result = engine.execute(bridge_plan(graph=relation_query()), "vector", vectors)
    assert result["trace"][0]["entity_ids"] == ["a"]
    assert result["trace"][0]["hypotheses"][0]["graph_confirmed"] is True
    assert graph.selects == [(True, True), (True, False)]


def test_visual_bridge_without_graph_match_never_searches_everything(engine, monkeypatch):
    engine.graph_store = FakeGraph(engine.catalog, scope=[])
    monkeypatch.setattr(engine, "search", lambda *a, **k: pytest.fail("Không tìm toàn kho"))
    result = engine.execute(bridge_plan(graph=relation_query()), "keyword")
    assert result["groups"][0]["status"] == "no_graph_match"


def ranked(monkeypatch, engine, rows):
    monkeypatch.setattr(
        engine, "search", lambda *a, **k: [{"image_id": i, "score": s} for i, s in rows]
    )


def test_shared_top_image_with_no_other_evidence_is_ambiguous(engine, monkeypatch):
    engine.graph_store = FakeGraph(engine.catalog)
    ranked(monkeypatch, engine, [("00-conflict", 1.0)])
    result = engine.execute(bridge_plan(), "keyword")
    assert result["trace"][0]["status"] == "ambiguous_entity"
    assert {h["entity_id"] for h in result["trace"][0]["hypotheses"]} == {"a", "b"}
    assert result["groups"][0]["results"] == []


def test_equal_scores_prefer_graph_confirmed_then_next_images(engine, monkeypatch):
    rows = [("ag", 1.0), ("bg", 1.0), ("ai", 0.5)]
    ranked(monkeypatch, engine, rows)
    engine.graph_store = FakeGraph(engine.catalog)
    assert engine.execute(bridge_plan(), "keyword")["trace"][0]["entity_ids"] == ["a"]
    engine.graph_store = FakeGraph(engine.catalog, scope=["a", "b"], confirmed=["b"])
    plan = bridge_plan(graph=relation_query())
    assert engine.execute(plan, "keyword")["trace"][0]["entity_ids"] == ["b"]


def test_visual_bridge_needs_vector_for_its_own_step(engine):
    engine.graph_store = FakeGraph(engine.catalog)
    with pytest.raises(ValueError, match="step ID"):
        engine.execute(bridge_plan(), "vector", {"s2": np.array([0, 1])})


def test_unknown_anchor_becomes_soft_text_only_with_visual_description(engine):
    engine.graph_store = graph = FakeGraph(engine.catalog, scope=["a"], confirmed=["a"])
    graph.known = set()
    vectors = {k: v / np.linalg.norm(v) for k, v in BRIDGE_VECTORS.items()}
    result = engine.execute(bridge_plan(graph=relation_query()), "vector", vectors)
    (trace,), (group,) = result["trace"], result["groups"]
    assert graph.selects == []  # Không lọc được bằng tên graph không biết.
    assert trace["entity_ids"] == ["b"] and trace["unmatched_names"] == ["Thương hiệu X"]
    assert trace["hypotheses"][0]["graph_confirmed"] is None
    assert group["unmatched_names"] == ["Thương hiệu X"]
    # Cùng quan hệ nhưng không có mô tả nhận diện: vẫn trả rỗng.
    graph.scope = graph.confirmed = []
    plan = bridge_plan(conditions=(), graph=relation_query())
    result = engine.execute(plan, "keyword")
    assert result["groups"][0]["status"] == "no_graph_match"


def test_known_relations_still_filter_when_another_anchor_is_unknown(engine):
    engine.graph_store = graph = FakeGraph(engine.catalog, scope=["a"], confirmed=["a"])
    query = relation_query()
    query["conditions"].append({**query["conditions"][0], "anchor_name": "Nơi lạ"})
    vectors = {k: v / np.linalg.norm(v) for k, v in BRIDGE_VECTORS.items()}
    result = engine.execute(bridge_plan(graph=query), "vector", vectors)
    assert result["trace"][0]["entity_ids"] == ["a"]
    graph.selects.clear()
    result = engine.execute(bridge_plan(graph={**query, "match": "any"}), "vector", vectors)
    assert result["trace"][0]["entity_ids"] == ["b"] and graph.selects == []


def named_plan(identity, mention="Khu chợ Xa Lạ"):
    step = make_step(mention=mention)
    step["identity_text"] = identity
    return make_plan([step])


def test_unknown_name_is_identified_by_its_description_or_returns_nothing(engine, monkeypatch):
    engine.graph_store = graph = FakeGraph(engine.catalog, scope=[])
    graph.source_ids = lambda ids: {i.upper() for i in ids}
    vectors = {"s1": np.array([0, 1]), "s1:identity": BRIDGE_VECTORS["s1"]}
    vectors = {k: v / np.linalg.norm(v) for k, v in vectors.items()}
    result = engine.execute(named_plan("khu chợ cổng đỏ"), "vector", vectors)
    (trace,), (group,) = result["trace"], result["groups"]
    assert trace["entity_ids"] == ["b"] and trace["unmatched_names"] == ["Khu chợ Xa Lạ"]
    assert group["results"][0]["image_id"] == "bi"
    assert group["verification_status"] == "visual_bridge_unverified"
    monkeypatch.setattr(engine, "search", lambda *a, **k: pytest.fail("Không tìm toàn kho"))
    result = engine.execute(named_plan(None), "keyword")
    assert result["groups"][0]["status"] == "no_graph_match"


def test_known_name_never_uses_its_description_to_pick_another_entity(engine):
    engine.graph_store = FakeGraph(engine.catalog, scope=["a"], confirmed=["a"])
    vectors = {"s1": np.array([0, 1]), "s1:identity": BRIDGE_VECTORS["s1"]}
    vectors = {k: v / np.linalg.norm(v) for k, v in vectors.items()}
    result = engine.execute(named_plan("cổng đỏ", "Cửa hàng A"), "vector", vectors)
    assert result["trace"] == []
    assert result["groups"][0]["graph_entity_ids"] == ["a"]
    assert result["groups"][0]["verification_status"] == "trusted_metadata_scope"


@pytest.mark.parametrize("score,winner", [(0.95, "b"), (0.8, "a")])
def test_graph_confirmed_place_wins_only_within_margin(engine, monkeypatch, score, winner):
    ranked(monkeypatch, engine, [("ag", 1.0), ("bg", score)])
    engine.graph_store = FakeGraph(engine.catalog, scope=["a", "b"], confirmed=["b"])
    result = engine.execute(bridge_plan(graph=relation_query()), "keyword")
    assert result["trace"][0]["entity_ids"] == [winner]


@pytest.mark.parametrize("method", ["vector", "keyword", "hybrid"])
def test_website_filters_apply_before_ranking_and_never_reintroduce_deleted(engine, method):
    engine.visible_images = {"ag", "ai", "bg", "bi"}
    engine.filtered_images = {"bi", "other"}
    found = engine.search("bên trong", np.array([0, 1]), method, 1)
    assert [r["image_id"] for r in found] == ["bi"]
    evidence = engine.search("bên trong", np.array([0, 1]), method, 10, apply_filters=False)
    assert "ai" in {r["image_id"] for r in evidence}
    assert "other" not in {r["image_id"] for r in evidence}
