import pytest

from image_search.baseline.evaluate import score_query


def query(answerable=True):
    return {
        "query_id": "q1",
        "split": "dev",
        "type": "multi-target",
        "synthetic": False,
        "answerable": answerable,
    }


def test_scores_each_target_then_averages_and_deduplicates_before_k():
    answer = {
        "targets": [{"image_ids": ["a", "b"], "required": 2}, {"image_ids": ["c"], "required": 1}]
    }
    results = [{"image_id": key} for key in ["a", "a", "c", "z", "b"]]
    score = score_query(query(), answer, results)
    assert score["known_recall@1"] == 0.25
    assert score["hit@1"] == 0.5
    assert score["known_ndcg@1"] == 0.5
    assert score["target_complete@1"] == 0
    assert score["known_recall@5"] == 1
    assert score["all_targets_complete@5"] == 1


def test_no_answer_has_no_recall_and_is_scored_separately():
    empty = score_query(query(False), {"targets": []}, [])
    assert empty["rejected"] is True
    assert "known_recall@1" not in empty
    found = score_query(query(False), {"targets": []}, [{"image_id": "a"}])
    assert found["rejected"] is False


def test_answerable_query_cannot_have_missing_targets():
    with pytest.raises(ValueError, match="thiếu mục tiêu"):
        score_query(query(), {"targets": []}, [])


def test_empty_predictions_have_zero_scores():
    score = score_query(query(), {"targets": [{"image_ids": ["a"], "required": 1}]}, [])
    assert score["known_recall@10"] == 0
    assert score["known_ndcg@10"] == 0
