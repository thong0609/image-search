"""Điều kiện graph có cấu trúc; không nhận Cypher từ model."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class GraphCondition(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    relations: list[Literal["LOCATED_IN", "PART_OF", "BRANCH_OF"]] = Field(
        min_length=1, max_length=3
    )
    direction: Literal["out", "in"]
    anchor_name: str | None
    anchor_step_id: str | None

    @model_validator(mode="after")
    def one_anchor(self):
        if bool(self.anchor_name and self.anchor_name.strip()) == bool(self.anchor_step_id):
            raise ValueError("Cần đúng một anchor_name hoặc anchor_step_id")
        return self


class GraphQuery(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    within_step_id: str | None = None
    target_name: str | None
    target_kind: Literal["place", "part", "brand", "area", "event", "route", "other"] | None
    target_category: str | None
    match: Literal["all", "any"]
    conditions: list[GraphCondition] = Field(max_length=8)

    @model_validator(mode="after")
    def bounded_query(self):
        if not self.conditions and not self.target_name and not self.within_step_id:
            raise ValueError("Cần tên đích hoặc ít nhất một điều kiện quan hệ")
        for text in (self.target_name, self.target_category):
            if text is not None and not text.strip():
                raise ValueError("Tên/category không được rỗng")
        return self


def strict_schema(model):
    """API bắt buộc mọi property; local vẫn đọc được plan v2 thiếu graph=null."""
    schema = model.model_json_schema()

    def visit(value):
        if isinstance(value, dict):
            value.pop("default", None)
            if value.get("type") == "object":
                value["required"] = list(value["properties"])
                value["additionalProperties"] = False
            for child in value.values():
                visit(child)
        elif isinstance(value, list):
            for child in value:
                visit(child)

    visit(schema)
    return schema
