"""Bản phân tích do model điền; code suy ra bước, dependency và query_type từ đó."""

import re
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from image_search.graph.query import GraphCondition, GraphQuery
from image_search.planner.schemas import QueryPlan, Step

IMAGE = "image"
EntityId = Literal["e1", "e2", "e3", "e4"]
# Từ nối/chỉ định: cụm chỉ gồm các từ này và tên entity thì không thêm đặc điểm nào.
LINK_WORDS = set(
    "của trong ở tại thuộc bên ngoài nằm từ cái khu nơi có cùng một các những ấy đó này kia".split()
)
# 'bên trong X' là một cảnh khác của X; 'toàn cảnh X' vẫn là chính X.
SAME_VIEW_WORDS = (LINK_WORDS - {"trong"}) | set("ảnh hình bức tấm toàn cận cảnh về".split())
# Câu hỏi về kho ảnh không mô tả gì; không được dùng để nhận diện nơi chứa.
FILLER = re.compile(
    r"^(có\s+)?(tấm\s+|bức\s+)?(ảnh|hình)?(\s*nào)?(\s*trong kho)?(\s*không)?\W*$", re.IGNORECASE
)
EXCLUSION = re.compile(r"(thay vì|thay cho|không|trừ|đừng)\b", re.IGNORECASE)
EDGE_WORDS = r"(?:của|ở|tại|thuộc|về)"


class Draft(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True, strict=True)


class DraftRelation(Draft):
    relations: list[Literal["LOCATED_IN", "PART_OF", "BRANCH_OF"]] = Field(
        min_length=1, max_length=3
    )
    direction: Literal["out", "in"]
    anchor_name: str | None
    anchor_entity_id: EntityId | None


class DraftRelationGroup(Draft):
    match: Literal["all", "any"]
    relations: list[DraftRelation] = Field(min_length=1, max_length=8)


class DraftEntity(Draft):
    id: EntityId
    mention: str = Field(min_length=1)
    proper_name: str | None
    kind: Literal["place", "part", "brand", "area", "event", "route", "other"] | None
    category: str | None
    relation_groups: list[DraftRelationGroup] = Field(max_length=3)


class DraftCondition(Draft):
    text: str = Field(min_length=1)
    owner: Literal["image"] | EntityId


class DraftTarget(Draft):
    image_subject: str = Field(min_length=1)
    image_text: str = Field(min_length=1)
    entities: list[DraftEntity] = Field(max_length=4)
    conditions: list[DraftCondition] = Field(max_length=16)
    count: int | None = Field(ge=1, le=100)


class QueryDraft(Draft):
    targets: list[DraftTarget] = Field(max_length=5)
    clarification_question: str | None


def words(text):
    return set(re.findall(r"\w+", (text or "").casefold()))


def only_names(text, entity, extra):
    """Cụm chỉ nhắc lại entity hoặc anchor đã mã hóa."""
    known = extra | words(entity.mention) | words(entity.proper_name)
    for group in entity.relation_groups:
        for item in group.relations:
            known |= words(item.anchor_name)
    return words(text) <= known


def strip_name(text, entity):
    """'mặt tiền cửa hàng Q' -> 'mặt tiền'; tên đã nằm ở entity_mention."""
    if entity is None:
        return text
    for name in (entity.proper_name, entity.mention):
        if name:
            text = re.sub(rf"(?<!\w){re.escape(name)}(?!\w)", " ", text, flags=re.IGNORECASE)
    text = " ".join(text.split())
    return re.sub(rf"\s+{EDGE_WORDS}$|^{EDGE_WORDS}\s+", "", text, flags=re.IGNORECASE)


def anchor_names(entity):
    return [i.anchor_name for g in entity.relation_groups for i in g.relations if i.anchor_name]


def bridge_search_text(subject, conditions, entity):
    """Giữ mọi điều kiện ảnh đích; đặc điểm nhận diện và điều kiện loại trừ không đưa vào."""
    places = anchor_names(entity)
    wanted = [c for c in conditions if not EXCLUSION.match(c)]
    text = subject
    for part in (*wanted, entity.mention, *places):
        if part.casefold() not in text.casefold():
            text += " " + part
    return text


def full_name(name, query):
    """Bù phần ngoặc ngay sau tên nếu model cắt mất; tên trong kho có cả phần này."""
    match = re.search(re.escape(name) + r"\s*\([^()]*\)", query, flags=re.IGNORECASE)
    return match.group(0) if match else name


def precedes_entity(text, entity, query):
    """Bổ ngữ tiếng Việt đứng sau danh từ: cụm đứng trước nơi chứa không thể mô tả nơi đó."""
    query = query.casefold()
    start, place = query.find(text.casefold()), query.find(entity.mention.casefold())
    return 0 <= start < place and start + len(text) <= place


def graph_query(entity, group, resolved, within):
    conditions = []
    for item in group.relations if group else ():
        anchor, step_id = item.anchor_name, None
        if item.anchor_entity_id is not None:
            if anchor is not None or item.anchor_entity_id not in resolved:
                raise ValueError("Anchor phải là đúng một tên hoặc entity đứng trước")
            anchor, step_id = resolved[item.anchor_entity_id]
        conditions.append(
            GraphCondition(
                relations=item.relations,
                direction=item.direction,
                anchor_name=anchor,
                anchor_step_id=step_id,
            )
        )
    return GraphQuery(
        within_step_id=within,
        target_name=None,
        target_kind=entity.kind,
        target_category=entity.category,
        match=group.match if group else "all",
        conditions=conditions,
    )


def direct_relation(entity, resolved):
    """Một quan hệ trực tiếp với anchor có tên chỉ là bộ lọc của bước trả ảnh."""
    if len(entity.relation_groups) != 1:
        return False
    items = entity.relation_groups[0].relations
    if len(items) != 1 or len(items[0].relations) != 1:
        return False
    name, _ = resolved.get(items[0].anchor_entity_id, (items[0].anchor_name, None))
    return name is not None


def without_detail_entity(target):
    """Bỏ 'nơi chứa' thừa: chi tiết của mô tả hoặc của ảnh đích, gắn vào một nơi chưa có tên."""
    *rest, last = target.entities or [None]
    if not rest or last.proper_name or rest[-1].proper_name:
        return target
    if any(c.owner == last.id for c in target.conditions):
        return target
    linked = {i.anchor_entity_id for g in last.relation_groups for i in g.relations}
    described = [c.text for c in target.conditions if c.owner == rest[-1].id]
    if linked != {rest[-1].id} or not described:
        return target
    mention = last.mention.casefold()
    if any(mention in text.casefold() for text in (target.image_subject, *described)):
        return target.model_copy(update={"entities": rest})
    return target


def compile_target(target, target_id, steps, query):
    target = without_detail_entity(target)
    owned = {entity.id: [] for entity in target.entities}
    by_id = {entity.id: entity for entity in target.entities}
    if len(owned) != len(target.entities):
        raise ValueError("ID entity bị trùng")
    last = target.entities[-1] if target.entities else None
    # Ảnh đích chính là entity thì mọi mô tả của nó là điều kiện ảnh, không phải bridge.
    same = last is not None and only_names(target.image_subject, last, SAME_VIEW_WORDS)
    subject = strip_name(target.image_subject, last)
    image_conditions = [subject] if words(subject) - LINK_WORDS or "trong" in words(subject) else []
    for condition in target.conditions:
        text = re.sub(r"^có\s+", "", condition.text, flags=re.IGNORECASE)
        if condition.owner != IMAGE and condition.owner not in owned:
            raise ValueError("Điều kiện không thuộc ảnh đích hoặc entity đã khai báo")
        if FILLER.match(text):
            continue
        if condition.owner == IMAGE or precedes_entity(text, by_id[condition.owner], query):
            image_conditions.append(text)
        elif not only_names(text, by_id[condition.owner], LINK_WORDS):
            own = same and condition.owner == last.id
            (image_conditions if own else owned[condition.owner]).append(text)
    # Entity cuối là nơi chứa ảnh đích; entity trước đó phải là anchor của entity sau.
    used = {
        item.anchor_entity_id
        for entity in target.entities
        for group in entity.relation_groups
        for item in group.relations
    }
    if any(entity.id not in used for entity in target.entities[:-1]):
        raise ValueError("Có entity không phục vụ ảnh đích")

    def add(**values):
        steps.append(
            Step(id=f"s{len(steps) + 1}", target_id=target_id, action="resolve_entity", **values)
        )
        return steps[-1].id

    resolved, mention, graph, parent, identity = {}, None, None, None, []
    for entity in target.entities:
        final_entity = entity is last
        visual, groups = owned[entity.id], entity.relation_groups
        if entity.proper_name:
            # Tên đã đủ định danh; giữ mô tả đi kèm làm điều kiện mềm, không tạo bridge.
            name = full_name(entity.proper_name, query)
            resolved[entity.id] = (name, None)
            if final_entity:
                mention = name
            # Tên đã định danh nên không tạo bridge; mô tả giữ lại phòng khi graph không có tên.
            if visual:
                identity += ([] if final_entity else [last.mention]) + [name, *visual]
            continue
        if final_entity and entity.kind == "part" and direct_relation(entity, resolved):
            image_conditions += visual  # Bộ phận của nơi đã có tên chính là thứ cần thấy.
            visual = []
        if final_entity and not visual and (not groups or direct_relation(entity, resolved)):
            graph = graph_query(entity, groups[0], resolved, None) if groups else None
            continue
        if not visual and not groups:
            # Anchor trần như 'quận 7': chính cụm nhắc tới là tên để tra graph.
            resolved[entity.id] = (entity.mention, None)
            continue
        step_id = None
        for group in groups or [None]:
            query = graph_query(entity, group, resolved, step_id) if group else None
            anchors = {c.anchor_step_id for c in query.conditions} if query else set()
            final = group is None or group is groups[-1]
            step_id = add(
                search_text=" ".join([entity.mention, *visual, *anchor_names(entity)]),
                entity_mention=None,
                conditions=visual if final else [],
                count=None,
                depends_on=sorted((anchors | {step_id}) - {None}),
                graph=query,
            )
        resolved[entity.id] = (None, step_id)
        if final_entity:
            parent = step_id
    steps.append(
        Step(
            id=f"s{len(steps) + 1}",
            target_id=target_id,
            action="retrieve_images",
            search_text=bridge_search_text(target.image_subject, image_conditions, last)
            if parent
            else target.image_text,
            entity_mention=mention,
            conditions=list(dict.fromkeys(image_conditions)),
            count=target.count,
            depends_on=[parent] if parent else [],
            graph=graph,
            identity_text=" ".join(identity) if identity and not parent else None,
        )
    )


def compile_plan(draft, text):
    """Không nhận query_type/dependency từ model, nên hai phần không thể mâu thuẫn."""
    if draft.clarification_question:
        if draft.targets:
            raise ValueError("Không lập mục tiêu khi còn cần làm rõ")
        return QueryPlan(
            query_type="unclear",
            needs_clarification=True,
            clarification_question=draft.clarification_question,
            steps=[],
        )
    steps = []
    for number, target in enumerate(draft.targets, 1):
        compile_target(target, f"t{number}", steps, text)
    hop = any(step.depends_on for step in steps)
    kind = "multi-target" if len(draft.targets) > 1 else "multi-hop" if hop else "single"
    return QueryPlan(
        query_type=kind, needs_clarification=False, clarification_question=None, steps=steps
    )
