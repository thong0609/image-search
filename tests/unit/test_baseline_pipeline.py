"""Chạy toàn pipeline bằng ảnh tự tạo và model SigLIP rất nhỏ, không dùng mạng."""

import csv
import hashlib

import pytest
from PIL import Image

pytest.importorskip("torch")
pytest.importorskip("transformers")

from tokenizers import Tokenizer  # noqa: E402
from tokenizers.models import WordLevel  # noqa: E402
from tokenizers.pre_tokenizers import Whitespace  # noqa: E402
from transformers import (  # noqa: E402
    PreTrainedTokenizerFast,
    SiglipConfig,
    SiglipImageProcessor,
    SiglipModel,
    SiglipProcessor,
)

from image_search.baseline.benchmark import draft_benchmark, freeze_benchmark  # noqa: E402
from image_search.baseline.evaluate import evaluate_predictions  # noqa: E402
from image_search.baseline.records import REQUIRED_COLUMNS, read_approved_records  # noqa: E402
from image_search.baseline.utils import read_json, read_jsonl, write_jsonl  # noqa: E402
from image_search.baseline.vectors import build_index, search_index  # noqa: E402


def make_tiny_model(path):
    config = SiglipConfig(
        text_config={
            "vocab_size": 8,
            "hidden_size": 16,
            "intermediate_size": 32,
            "num_hidden_layers": 1,
            "num_attention_heads": 2,
            "max_position_embeddings": 8,
        },
        vision_config={
            "hidden_size": 16,
            "intermediate_size": 32,
            "num_hidden_layers": 1,
            "num_attention_heads": 2,
            "image_size": 16,
            "patch_size": 8,
        },
    )
    SiglipModel(config).save_pretrained(path)
    tokenizer = Tokenizer(
        WordLevel(
            {"[UNK]": 0, "[PAD]": 1, "[EOS]": 2, "ảnh": 3, "đỏ": 4, "xanh": 5, "tìm": 6, ".": 7},
            unk_token="[UNK]",
        )
    )
    tokenizer.pre_tokenizer = Whitespace()
    tokenizer = PreTrainedTokenizerFast(
        tokenizer_object=tokenizer,
        unk_token="[UNK]",
        pad_token="[PAD]",
        eos_token="[EOS]",
        model_input_names=["input_ids"],
    )
    processor = SiglipProcessor(SiglipImageProcessor(size={"height": 16, "width": 16}), tokenizer)
    processor.save_pretrained(path)


def test_full_baseline_with_local_tiny_model(tmp_path, monkeypatch):
    source = tmp_path / "source.csv"
    with source.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=REQUIRED_COLUMNS)
        writer.writeheader()
        for index in range(8):
            row = dict.fromkeys(REQUIRED_COLUMNS, "")
            row.update(
                entity_id=f"e{index // 2}",
                entity_name=f"Địa điểm {index // 2}",
                mo_ta="Ảnh màu trong fixture",
                approve="yes",
                image_url=f"https://example.com/{index}",
            )
            writer.writerow(row)
    records = read_approved_records(source)
    for index, record in enumerate(records):
        path = tmp_path / f"image-{index}.png"
        Image.new("RGB", (16, 16), (index * 30, 50, 200)).save(path)
        record.update(
            download_status="success",
            local_path=str(path),
            image_id=hashlib.sha256(path.read_bytes()).hexdigest(),
        )
    records_path = tmp_path / "downloaded-records.jsonl"
    write_jsonl(records_path, records)
    draft_benchmark(records_path, tmp_path, per_type=1)
    queries_path = tmp_path / "queries.jsonl"
    answers_path = tmp_path / "answers.jsonl"
    queries = read_jsonl(queries_path)
    for query in queries:
        query.update(text="tìm ảnh đỏ .", reviewed=True)
    answers = read_jsonl(answers_path)
    for answer in answers:
        answer["verification"] = "Nhãn fixture tổng hợp, chỉ kiểm tra code"
    write_jsonl(queries_path, queries)
    write_jsonl(answers_path, answers)
    manifest = tmp_path / "benchmark.json"
    freeze_benchmark(source, records_path, queries_path, answers_path, manifest)
    model_path = tmp_path / "tiny-model"
    make_tiny_model(model_path)
    index_dir = tmp_path / "index"
    build_index(manifest, index_dir, str(model_path), "0" * 40, batch_size=2, threads=1)
    # Chạy lại dùng index cũ, không tạo vector lần nữa.
    build_index(manifest, index_dir, str(model_path), "0" * 40, batch_size=2, threads=1)
    output = search_index(manifest, index_dir, split="dev", threads=1)
    report = evaluate_predictions(manifest, output / "predictions.jsonl")
    assert report["summary"]["dev/answerable"]["queries"] == 3
    assert report["summary"]["dev/no-answer"]["queries"] == 1
    assert read_json(output / "run.json")["rounds"] == 3
    assert len(read_jsonl(output / "timings.jsonl")) == 12
    assert (output / "results.html").exists()
    assert (output / "report.md").exists()
    predictions = read_jsonl(output / "predictions.jsonl")
    predictions[0]["results"][0]["image_id"] = "unknown"
    write_jsonl(output / "bad.jsonl", predictions)
    with pytest.raises(ValueError, match="ID lạ"):
        evaluate_predictions(manifest, output / "bad.jsonl")
    write_jsonl(output / "missing.jsonl", predictions[1:])
    with pytest.raises(ValueError, match="thiếu hoặc thừa query"):
        evaluate_predictions(manifest, output / "missing.jsonl")
    with pytest.raises(ValueError, match="Index không tương thích"):
        build_index(manifest, index_dir, str(model_path), "1" * 40)
    for method in ["hybrid", "keyword"]:
        if method == "keyword":
            monkeypatch.setattr(
                "image_search.baseline.vectors.load_encoder",
                lambda *args: pytest.fail("Keyword không được nạp model"),
            )
        output = search_index(
            manifest, index_dir, split="dev", threads=1, method=method, output_dir=tmp_path / method
        )
        report = evaluate_predictions(manifest, output / "predictions.jsonl")
        assert report["run"]["method"] == method
        if method == "hybrid":
            assert report["run"]["hybrid"] == {
                "fusion": "rrf",
                "weights": {"vector": 1, "keyword": 1},
                "rrf_k": 60,
                "candidates": 100,
            }
        assert len(read_jsonl(output / "predictions.jsonl")) == 4
        assert read_json(output / "run.json")["keyword_index"]["config"]["fields"] == [
            "entity_name",
            "leaf_label",
            "page_title",
            "mo_ta",
        ]
