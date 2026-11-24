# ruff: noqa: E402
# The embedding stack is an optional baseline extra; tests never load model weights.
from types import SimpleNamespace

import pytest

np = pytest.importorskip("numpy")
torch = pytest.importorskip("torch")

from image_search.embedding.encoder import encode_text, normalize
from image_search.embedding.settings import EmbeddingSettings
from image_search.embedding.siglip2 import Siglip2Embedding


class Processor:
    def __call__(self, text, padding, truncation, **kwargs):
        tokens = [[len(w) for w in t.split()] + [1] for t in text]
        if not kwargs.get("return_tensors"):
            return {"input_ids": tokens}
        length = kwargs["max_length"]
        return {"input_ids": torch.tensor([(t[:length] + [0] * length)[:length] for t in tokens])}


class Model:
    config = SimpleNamespace(text_config=SimpleNamespace(max_position_embeddings=4))

    def get_text_features(self, input_ids):
        return torch.stack([input_ids.sum(dim=1), input_ids[:, 0]], dim=1).float()


@pytest.fixture
def encoder(monkeypatch):
    from image_search.embedding import siglip2

    metadata = {"config": {"model": "test", "revision": "a" * 40}, "processor_sha256": "test"}
    monkeypatch.setattr(
        siglip2, "load_index", lambda *_: ({}, metadata, SimpleNamespace(dimensions=2))
    )
    monkeypatch.setattr(siglip2, "load_encoder", lambda *_: (Model(), Processor()))
    monkeypatch.setattr(siglip2, "processor_hash", lambda _: "test")
    return Siglip2Embedding(EmbeddingSettings(_env_file=None, batch_size=2))


def test_batch_vectors_match_single_baseline_encoding_and_keep_order(encoder):
    texts = ["ảnh cổng đỏ", "bên trong", "khách sạn màu xanh"]
    actual, _ = encoder.encode_texts(texts)
    expected = np.stack([encode_text(t, encoder.model, encoder.processor) for t in texts])
    assert actual.shape == (3, 2)
    assert actual.dtype == np.float32
    assert np.allclose(actual, expected)
    assert np.allclose(np.linalg.norm(actual, axis=1), 1)


def test_long_text_is_flagged_when_truncated(encoder):
    _, details = encoder.encode_texts(["một hai ba bốn năm", "ngắn"])
    assert details == [
        {"token_count": 6, "truncated": True},
        {"token_count": 2, "truncated": False},
    ]


@pytest.mark.parametrize("texts", [[], [""], ["đúng", "   "], [None]])
def test_invalid_text_batch_is_rejected(encoder, texts):
    with pytest.raises(ValueError, match="text"):
        encoder.encode_texts(texts)


def test_text_and_image_dimensions_cannot_silently_diverge(encoder):
    encoder.dimensions = 3
    with pytest.raises(ValueError, match="chiều"):
        encoder.encode_texts(["ảnh"])


def test_processor_mismatch_rejects_model(monkeypatch, encoder):
    monkeypatch.setattr("image_search.embedding.siglip2.processor_hash", lambda _: "changed")
    with pytest.raises(ValueError, match="Processor"):
        Siglip2Embedding(EmbeddingSettings(_env_file=None))


@pytest.mark.parametrize("vectors", [[[0, 0]], [[float("nan"), 1]]])
def test_invalid_vectors_are_rejected(vectors):
    with pytest.raises(ValueError):
        normalize(vectors)
