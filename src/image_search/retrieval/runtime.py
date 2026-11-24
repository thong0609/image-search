"""Nạp Qdrant index và metadata corpus; không dùng nhãn đáp án."""

from image_search.baseline.keyword import load_keyword_index
from image_search.baseline.settings import get_baseline_settings
from image_search.baseline.utils import read_jsonl
from image_search.baseline.vectors import load_index
from image_search.retrieval.catalog import Catalog
from image_search.retrieval.engine import RetrievalEngine


def load_engine(embedding_settings, settings, aliases=None):
    corpus, index, store = load_index(embedding_settings.manifest, settings.qdrant_collection)
    baseline = get_baseline_settings()
    keyword, _ = load_keyword_index(
        corpus, settings.keyword_dir, baseline.keyword_k1, baseline.keyword_b
    )
    records = read_jsonl(corpus["files"]["records"]["path"])
    catalog = Catalog(records, index["image_ids"], aliases)
    return RetrievalEngine(index["image_ids"], store, keyword, catalog, settings), corpus, index
