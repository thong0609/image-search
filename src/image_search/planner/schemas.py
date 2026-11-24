"""Kế hoạch có mục tiêu và các bước phụ thuộc, không chứa đáp án ảnh."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from image_search.graph.query import GraphQuery


class Step(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True, strict=True)

    id: str = Field(min_length=1)
    target_id: str = Field(min_length=1)
    action: Literal["resolve_entity", "retrieve_images"]
    search_text: str = Field(min_length=1)
    entity_mention: str | None
    conditions: list[str]
    count: int | None = Field(ge=1, le=100)
    depends_on: list[str]
    graph: GraphQuery | None = None
    # Tên kèm mô tả nhận diện; chỉ dùng khi tên không có trong graph, không lọc ảnh đích.
    identity_text: str | None = Field(default=None, min_length=1)


class QueryPlan(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True, strict=True)

    query_type: Literal["single", "multi-target", "multi-hop", "unclear"]
    needs_clarification: bool
    clarification_question: str | None
    steps: list[Step] = Field(max_length=12)

    @model_validator(mode="after")
    def check_steps(self):
        if self.needs_clarification:
            if not self.clarification_question or not self.clarification_question.strip():
                raise ValueError("Cần câu hỏi làm rõ")
            if self.steps:
                raise ValueError("Không thực thi kế hoạch khi còn cần làm rõ")
            return self
        if self.query_type == "unclear" or self.clarification_question is not None:
            raise ValueError("Trạng thái làm rõ không nhất quán")
        seen = {}
        final = {}
        for step in self.steps:
            if step.id in seen:
                raise ValueError("ID bước bị trùng")
            if len(step.depends_on) != len(set(step.depends_on)):
                raise ValueError("Dependency bị trùng")
            for parent in step.depends_on:
                if parent not in seen or seen[parent].target_id != step.target_id:
                    raise ValueError("Dependency phải trỏ bước trước đó trong cùng mục tiêu")
            if step.graph is not None:
                anchors = {c.anchor_step_id for c in step.graph.conditions if c.anchor_step_id}
                if step.graph.within_step_id:
                    anchors.add(step.graph.within_step_id)
                if anchors != set(step.depends_on):
                    raise ValueError("Graph phải dùng đủ dependencies làm anchor")
                for parent in anchors:
                    if parent and (
                        parent not in step.depends_on or seen[parent].action != "resolve_entity"
                    ):
                        raise ValueError("Graph anchor phải là resolve_entity dependency")
            if step.entity_mention is not None and not step.entity_mention.strip():
                raise ValueError("Entity mention không được rỗng")
            if any(not condition.strip() for condition in step.conditions):
                raise ValueError("Điều kiện không được rỗng")
            if step.action == "resolve_entity":
                if step.identity_text is not None:
                    raise ValueError("identity_text chỉ thuộc bước trả ảnh")
                if step.count is not None:
                    raise ValueError("Bước xác định entity không yêu cầu số ảnh")
            else:
                if step.target_id in final:
                    raise ValueError("Mỗi mục tiêu chỉ có một bước trả ảnh")
                final[step.target_id] = step
            seen[step.id] = step
        if not 1 <= len(final) <= 5:
            raise ValueError("Cần từ 1 đến 5 mục tiêu trả ảnh")
        needed = set(final_step.id for final_step in final.values())
        for step in reversed(self.steps):
            if step.id in needed:
                needed.update(step.depends_on)
        if needed != set(seen):
            raise ValueError("Có bước không phục vụ mục tiêu cuối")
        has_dependency = any(step.depends_on for step in self.steps)
        expected = "multi-target" if len(final) > 1 else "multi-hop" if has_dependency else "single"
        if self.query_type != expected:
            raise ValueError("Loại truy vấn không khớp mục tiêu/dependency")
        return self
