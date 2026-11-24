"""Kiểm tra encoder khớp index ảnh và số token của một câu; không gọi OpenAI."""

import argparse
import json

from image_search.embedding.settings import EmbeddingSettings
from image_search.embedding.siglip2 import Siglip2Embedding


def main():
    parser = argparse.ArgumentParser(description="Kiểm tra embedding SigLIP2")
    commands = parser.add_subparsers(dest="command", required=True)
    check = commands.add_parser("check", help="Mã hóa lại ảnh mẫu, so với vector trong Qdrant")
    check.add_argument("--verify-samples", type=int, default=3)
    text = commands.add_parser("text", help="Mã hóa một câu, báo số token và có bị cắt không")
    text.add_argument("input")
    args = parser.parse_args()
    try:
        encoder = Siglip2Embedding(EmbeddingSettings())
        result = {
            "model": encoder.index["config"]["model"],
            "revision": encoder.index["config"]["revision"],
            "image_count": len(encoder.index["image_ids"]),
            "dimensions": encoder.dimensions,
            "max_text_tokens": encoder.max_length,
        }
        if args.command == "check":
            result["image_sample_checks"] = encoder.verify_image_samples(args.verify_samples)
        else:
            result["text"] = encoder.encode_texts([args.input])[1][0]
        print(json.dumps(result, ensure_ascii=False, indent=2))
    except (OSError, ValueError, KeyError) as error:
        parser.exit(1, f"Lỗi: {error}\n")
