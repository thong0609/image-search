"""Nhập ảnh/metadata vào Qdrant; không tạo file vector."""

import argparse

from image_search.adapters.qdrant.client import create_qdrant_client
from image_search.adapters.qdrant.metadata import sync_metadata
from image_search.adapters.qdrant.vectors import QdrantVectors, read_metadata
from image_search.baseline.benchmark import load_manifest
from image_search.baseline.utils import file_hash, read_jsonl
from image_search.baseline.vectors import build_index
from image_search.config import get_settings
from image_search.embedding.settings import EmbeddingSettings
from image_search.retrieval.catalog import Catalog
from image_search.retrieval.settings import RetrievalSettings


def main():
    parser = argparse.ArgumentParser(description="Index ảnh hoặc bổ sung metadata Qdrant")
    parser.add_argument(
        "--sync-metadata",
        action="store_true",
        help="Chỉ nạp metadata từ nguồn đã pin, không encode lại ảnh",
    )
    args = parser.parse_args()
    settings = EmbeddingSettings()
    collection = RetrievalSettings().qdrant_collection
    if not args.sync_metadata:
        build_index(
            settings.manifest, collection, batch_size=settings.batch_size, threads=settings.threads
        )
        return
    corpus = load_manifest(settings.manifest)
    client = create_qdrant_client(get_settings())
    try:
        index = read_metadata(client, collection)
        if index["config"]["manifest_sha256"] != file_hash(settings.manifest) or index[
            "image_ids"
        ] != [r["image_id"] for r in corpus["images"]]:
            raise ValueError("Metadata nguồn không khớp corpus của Qdrant")
        catalog = Catalog(read_jsonl(corpus["files"]["records"]["path"]), index["image_ids"])
        store = QdrantVectors(client, collection, index["index_sha256"], index["shape"][1])
        sync_metadata(store, index, catalog, corpus["images"], corpus["files"]["records"]["sha256"])
        print(f"Đã nạp và kiểm tra metadata {len(index['image_ids'])} ảnh -> {collection}")
    finally:
        client.close()


if __name__ == "__main__":
    main()
