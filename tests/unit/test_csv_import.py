import csv
import io

import pytest

from image_search.baseline.records import REQUIRED_COLUMNS
from image_search.ingestion.csv_input import parse_csv


def document(rows):
    stream = io.StringIO()
    writer = csv.DictWriter(stream, fieldnames=REQUIRED_COLUMNS)
    writer.writeheader()
    writer.writerows([{k: row.get(k, "") for k in REQUIRED_COLUMNS} for row in rows])
    return stream.getvalue().encode("utf-8-sig")


def row(**values):
    return {
        "entity_id": "A",
        "entity_name": "Chợ A",
        "image_url": "https://example.com/a.jpg",
        "approve": "yes",
        **values,
    }


def test_csv_preserves_invalid_rows_and_skips_unapproved_and_duplicates():
    result = parse_csv(
        document(
            [
                row(),
                row(),
                row(approve="no"),
                row(entity_id=""),
                row(image_height="-1"),
                row(mo_ta="different"),
            ]
        )
    )
    assert [r["status"] for r in result] == [
        "pending",
        "skipped",
        "skipped",
        "failed",
        "failed",
        "failed",
    ]
    assert [r["line"] for r in result] == list(range(1, 7))


@pytest.mark.parametrize("data", [b"a,b\n1,2", b"\xff", b""])
def test_invalid_csv_rejected(data):
    with pytest.raises(ValueError):
        parse_csv(data)
