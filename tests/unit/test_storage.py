import pytest

from image_search.adapters.object_storage.local import LocalObjectStorage


def test_object_is_immutable_and_identical_retry_is_allowed(tmp_path):
    storage = LocalObjectStorage(tmp_path)
    digest = storage.put("images/v1", b"original")
    assert storage.put("images/v1", b"original") == digest
    with pytest.raises(ValueError, match="Immutable"):
        storage.put("images/v1", b"replacement")
    assert storage.read("images/v1") == b"original"


@pytest.mark.parametrize("key", ["../outside", "/etc/passwd", "", "."])
def test_storage_rejects_keys_outside_object_namespace(tmp_path, key):
    storage = LocalObjectStorage(tmp_path)
    with pytest.raises(ValueError):
        storage.put(key, b"private")
