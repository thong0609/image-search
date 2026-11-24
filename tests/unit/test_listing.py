"""Danh sách ảnh luôn có kết quả; không gọi model thật."""

from types import SimpleNamespace
from unittest.mock import Mock

import pytest

np = pytest.importorskip("numpy")

from image_search.retrieval.listing import append, interleave, search_list, target_texts  # noqa: E402


def step(sid, target="t1", action="retrieve_images", text="ảnh", deps=(), **values):
    return {
        "id": sid,
        "target_id": target,
        "action": action,
        "search_text": text,
        "entity_mention": None,
        "conditions": [],
        "count": None,
        "depends_on": list(deps),
        **values,
    }


def plan(steps, kind="single"):
    return {
        "query_type": kind,
        "needs_clarification": False,
        "clarification_question": None,
        "steps": steps,
    }


def rows(*ids):
    return [{"image_id": i, "score": 1.0} for i in ids]


def group(ids, target="t1", status="candidates", check="trusted_metadata_scope"):
    return {
        "target_id": target,
        "status": status,
        "candidates": rows(*ids),
        "results": rows(*ids)[:1],
        "verification_status": check,
    }


def engine(groups, whole, trace=()):
    result = Mock()
    result.settings = SimpleNamespace(list_size=20, top_k=100)
    result.execute.return_value = {"status": "x", "groups": groups, "trace": list(trace)}
    result.search.return_value = rows(*whole)
    return result


def ids(result, n=0):
    return [r["image_id"] for r in result["groups"][n]["results"]]


def test_interleave_keeps_first_rank_and_never_repeats():
    merged = interleave(rows("a", "b"), rows("b", "c", "d"))
    assert [r["image_id"] for r in merged] == ["a", "b", "c", "d"]
    assert [r["image_id"] for r in append(rows("a", "b"), rows("c", "a"))] == ["a", "b", "c"]


def test_trusted_place_comes_first_and_requested_count_does_not_cut_the_list():
    item = plan([step("s1", count=1)])
    result = search_list(engine([group("ab")], "xay"), None, "câu", item, "keyword")
    assert ids(result) == ["a", "b", "x", "y"]
    assert result["status"] == "candidate_results"
    assert [r["source"] for r in result["groups"][0]["results"]][:3] == ["place", "place", "query"]


def test_guessed_place_is_interleaved_with_whole_query():
    guessed = group("abc", check="visual_bridge_unverified")
    result = search_list(engine([guessed], "xy"), None, "câu", plan([step("s1")]), "keyword")
    assert ids(result) == ["a", "x", "b", "y", "c"]


@pytest.mark.parametrize("status", ["no_graph_match", "unsupported_graph_relation"])
def test_unresolved_target_falls_back_to_whole_query_and_keeps_reason(status):
    empty = {**group("", status=status), "results": []}
    result = search_list(engine([empty], "xy"), None, "câu", plan([step("s1")]), "keyword")
    assert ids(result) == ["x", "y"]
    assert result["status"] == result["groups"][0]["status"] == "fallback_results"
    assert result["groups"][0]["resolution_status"] == status


def test_planner_error_lists_whole_query_and_clarification_still_asks():
    item = engine([], "xy")
    assert ids(search_list(item, None, "câu", None, "keyword")) == ["x", "y"]
    item.execute.assert_not_called()
    unclear = plan([], "unclear") | {"needs_clarification": True, "clarification_question": "Gì?"}
    item.execute.return_value = {"status": "needs_clarification", "groups": [], "trace": []}
    assert search_list(item, None, "câu", unclear)["groups"] == []
    item.search.assert_called_once()


def test_multi_target_keeps_groups_and_uses_each_targets_own_text():
    steps = [
        step("s1", "t1", text="chợ A"),
        step("s2", "t2", "resolve_entity", text="chùa có tháp"),
        step("s3", "t2", text="chuông", deps=["s2"]),
    ]
    item = engine([group("a", "t1"), group("b", "t2")], "x")
    result = search_list(item, None, "cả câu", plan(steps, "multi-target"), "keyword")
    assert [g["target_id"] for g in result["groups"]] == ["t1", "t2"]
    searched = [c.args[0] for c in item.search.call_args_list]
    assert searched == ["chợ A", "chùa có tháp chuông"]
    assert target_texts(None, "cả câu") == {"t1": "cả câu"}


def test_tied_places_are_mixed_instead_of_returning_nothing():
    steps = [step("s1", action="resolve_entity"), step("s2", text="chuông", deps=["s1"])]
    trace = [{"step_id": "s1", "status": "ambiguous_entity", "tied_entity_ids": ["a", "b"]}]
    empty = {**group("", status="ambiguous_entity"), "results": []}
    item = engine([empty], "", trace)
    item.graph_store.source_ids.return_value = {"A", "B"}
    item.search.side_effect = [rows("x", "y"), rows("p", "q")]
    result = search_list(item, None, "câu", plan(steps, "multi-hop"), "keyword")
    assert ids(result) == ["p", "x", "q", "y"]
    assert item.search.call_args.kwargs["entity_ids"] == {"A", "B"}


def test_long_query_uses_keyword_fallback_but_long_step_is_rejected():
    encoder = Mock()
    encoder.encode_texts.return_value = (np.eye(2), [{"truncated": False}, {"truncated": True}])
    item = engine([group("a")], "x")
    search_list(item, encoder, "câu rất dài", plan([step("s1")]), "hybrid")
    assert item.search.call_args.args[1:3] == (None, "keyword")
    assert set(item.execute.call_args.args[2]) == {"s1"}
    encoder.encode_texts.return_value = (np.eye(2), [{"truncated": True}, {"truncated": False}])
    with pytest.raises(ValueError, match="cắt token"):
        search_list(item, encoder, "câu", plan([step("s1")]), "hybrid")
