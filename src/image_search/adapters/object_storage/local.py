import hashlib
import os
import tempfile
from pathlib import Path


class LocalObjectStorage:
    def __init__(self, root: Path):
        self.root = root.resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    def _path(self, key: str) -> Path:
        path = (self.root / key).resolve()
        if (
            not key
            or Path(key).is_absolute()
            or ".." in Path(key).parts
            or path == self.root
            or not path.is_relative_to(self.root)
        ):
            raise ValueError("Object key must stay inside storage root")
        return path

    def put(self, key: str, content: bytes) -> str:
        path = self._path(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        # Publish a complete file atomically without replacing an existing artifact.
        fd, temporary = tempfile.mkstemp(dir=path.parent)
        try:
            with os.fdopen(fd, "wb") as stream:
                stream.write(content)
                stream.flush()
                os.fsync(stream.fileno())
            try:
                os.link(temporary, path)
            except FileExistsError:
                if path.read_bytes() != content:
                    raise ValueError(
                        "Immutable object already exists with different content"
                    ) from None
        finally:
            Path(temporary).unlink(missing_ok=True)
        return hashlib.sha256(content).hexdigest()

    def read(self, key: str) -> bytes:
        return self._path(key).read_bytes()

    def probe(self) -> None:
        fd, name = tempfile.mkstemp(dir=self.root)
        os.close(fd)
        Path(name).unlink()
