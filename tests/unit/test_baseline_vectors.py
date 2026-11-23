import pytest

np = pytest.importorskip("numpy")

from image_search.baseline.vectors import normalize, rank_images  # noqa: E402


def test_cosine_search_uses_stable_image_id_order_for_ties():
    vectors = normalize([[1, 0], [1, 0], [0, 1]])
    found = rank_images(np.array([1, 0]), vectors, ["b", "a", "c"], 2)
    assert [row["image_id"] for row in found] == ["a", "b"]


@pytest.mark.parametrize("vectors", [[[0, 0]], [[float("nan"), 1]]])
def test_invalid_vectors_are_rejected(vectors):
    with pytest.raises(ValueError):
        normalize(vectors)
