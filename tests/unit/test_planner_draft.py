"""Code suy ra route/dependency từ phân tích; không gọi model."""

from pathlib import Path

import pytest
from pydantic import ValidationError

from image_search.baseline.utils import read_jsonl
from image_search.modules.graph.query import strict_schema
from image_search.planner.draft import QueryDraft, compile_plan

CASES = Path(__file__).parents[1] / "fixtures/planner-scope-cases.jsonl"


def relation(kind="LOCATED_IN", name=None, entity=None):
    return {
        "relations": [kind],
        "direction": "out",
        "anchor_name": name,
        "anchor_entity_id": entity,
    }


def entity(mention, name=None, relations=(), id="e1", kind="place", match="all"):
    groups = [{"match": match, "relations": list(relations)}] if relations else []
    return {
        "id": id,
        "mention": mention,
        "proper_name": name,
        "kind": kind,
        "category": mention,
        "relation_groups": groups,
    }


def target(subject, entities=(), conditions=(), count=None, text=None):
    return {
        "image_subject": subject,
        "image_text": text or subject,
        "entities": list(entities),
        "conditions": [{"owner": o, "text": t} for o, t in conditions],
        "count": count,
    }


def build(*targets, query="", question=None):
    draft = QueryDraft.model_validate(
        {"targets": list(targets), "clarification_question": question}
    )
    return compile_plan(draft, query)


def test_unnamed_container_description_becomes_bridge_and_stays_out_of_target():
    plan = build(
        target(
            "phòng mổ",
            [entity("bệnh viện", relations=[relation(name="Huế")])],
            [("e1", "có cổng ốp gỗ")],
            count=2,
            text="phòng mổ của bệnh viện có cổng ốp gỗ",
        )
    )
    resolve, retrieve = plan.steps
    assert plan.query_type == "multi-hop"
    assert resolve.conditions == ["cổng ốp gỗ"] and resolve.count is None
    assert resolve.graph.conditions[0].anchor_name == "Huế"
    assert retrieve.depends_on == [resolve.id] and retrieve.count == 2
    assert retrieve.conditions == ["phòng mổ"]
    assert "cổng" not in retrieve.search_text and "Huế" in retrieve.search_text


def test_target_search_keeps_image_conditions_but_not_bridge_or_exclusions():
    plan = build(
        target(
            "khu vực thờ",
            [entity("nhà thờ", relations=[relation(name="Huế")])],
            [("image", "có tượng trắng"), ("image", "thay vì ảnh màu"), ("e1", "cổng sắt")],
        )
    )
    resolve, retrieve = plan.steps
    assert retrieve.search_text == "khu vực thờ tượng trắng nhà thờ Huế"
    assert resolve.search_text == "nhà thờ cổng sắt Huế"
    assert retrieve.identity_text is None


@pytest.mark.parametrize("text", ["có ảnh nào trong kho không?", "ảnh trong kho", "có hình không"])
def test_question_about_the_collection_is_not_a_description(text):
    plan = build(target("Phòng sữa", [entity("trại", "trại Xanh")], [("e1", text)]))
    assert plan.steps[0].identity_text is None
    assert plan.steps[0].conditions == ["Phòng sữa"]


@pytest.mark.parametrize("text", ["không có người", "có hình con gà", "ảnh trắng đen"])
def test_real_descriptions_are_not_dropped_as_filler(text):
    plan = build(target("Phòng sữa", [entity("trại", "trại Xanh")], [("image", text)]))
    assert len(plan.steps[0].conditions) == 2


def test_description_of_named_anchor_identifies_the_container():
    plan = build(
        target(
            "cổng soát vé",
            [
                entity("tuyến xe", "tuyến xe Số 1", id="e1"),
                entity("nhà ga", id="e2", relations=[relation(entity="e1")]),
            ],
            [("e1", "đoàn tàu xanh")],
        )
    )
    (step,) = plan.steps
    assert plan.query_type == "single"
    assert step.identity_text == "nhà ga tuyến xe Số 1 đoàn tàu xanh"


def test_image_owned_condition_stays_single_with_location_filter():
    plan = build(
        target(
            "đàn bò",
            [entity("trang trại", relations=[relation(name="Ba Vì")])],
            [("image", "bên tháp nước")],
        )
    )
    (step,) = plan.steps
    assert plan.query_type == "single"
    assert step.conditions == ["đàn bò", "bên tháp nước"]
    assert step.graph.conditions[0].anchor_name == "Ba Vì"


def test_named_container_never_creates_bridge_but_keeps_description():
    plan = build(target("sân hiên", [entity("quán", "quán Mộc")], [("e1", "biển hình lá")]))
    (step,) = plan.steps
    assert plan.query_type == "single"
    assert step.entity_mention == "quán Mộc"
    assert step.conditions == ["sân hiên"]
    assert step.identity_text == "quán Mộc biển hình lá"


@pytest.mark.parametrize("subject", ["hải đăng", "ảnh hải đăng", "toàn cảnh hải đăng"])
def test_description_of_requested_entity_itself_is_not_a_bridge(subject):
    plan = build(target(subject, [entity("hải đăng")], [("e1", "sọc đỏ")]))
    assert plan.query_type == "single"
    assert "sọc đỏ" in plan.steps[0].conditions


def test_inside_view_is_a_different_scene_from_the_entity():
    plan = build(target("bên trong cửa hàng", [entity("cửa hàng")], [("e1", "cổng đỏ")]))
    assert plan.query_type == "multi-hop"
    assert plan.steps[1].conditions == ["bên trong"]


@pytest.mark.parametrize("text", ["của trại ngựa", "ở trại ngựa ấy", "tại trại ngựa Huế"])
def test_condition_repeating_entity_or_anchor_adds_no_hop(text):
    container = entity("trại ngựa", relations=[relation(name="Huế")])
    plan = build(target("cổng gỗ", [container], [("e1", text)]))
    assert plan.query_type == "single"


def test_phrase_before_container_cannot_describe_it():
    query = "Ảnh người câu cá bên tháp canh đỏ ở khu cắm trại."
    item = target("người câu cá", [entity("khu cắm trại")], [("e1", "bên tháp canh đỏ")])
    assert build(item, query=query).query_type == "single"
    query = "Ảnh người câu cá ở khu cắm trại có tháp canh đỏ."
    item = target("người câu cá", [entity("khu cắm trại")], [("e1", "tháp canh đỏ")])
    assert build(item, query=query).query_type == "multi-hop"


def test_two_relations_need_resolution_and_groups_are_chained():
    item = entity(
        "cửa hàng",
        relations=[relation(name="Huế"), relation(name="Vinh")],
        match="any",
    )
    item["relation_groups"].append({"match": "all", "relations": [relation("BRANCH_OF", name="X")]})
    plan = build(target("kệ giày", [item]))
    first, second, last = plan.steps
    assert plan.query_type == "multi-hop"
    assert first.graph.match == "any"
    assert second.graph.within_step_id == first.id and second.depends_on == [first.id]
    assert last.depends_on == [second.id]


def test_described_anchor_is_resolved_before_its_child():
    plan = build(
        target(
            "kệ sách",
            [
                entity("tòa nhà", id="e1"),
                entity("hiệu sách", id="e2", relations=[relation(entity="e1")]),
            ],
            [("e1", "mái kính"), ("e2", "biển xanh")],
        )
    )
    anchor, shop, last = plan.steps
    assert shop.graph.conditions[0].anchor_step_id == anchor.id
    assert last.depends_on == [shop.id]


@pytest.mark.parametrize(
    "subject,detail", [("thuyền nan", "ngôi đình"), ("thuyền qua cửa hang", "cửa hang")]
)
def test_detail_of_description_or_subject_is_not_a_container(subject, detail):
    plan = build(
        target(
            subject,
            [
                entity("điểm du lịch", id="e1", relations=[relation(name="Huế")]),
                entity(detail, id="e2", relations=[relation(entity="e1")]),
            ],
            [("e1", "kayak cam trước ngôi đình")],
        )
    )
    resolve, retrieve = plan.steps
    assert resolve.conditions == ["kayak cam trước ngôi đình"]
    assert retrieve.depends_on == [resolve.id]


def test_nested_container_outside_the_description_is_kept():
    plan = build(
        target(
            "kệ sách",
            [
                entity("tòa nhà", id="e1"),
                entity("hiệu sách", id="e2", relations=[relation(entity="e1")]),
            ],
            [("e1", "mái kính")],
        )
    )
    assert len(plan.steps) == 3


def test_bare_place_anchor_is_used_as_name():
    plan = build(
        target(
            "kệ sách",
            [
                entity("quận 7", id="e1"),
                entity("hiệu sách", id="e2", relations=[relation(entity="e1")]),
            ],
            [("e2", "biển xanh")],
        )
    )
    assert plan.steps[0].graph.conditions[0].anchor_name == "quận 7"


def test_multi_target_keeps_dependency_inside_its_target():
    plan = build(
        target("bệnh viện An Bình", [entity("bệnh viện", "bệnh viện An Bình")], count=1),
        target("kho hạt", [entity("nhà máy")], [("e1", "ống khói ba màu")], count=2),
    )
    assert plan.query_type == "multi-target"
    assert [s.target_id for s in plan.steps] == ["t1", "t2", "t2"]


def test_clarification_and_invalid_drafts():
    assert build(question="Ảnh nào?").query_type == "unclear"
    with pytest.raises(ValueError):
        build()
    with pytest.raises(ValueError, match="làm rõ"):
        build(target("cổng"), question="Ảnh nào?")
    with pytest.raises(ValueError, match="khai báo"):
        build(target("cổng", [], [("e1", "đỏ")]))
    with pytest.raises(ValueError, match="không phục vụ"):
        build(target("cổng", [entity("a", id="e1"), entity("b", id="e2")]))
    with pytest.raises(ValidationError):
        build(target("cổng", [entity("a", id=" ")]))


def test_model_schema_has_no_route_or_dependency_fields():
    text = str(strict_schema(QueryDraft))
    assert "query_type" not in text and "depends_on" not in text


def test_scope_fixture_pairs_are_contrastive_and_do_not_cross_split():
    rows = read_jsonl(CASES)
    pairs = {}
    for row in rows:
        pairs.setdefault(row["intent_id"], []).append(row)
    assert len(rows) == 32 and len(pairs) == 16
    for pair in pairs.values():
        assert {r["type"] for r in pair} == {"multi-hop", "single"}
        assert len({r["split"] for r in pair}) == 1
    for row in rows:
        if row["type"] == "multi-hop":
            assert row["bridge"] in row["text"] and row["target"] in row["text"]
