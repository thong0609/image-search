"""Conservative local draft parser. Unsupported grammar always goes to the LLM."""

import re
import unicodedata
from collections import defaultdict
from dataclasses import dataclass

from image_search.adapters.qdrant.metadata import name_key
from image_search.planner.draft import QueryDraft, compile_plan
from image_search.planner.schemas import QueryPlan

VERSION = "heuristic-v1"
PREFIX = re.compile(
    r"^(?:(?:bạn\s+)?(?:hãy\s+)?(?:tìm|cho|lấy)(?:\s+giúp)?"
    r"(?:\s+(?:cho\s+)?(?:tôi|mình))?(?:\s+xem)?\s+)?"
    r"(?:(?P<count>[1-9]\d?)\s+)?(?:hình ảnh|ảnh|hình)(?:\s+(?:về|của))?\s+",
    re.I,
)

VIEWS = ("bên trong", "bên ngoài", "mặt tiền", "toàn cảnh", "cổng")
# Explicit small visual vocabulary: unknown words cannot silently become a single intent.
SUBJECTS = ("sân bóng", "sân vận động", "tòa nhà", "công viên", "hồ nước", "bãi xe")
ATTRIBUTES = (
    "có mái che",
    "mái đỏ",
    "màu đỏ",
    "màu trắng",
    "màu xanh",
    "cao tầng",
    "ban đêm",
)
UNSAFE = re.compile(
    r"\b(không|đừng|trừ|thay vì|ngoại trừ|hoặc|hay|gần|cách|cùng|nằm|thuộc|"
    r"vừa rồi|trước đó|thứ hai|giống|nhất)\b",
    re.I,
)


def clean(text):
    return " ".join(unicodedata.normalize("NFC", text).strip().split()).rstrip(".!?")


@dataclass(frozen=True)
class Decision:
    plan: QueryPlan | None
    reason: str
    version: str = VERSION

    def metadata(self):
        return {
            "route": "heuristic" if self.plan else "llm",
            "reason": self.reason,
            "version": self.version,
        }


class HeuristicPlanner:
    def __init__(self, entities=()):
        # Only graph-supported names/aliases. Ambiguous name keys are excluded.
        owners = defaultdict(set)
        for entity in entities:
            for alias in (entity["name"], *entity.get("aliases", [])):
                owners[name_key(alias)].add(entity["entity_id"])
        self.names = {key for key, ids in owners.items() if len(ids) == 1 and key}

    def named(self, text):
        return name_key(text) in self.names

    def target(self, text):
        text = clean(text)
        prefix = PREFIX.match(text)
        count = int(prefix["count"]) if prefix and prefix["count"] else None
        text = PREFIX.sub("", text, count=1)
        subject, name = text, None
        if self.named(text):
            name = text
        else:
            for view in VIEWS:
                match = re.fullmatch(rf"{view}\s+(?:(?:của|ở|tại)\s+)?(.+)", text, re.I)
                if match and self.named(match[1]):
                    subject, name = view, match[1]
                    break
        if name is None:
            # No open-ended residual text, implicit place or relation accepted here.
            pattern = "(?:" + "|".join(SUBJECTS) + ")(?: (?:" + "|".join(ATTRIBUTES) + "))?"
            if not re.fullmatch(pattern, text, re.I):
                return None
        return {
            "image_subject": subject,
            "image_text": text,
            "entities": []
            if name is None
            else [
                {
                    "id": "e1",
                    "mention": name,
                    "proper_name": name,
                    "kind": None,
                    "category": None,
                    "relation_groups": [],
                }
            ],
            "conditions": [],
            "count": count,
        }

    def decide(self, query):
        text = clean(query)
        if not text:
            return Decision(None, "empty_query")
        prefix = PREFIX.match(text)
        count = int(prefix["count"]) if prefix and prefix["count"] else None
        text = PREFIX.sub("", text, count=1)
        # Match the complete known name first: conjunctions can be part of names.
        if self.named(text):
            targets, reason = [self.target(text)], "exact_name"
        else:
            if UNSAFE.search(text):
                return Decision(None, "unsupported_relation_negation_or_reference")
            target = self.target(text)
            if target:
                targets, reason = [target], "direct_target"
            else:
                # Two views sharing one explicit name; no general coordination guessing.
                views = "(?:" + "|".join(VIEWS) + ")"
                match = re.fullmatch(
                    rf"({views}) và ({views})\s+(?:(?:của|ở|tại)\s+)?(.+)", text, re.I
                )
                if match and self.named(match[3]):
                    targets = [self.target(f"{match[i]} {match[3]}") for i in (1, 2)]
                    reason = "shared_named_scope"
                else:
                    parts = re.split(r"\s+và\s+", text, flags=re.I)
                    targets = [self.target(part) for part in parts]
                    if not 2 <= len(parts) <= 5 or any(t is None for t in targets):
                        return Decision(None, "unsupported_grammar_or_unknown_name")
                    reason = "explicit_targets"
        targets[0]["count"] = count
        draft = QueryDraft.model_validate({"targets": targets, "clarification_question": None})
        return Decision(compile_plan(draft, query), reason)
