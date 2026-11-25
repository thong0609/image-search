"""Khởi tạo retrieval từ Qdrant và Neo4j cùng snapshot, không đọc file metadata nguồn."""

from image_search.adapters.neo4j.client import load_graph
from image_search.baseline.settings import get_baseline_settings
from image_search.embedding.index import load_index
from image_search.embedding.text_index import load_text_store
from image_search.retrieval.catalog import Catalog
from image_search.retrieval.engine import RetrievalEngine
from image_search.retrieval.keyword import build_keyword_index


def load_engine(embedding_settings, settings, aliases=None):
    corpus, index, store = load_index(collection=settings.qdrant_collection)
    baseline = get_baseline_settings()
    records = [r for payload in store.payloads.values() for r in payload["records"]]
    keyword, keyword_metadata = build_keyword_index(
        records, index["image_ids"], baseline.keyword_k1, baseline.keyword_b
    )
    graph = None
    try:
        text_store, text_metadata = None, None
        if settings.text_vectors:
            text_store, text_metadata = load_text_store(store, index)
        graph = load_graph(index, store.payloads)
        catalog = Catalog(records, index["image_ids"], aliases)
        engine = RetrievalEngine(
            index["image_ids"], store, keyword, catalog, settings, graph, text_store
        )
        engine.keyword_metadata = keyword_metadata
        engine.text_metadata = text_metadata
        return engine, corpus, index
    except Exception:
        if graph is not None:
            graph.driver.close()
        store.client.close()
        raise
