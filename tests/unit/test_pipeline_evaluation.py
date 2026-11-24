# ruff: noqa: E402
import runpy
from pathlib import Path

import pytest

pytest.importorskip("torch")

helpers = runpy.run_path(Path(__file__).parents[2] / "scripts/report_pipeline_evaluation.py")
merge_rankings = helpers["merge_rankings"]
score_pipeline_case = helpers["score_pipeline_case"]


def query(kind="multi-target", answerable=True):
    return {
        "query_id": "q1",
        "split": "dev",
        "type": kind,
        "answerable": answerable,
        "synthetic": True,
        "intent_id": "intent",
        "report_group": "canonical",
        "evaluation_suite": "entity_retrieval",
    }


def test_merge_is_balanced_unique_and_has_global_budget():
    lists = [[{"image_id": i} for i in ids] for ids in [["a", "b", "c"], ["a", "d", "e"]]]
    assert [r["image_id"] for r in merge_rankings(lists, 4)] == ["a", "b", "d", "c"]
    assert merge_rankings([[], []], 10) == []


def test_ambiguous_hypotheses_are_only_diagnostic_candidates():
    answer = {"targets": [{"image_ids": ["a"], "required": 1}]}
    prediction = {"groups": [{"results": [], "hypotheses": [{"candidates": [{"image_id": "a"}]}]}]}
    score = score_pipeline_case(query("single"), answer, prediction)
    assert score["known_recall@10"] == 0
    assert score["candidate_known_recall@100"] == 1
    assert score["all_targets_complete@10"] == 0


def test_one_mixed_group_cannot_count_as_two_separate_targets():
    answer = {"targets": [{"image_ids": ["a"], "required": 1}, {"image_ids": ["b"], "required": 1}]}
    prediction = {"groups": [{"results": [{"image_id": "a"}, {"image_id": "b"}], "hypotheses": []}]}
    score = score_pipeline_case(query(), answer, prediction)
    assert score["all_targets_complete@10"] == 1
    assert score["separate_group_matching_complete@10"] == 0
    prediction["groups"] = [
        {"results": [{"image_id": iid}], "hypotheses": []} for iid in ("a", "b")
    ]
    assert (
        score_pipeline_case(query(), answer, prediction)["separate_group_matching_complete@10"] == 1
    )


def test_errors_stay_in_quality_denominator_as_empty_predictions():
    answer = {"targets": [{"image_ids": ["a"], "required": 1}]}
    score = score_pipeline_case(query("single"), answer, {"status": "planner_error", "groups": []})
    assert score["known_ndcg@10"] == 0
    assert score["candidate_known_recall@100"] == 0


def test_unknown_cannot_be_scored_as_negative():
    with pytest.raises(ValueError, match="Unknown"):
        score_pipeline_case(query(answerable=None), {"targets": []}, {"groups": []})
