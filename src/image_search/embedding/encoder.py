"""Nạp SigLIP2 đã pin và chuẩn hóa vector."""

import hashlib
import importlib.metadata

PREPROCESSING = "rgb;processor-default;max_length=model;truncate;l2;float32;v1"


def library_versions():
    return {
        name: importlib.metadata.version(name)
        for name in ["torch", "transformers", "numpy", "pillow", "tokenizers"]
    }


def load_encoder(model_name, revision, cache_dir, threads=4):
    import torch
    from transformers import AutoModel, AutoProcessor

    if len(revision) != 40 or any(c not in "0123456789abcdef" for c in revision):
        raise ValueError("revision phải là commit SHA đầy đủ (40 ký tự)")
    if threads < 1:
        raise ValueError("threads phải lớn hơn 0")
    torch.set_num_threads(threads)
    processor = AutoProcessor.from_pretrained(model_name, revision=revision, cache_dir=cache_dir)
    model = AutoModel.from_pretrained(model_name, revision=revision, cache_dir=cache_dir).eval()
    return model, processor


def processor_hash(processor):
    text = processor.image_processor.to_json_string()
    text += processor.tokenizer.backend_tokenizer.to_str()
    return hashlib.sha256(text.encode()).hexdigest()


def normalize(vectors):
    import numpy as np

    vectors = np.asarray(vectors, dtype=np.float32)
    norms = np.linalg.norm(vectors, axis=-1, keepdims=True)
    if not np.isfinite(vectors).all() or (norms <= 0).any():
        raise ValueError("Vector rỗng/NaN/Inf")
    return vectors / norms


def encode_text(text, model, processor):
    import torch

    if not text.strip():
        raise ValueError("Câu tìm kiếm không được rỗng")
    inputs = processor(
        text=[text],
        padding="max_length",
        truncation=True,
        max_length=model.config.text_config.max_position_embeddings,
        return_tensors="pt",
    )
    with torch.inference_mode():
        features = model.get_text_features(**inputs)
    return normalize(features.cpu().numpy())[0]
