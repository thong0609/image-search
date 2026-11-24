import runpy
from pathlib import Path

import pytest

helpers = runpy.run_path(Path(__file__).parents[2] / "scripts/evaluate_retrieval.py")
merge_rankings, score_case = helpers["merge_rankings"], helpers["score_case"]
summarize = helpers["summarize"]


def query(**values):
    return {
        "query_id": "q1",
        "split": "dev",
        "type": "single",
        "answerable": True,
        "report_group": "canonical",
        **values,
    }


def prediction(*groups):
    return {"groups": [{"results": [{"image_id": i} for i in ids]} for ids in groups]}


ANSWER = {"targets": [{"image_ids": ["a"], "required": 1}, {"image_ids": ["b"], "required": 1}]}


def test_merge_is_balanced_unique_and_has_global_budget():
    lists = [[{"image_id": i} for i in ids] for ids in [["a", "b", "c"], ["a", "d", "e"]]]
    assert [r["image_id"] for r in merge_rankings(lists, 4)] == ["a", "b", "d", "c"]
    assert merge_rankings([[], []], 10) == []


def test_each_target_group_contributes_to_completeness():
    assert score_case(query(), ANSWER, prediction("a", "b"))["all_targets_complete@10"] == 1
    assert score_case(query(), ANSWER, prediction("a", "x"))["all_targets_complete@10"] == 0


def test_first_rank_is_measured_beyond_top_ten():
    score = score_case(query(), ANSWER, prediction([f"x{n}" for n in range(11)] + ["a"]))
    assert (score["first@10"], score["first@20"]) == (0, 1)


def test_errors_stay_in_denominator_and_families_are_averaged():
    queries = [query(query_id=q, intent_id="i") for q in ("q1", "q2")]
    queries.append(query(query_id="q3", answerable=False))
    answers = {q["query_id"]: ANSWER for q in queries}
    predictions = {"q1": prediction("a"), "q2": {"groups": []}, "q3": prediction("a")}
    (row,) = summarize(queries, answers, predictions).values()
    assert row["queries"] == 2 and row["đích@1"] == 0.5


def test_unknown_cannot_be_scored():
    with pytest.raises(ValueError, match="chưa rõ"):
        score_case(query(answerable=None), {"targets": []}, {"groups": []})
