"""Strict triples contract and stable content identities."""

import hashlib
import json
import re
import unicodedata

from pydantic import BaseModel, ConfigDict, field_validator, model_validator


def digest(value):
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, ensure_ascii=False).encode()
    ).hexdigest()


def name_key(name):
    return " ".join(unicodedata.normalize("NFC", name).casefold().split())


class RecordTriples(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    record_id: str
    triples: list[list[str]]

    @field_validator("triples")
    @classmethod
    def valid_triples(cls, triples):
        seen = set()
        for triple in triples:
            if len(triple) != 3 or any(not x.strip() for x in triple):
                raise ValueError("Triple cần đúng ba chuỗi không rỗng")
            a, relation, b = triple
            if not re.fullmatch(r"[A-Z][A-Z0-9]*(?:_[A-Z0-9]+)*", relation):
                raise ValueError("Relationship phải UPPER_SNAKE_CASE")
            key = (name_key(a), relation, name_key(b))
            if key[0] == key[2] or key in seen:
                raise ValueError("Self-loop hoặc triple trùng")
            seen.add(key)
        return triples


class Extraction(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    records: list[RecordTriples]

    @model_validator(mode="after")
    def unique_records(self):
        ids = [r.record_id for r in self.records]
        if len(ids) != len(set(ids)):
            raise ValueError("record_id trùng")
        return self

    def check_input(self, group):
        if {r.record_id for r in self.records} != {r["record_id"] for r in group["records"]}:
            raise ValueError("Output thiếu/thừa record_id")
        return self


def output_schema():
    # Keep the provider schema simple; semantic constraints are checked locally.
    return {
        "type": "object",
        "properties": {
            "records": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "record_id": {"type": "string"},
                        "triples": {
                            "type": "array",
                            "items": {
                                "type": "array",
                                "items": {"type": "string"},
                                "minItems": 3,
                                "maxItems": 3,
                            },
                        },
                    },
                    "required": ["record_id", "triples"],
                    "additionalProperties": False,
                },
            }
        },
        "required": ["records"],
        "additionalProperties": False,
    }
