from typing import Protocol


class TextEncoder(Protocol):
    def encode(self, text: str) -> list[float]: ...


class VectorRetriever(Protocol):
    def retrieve(self, vector: list[float], limit: int) -> list[str]: ...


class Reranker(Protocol):
    def rank(self, query: str, image_ids: list[str]) -> list[str]: ...
