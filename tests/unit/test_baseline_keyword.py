import math

import pytest

pytest.importorskip("numpy")

from image_search.retrieval.keyword import (  # noqa: E402
    build_documents,
    build_keyword_index,
    fuse_rankings,
    keyword_search,
    prepare_bm25,
    tokenize,
)


def test_vietnamese_keywords_match_with_or_without_accents():
    assert tokenize("ĐÀ NẴNG, Chợ Hàn!") == tokenize("da nang cho han")
    assert tokenize("Đa\u0300 Na\u0306\u0303ng") == ["da", "nang"]


def test_documents_keep_all_image_links_without_using_labels():
    records = [
        {
            "image_id": "a",
            "download_status": "success",
            "entity_name": "Đà Nẵng",
            "mo_ta": "Cổng chợ",
            "query_id": "secret",
            "targets": ["answer"],
        },
        {"image_id": "a", "download_status": "success", "entity_name": "Chợ Hàn"},
        {"image_id": None, "download_status": "failed", "entity_name": "Không được lấy"},
    ]
    docs = build_documents(records + records, ["a", "b"])
    assert docs == [
        {"image_id": "a", "text": "Chợ Hàn\nCổng chợ\nĐà Nẵng"},
        {"image_id": "b", "text": ""},
    ]


def test_bm25_matches_hand_calculation_and_skips_zero_scores():
    docs = [
        {"image_id": "a", "text": "chợ chợ hàn"},
        {"image_id": "b", "text": "chợ"},
        {"image_id": "c", "text": ""},
    ]
    index = prepare_bm25(docs, 1.2, 0.75)
    results = keyword_search("cho", index, 10)
    scores = {r["image_id"]: r["score"] for r in results}
    expected = math.log(1 + 1.5 / 2.5) * 2 * 2.2 / (2 + 1.2 * (0.25 + 0.75 * 3 / (4 / 3)))
    assert scores["a"] == pytest.approx(expected)
    assert set(scores) == {"a", "b"}
    assert keyword_search("xyznotfound", index, 10) == []
    assert keyword_search("!!!", index, 10) == []


def test_bm25_ties_are_stable_by_image_id():
    index = prepare_bm25(
        [{"image_id": "b", "text": "chợ"}, {"image_id": "a", "text": "chợ"}], 1.2, 0.75
    )
    assert [r["image_id"] for r in keyword_search("chợ", index, 2)] == ["a", "b"]


def test_rrf_uses_ranks_instead_of_raw_score_scales():
    vector = [{"image_id": "a", "score": 0.9}, {"image_id": "b", "score": 0.8}]
    keyword = [{"image_id": "b", "score": 100}, {"image_id": "a", "score": 1}]
    results = fuse_rankings([vector, keyword], 2, 60)
    assert [r["image_id"] for r in results] == ["a", "b"]
    assert results[0]["score"] == pytest.approx(1 / 61 + 1 / 62)
    assert results[1]["score"] == results[0]["score"]
    assert fuse_rankings([vector, []], 2, 60)[0]["score"] == pytest.approx(1 / 61)
    assert fuse_rankings([[], keyword], 2, 60)[0]["image_id"] == "b"
    assert fuse_rankings([vector + vector, keyword], 10, 60) == results


def test_rrf_adds_votes_only_from_branches_containing_the_image():
    results = fuse_rankings([[{"image_id": "a"}], [{"image_id": "b"}]], 10, 60)
    assert results == [{"image_id": "a", "score": 1 / 61}, {"image_id": "b", "score": 1 / 61}]
    assert fuse_rankings([[], []], 10, 60) == []


@pytest.mark.parametrize("top_k,rrf_k", [(0, 60), (10, 0)])
def test_rrf_rejects_invalid_parameters(top_k, rrf_k):
    with pytest.raises(ValueError, match="RRF"):
        fuse_rankings([[], []], top_k, rrf_k)


def test_keyword_index_is_built_in_memory_from_records():
    records = [{"image_id": "a", "download_status": "success", "entity_name": "Chợ Hàn"}]
    index, metadata = build_keyword_index(records, ["a"], 1.2, 0.75)
    assert keyword_search("chợ", index, 10)[0]["image_id"] == "a"
    assert metadata["source"] == "qdrant_payload"
    _, repeated = build_keyword_index(records, ["a"], 1.2, 0.75)
    assert metadata == repeated
    records[0]["entity_name"] = "Tên mới"
    _, changed = build_keyword_index(records, ["a"], 1.2, 0.75)
    assert metadata["documents_sha256"] != changed["documents_sha256"]
