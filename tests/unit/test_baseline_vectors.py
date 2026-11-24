import pytest

np = pytest.importorskip("numpy")

from image_search.baseline.vectors import normalize  # noqa: E402


@pytest.mark.parametrize("vectors", [[[0, 0]], [[float("nan"), 1]]])
def test_invalid_vectors_are_rejected(vectors):
    with pytest.raises(ValueError):
        normalize(vectors)
