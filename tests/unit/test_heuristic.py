from concurrent.futures import ThreadPoolExecutor
from unittest.mock import Mock

import pytest

from image_search.planner.heuristic import HeuristicPlanner
from image_search.search import SearchService
from image_search.timing import capture, span


@pytest.fixture
def planner():
    return HeuristicPlanner(
        [
            {"entity_id": "a", "name": "Gumac", "aliases": ["GUMAC Store"]},
            {"entity_id": "b", "name": "Canifa", "aliases": []},
            {"entity_id": "c", "name": "Chợ A", "aliases": ["Chợ chung"]},
            {"entity_id": "d", "name": "Chợ B", "aliases": ["Chợ chung"]},
            {"entity_id": "e", "name": "Trắng và Xanh", "aliases": []},
        ]
    )


@pytest.mark.parametrize(
    "text,kind,count",
    [
        ("Tìm cho tôi hình ảnh bên trong của Gumac", "single", 1),
        ("Ảnh sân bóng có mái che", "single", 1),
        ("Ảnh Gumac và Canifa", "multi-target", 2),
        ("ảnh bên ngoài và bên trong Gumac", "multi-target", 2),
        ("ảnh Trắng và Xanh", "single", 1),
        ("ảnh GUMAC Store", "single", 1),
    ],
)
def test_supported_grammar_compiles_to_existing_plan(planner, text, kind, count):
    decision = planner.decide(text)
    assert decision.plan.query_type == kind
    assert len(decision.plan.steps) == count
    assert all(s.action == "retrieve_images" and not s.depends_on for s in decision.plan.steps)


def test_shared_scope_keeps_name_for_both_views(planner):
    steps = planner.decide("ảnh bên ngoài và bên trong Gumac").plan.steps
    assert [s.entity_mention for s in steps] == ["Gumac", "Gumac"]
    assert steps[0].search_text != steps[1].search_text


@pytest.mark.parametrize(
    "text",
    [
        "ảnh bên trong sân vận động có mái đỏ",
        "ảnh không thuộc Gumac",
        "ảnh không có người",
        "ảnh Gumac ở Hà Nội",
        "ảnh Gumac gần Canifa",
        "ảnh của nơi vừa rồi",
        "ảnh đẹp nhất",
        "ảnh Chợ chung",
        "ảnh Gumacc",
        "ảnh Gumac và Canifa ở Hà Nội",
        "ảnh tòa nhà màu trắng và xanh",
        "ảnh bên trong nơi có mái đỏ",
        "ảnh bên trong cửa hàng chưa biết",
        "",
    ],
)
def test_uncertain_or_complex_query_falls_back_without_losing_conditions(planner, text):
    assert planner.decide(text).plan is None


def test_local_plan_does_not_call_llm(tmp_path, monkeypatch, planner):
    monkeypatch.setenv("IMAGE_SEARCH_PLANNER_LOCAL_MODE", "heuristic")
    service = SearchService(tmp_path)
    service.load = Mock()
    service.local_planner = planner
    monkeypatch.setattr("image_search.planner.router.make_client", Mock(side_effect=AssertionError))
    diagnostics = {}
    plan, cached = service.plan("ảnh Gumac", diagnostics)
    assert plan.query_type == "single" and not cached
    assert diagnostics["route"] == "heuristic"


def test_timing_is_isolated_between_concurrent_requests():
    def request(i):
        with capture() as values:
            with span(str(i)):
                pass
        return values

    with ThreadPoolExecutor(4) as pool:
        results = list(pool.map(request, range(8)))
    assert [set(v) for v in results] == [{str(i)} for i in range(8)]


def test_requested_count_is_preserved(planner):
    plan = planner.decide("Tìm 2 ảnh về Gumac").plan
    assert plan.steps[0].count == 2


def test_each_target_preserves_its_count(planner):
    plan = planner.decide("Tìm 2 ảnh về Gumac và 3 ảnh về Canifa").plan
    assert [s.count for s in plan.steps] == [2, 3]


def test_default_mode_preserves_llm_path(tmp_path, monkeypatch):
    monkeypatch.setenv("IMAGE_SEARCH_PLANNER_LOCAL_MODE", "off")
    service = SearchService(tmp_path)
    service.load = Mock(side_effect=AssertionError("No extra loading with heuristic disabled"))
    assert service.local_plan("ảnh Gumac").reason == "disabled"


def test_new_snapshot_replaces_names():
    old = HeuristicPlanner([{"entity_id": "a", "name": "Cửa hàng cũ"}])
    new = HeuristicPlanner([{"entity_id": "b", "name": "Cửa hàng mới"}])
    assert old.decide("ảnh Cửa hàng cũ").plan is not None
    assert new.decide("ảnh Cửa hàng cũ").plan is None
    assert new.decide("ảnh Cửa hàng mới").plan is not None


def test_playground_can_use_heuristic_without_paid_client(tmp_path, monkeypatch, planner):
    from image_search.playground import PlaygroundService

    monkeypatch.setenv("IMAGE_SEARCH_PLANNER_LOCAL_MODE", "heuristic")
    search = SearchService(tmp_path)
    search.load = Mock()
    search.local_planner = planner
    monkeypatch.setattr("image_search.planner.router.make_client", Mock(side_effect=AssertionError))
    result = PlaygroundService(search).run("ảnh Gumac", "planner", "hybrid")
    assert result["planner"]["route"] == "heuristic"
    assert result["planner"]["status"] == "ok"
    assert result["planner"]["input_tokens"] == 0
