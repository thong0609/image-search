import csv
import json

import pytest

from image_search.baseline.records import REQUIRED_COLUMNS, read_approved_records
from image_search.baseline.utils import write_jsonl


def make_csv(path, approvals):
    with path.open("w", encoding="utf-8-sig", newline="") as csv_file:
        writer = csv.DictWriter(csv_file, fieldnames=REQUIRED_COLUMNS)
        writer.writeheader()
        for approval in approvals:
            row = dict.fromkeys(REQUIRED_COLUMNS, "")
            row.update(
                entity_id="school-1", image_url="https://example.com/a.jpg", approve=approval
            )
            writer.writerow(row)


def test_exact_yes_filter_preserves_duplicate_urls_and_record_positions(tmp_path):
    source = tmp_path / "source.csv"
    make_csv(source, ["no", "yes", "YES", " yes ", "", "yes"])
    records = read_approved_records(source)
    assert [row["csv_record_number"] for row in records] == [2, 6]
    assert [row["record_id"] for row in records] == ["csv-2", "csv-6"]
    output = tmp_path / "output" / "records.jsonl"
    write_jsonl(output, records)
    assert [json.loads(line) for line in output.read_text().splitlines()] == records


def test_missing_columns_have_clear_error(tmp_path):
    source = tmp_path / "source.csv"
    source.write_text("approve\nyes\n", encoding="utf-8")
    with pytest.raises(ValueError, match="CSV thiếu cột:.*entity_id"):
        read_approved_records(source)


def test_empty_csv_with_headers_returns_no_records(tmp_path):
    source = tmp_path / "source.csv"
    make_csv(source, [])
    assert read_approved_records(source) == []


def test_approved_record_requires_entity_and_url(tmp_path):
    source = tmp_path / "source.csv"
    make_csv(source, ["yes"])
    source.write_text(source.read_text(encoding="utf-8-sig").replace("school-1", ""))
    with pytest.raises(ValueError, match="Record 1: thiếu entity_id hoặc image_url"):
        read_approved_records(source)


def test_malformed_record_is_reported(tmp_path):
    source = tmp_path / "source.csv"
    make_csv(source, [])
    with source.open("a") as stream:
        stream.write("not,enough,columns\n")
    with pytest.raises(ValueError, match="số cột không khớp"):
        read_approved_records(source)
