"""Dựng và kiểm tra image index trong Qdrant."""

import hashlib
import json
from pathlib import Path

import numpy as np
from PIL import Image

from image_search.adapters.qdrant.client import create_qdrant_client
from image_search.adapters.qdrant.metadata import read_payloads, sync_metadata
from image_search.adapters.qdrant.vectors import QdrantVectors, read_metadata
from image_search.baseline.benchmark import load_manifest
from image_search.baseline.settings import get_baseline_settings
from image_search.config import get_settings
from image_search.embedding.encoder import (
    PREPROCESSING,
    library_versions,
    load_encoder,
    normalize,
    processor_hash,
)
from image_search.files import file_hash, read_jsonl
from image_search.retrieval.catalog import Catalog
from image_search.retrieval.settings import RetrievalSettings


def build_index(
    manifest_path, collection=None, model_name=None, revision=None, batch_size=8, threads=4
):
    import torch

    settings = get_baseline_settings()
    collection = collection or RetrievalSettings().qdrant_collection
    if batch_size < 1 or threads < 1:
        raise ValueError("batch-size/threads phải lớn hơn 0")
    manifest = load_manifest(manifest_path)
    client = create_qdrant_client(get_settings())
    try:
        if client.collection_exists(collection):
            _, existing, existing_store = load_index(manifest_path, collection)
            existing_store.client.close()
            if existing["config"]["model"] != (model_name or settings.model_name) or existing[
                "config"
            ]["revision"] != (revision or settings.model_revision):
                raise ValueError("Index không tương thích; dùng collection mới")
            print("Dùng lại collection Qdrant đã kiểm tra")
            return
        model, processor = load_encoder(
            model_name or settings.model_name,
            revision or settings.model_revision,
            Path("var/models"),
            threads,
        )
        batches = []
        for start in range(0, len(manifest["images"]), batch_size):
            batch = []
            try:
                for row in manifest["images"][start : start + batch_size]:
                    with Image.open(row["local_path"]) as image:
                        batch.append(image.convert("RGB"))
                inputs = processor(images=batch, return_tensors="pt")
                with torch.inference_mode():
                    features = model.get_image_features(**inputs)
                batches.append(normalize(features.cpu().numpy()))
            finally:
                for image in batch:
                    image.close()
        vectors = np.concatenate(batches)
        index = {
            "config": {
                "manifest_sha256": file_hash(manifest_path),
                "model": model_name or settings.model_name,
                "revision": revision or settings.model_revision,
                "preprocessing": PREPROCESSING,
                "libraries": library_versions(),
            },
            "image_ids": [r["image_id"] for r in manifest["images"]],
            "shape": list(vectors.shape),
            "processor_sha256": processor_hash(processor),
        }
        index["index_sha256"] = hashlib.sha256(
            json.dumps(index, sort_keys=True).encode()
        ).hexdigest()
        catalog = Catalog(read_jsonl(manifest["files"]["records"]["path"]), index["image_ids"])
        store = QdrantVectors(client, collection, index["index_sha256"], vectors.shape[1])
        store.upload(
            index["image_ids"],
            vectors,
            catalog,
            index["config"]["model"],
            index["config"]["revision"],
        )
        sync_metadata(
            store, index, catalog, manifest["images"], manifest["files"]["records"]["sha256"]
        )
    finally:
        client.close()


def load_index(manifest_path=None, collection=None):
    collection = collection or RetrievalSettings().qdrant_collection
    manifest = load_manifest(manifest_path) if manifest_path else None
    client = create_qdrant_client(get_settings())
    try:
        metadata = read_metadata(client, collection)
        config = metadata["config"]
        if (
            (manifest_path and config["manifest_sha256"] != file_hash(manifest_path))
            or config["preprocessing"] != PREPROCESSING
            or config["libraries"] != library_versions()
        ):
            raise ValueError("Qdrant index không khớp corpus/model/thư viện")
        if manifest and [r["image_id"] for r in manifest["images"]] != metadata["image_ids"]:
            raise ValueError("Image IDs không khớp Qdrant index")
        store = QdrantVectors(client, collection, metadata["index_sha256"], metadata["shape"][1])
        store.validate(metadata["image_ids"])
        if not metadata.get("search_metadata_sha256"):
            raise ValueError(
                "Thiếu search metadata trong Qdrant; chạy image-search-qdrant --sync-metadata"
            )
        store.metadata_hash = metadata["search_metadata_sha256"]
        payloads = read_payloads(store, metadata["image_ids"], store.metadata_hash)
        store.payloads = payloads
        corpus = {"images": [payloads[iid]["image"] for iid in metadata["image_ids"]]}
        return manifest or corpus, metadata, store
    except Exception:
        client.close()
        raise
