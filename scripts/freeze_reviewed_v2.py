"""Chốt tập tham chiếu đã duyệt ảnh, không nâng cả draft thành gold độc lập."""

import copy
from collections import Counter, defaultdict
from pathlib import Path

from image_search.baseline.utils import file_hash, read_json, read_jsonl, write_json, write_jsonl

SOURCE = Path("var/benchmark-v2")
DEST = Path("var/benchmark-v2-reviewed")
# Chỉ số trong visual-items.json; quyết định được ghi trước khi chạy retrieval.
ACCEPTED = {
    1,
    2,
    3,
    5,
    6,
    7,
    8,
    10,
    11,
    12,
    15,
    16,
    19,
    20,
    21,
    22,
    23,
    24,
    26,
    28,
    29,
    30,
    31,
    36,
    37,
    40,
    41,
    42,
    43,
    44,
    45,
    46,
    48,
    49,
    56,
    59,
    60,
    61,
    62,
    64,
    67,
    68,
    69,
}
REJECTED = {
    0: "Ảnh chụp mặt tiền, không đáp ứng yêu cầu ảnh phía trong.",
    4: "Ảnh mặt tiền; không thấy rõ khu trưng bày.",
    9: "Không phân biệt chắc chắn hoàng hôn với bình minh từ ảnh.",
    13: "Chưa đủ bằng chứng xác định đúng bến suối Yến từ khung cảnh.",
    14: "Đường tàu qua phố; không đủ bằng chứng nằm tại ga Hà Nội.",
    17: "Chưa xác nhận rõ tượng và vị trí cụ thể trong quần thể.",
    18: "Có đèn lồng nhưng chưa xác nhận ánh đèn đang sáng.",
    25: "Ảnh nhìn xa, không xác nhận đủ rõ máy bay.",
    27: "Ảnh máy bay nhìn thẳng từ trên; chưa xác nhận được sân bay Vinh.",
    32: "Dấu hiệu ảnh ghép máy bay trên bầu trời; cần xác minh nguồn.",
    33: "Ảnh khu mộ ngoài trời, không phải bàn thờ phía trong.",
    34: "Cảnh khu nhà gần hoàn thiện; chưa xác nhận đang thi công.",
    35: "Ảnh mặt tiền đường phố, điều kiện cận cảnh chi tiết chưa rõ.",
    38: "Ảnh khu nghỉ dưỡng có bể bơi; nguồn gán căn cứ Khe Sanh cần xác minh.",
    39: "Công trình trang trí hình vòm; chưa chứng minh là cổng.",
    47: "Không đủ rõ điều kiện nhiều cây xanh tại địa điểm.",
    57: "Ảnh ghép; chưa xác minh tượng thuộc tháp chuông được hỏi.",
    58: "Không thấy rõ tượng trong ảnh toàn cảnh.",
    63: "Bàn thờ ngoài trời, không khớp yêu cầu bên trong.",
    65: "Ảnh đường hầm; chưa chứng minh là ga Bến Thành đang thi công.",
    66: "Chưa rõ chi tiết cận cảnh mà người hỏi muốn tìm.",
}
for index in range(50, 56):
    REJECTED[index] = (
        "Ảnh có đường ray nhưng có thể thuộc ga khác trên tuyến; cần xác minh ga Cát Linh."
    )


def main():
    if (DEST / "manifest.json").exists():
        raise SystemExit("Tập đã chốt; dùng phiên bản mới nếu sửa nhãn.")
    items = read_json("var/gold-review-v2/visual-items.json")
    assert ACCEPTED | REJECTED.keys() == set(range(len(items)))
    assert not ACCEPTED & REJECTED.keys()
    source_queries = read_jsonl(SOURCE / "queries.jsonl")
    source_answers = {a["query_id"]: a for a in read_jsonl(SOURCE / "answers.jsonl")}
    positive = defaultdict(list)
    decisions = []
    for index, item in enumerate(items):
        accepted = index in ACCEPTED
        decisions.append(
            {
                **item,
                "accepted": accepted,
                "reviewer": "assistant_visual_review",
                "reason": "Điều kiện thị giác nhìn thấy; danh tính theo metadata nguồn."
                if accepted
                else REJECTED[index],
            }
        )
        if accepted:
            positive[item["query_id"]].append(item["image_id"])
    queries, answers = [], []
    for q in source_queries:
        if q["query_id"] not in positive:
            continue
        q = copy.deepcopy(q)
        a = copy.deepcopy(source_answers[q["query_id"]])
        q.update(reviewed=True, evaluation_ready=True, review_level="assistant_visual_only")
        q["evaluation_suite"] = "reviewed_visual"
        a["targets"] = [{"image_ids": sorted(set(positive[q["query_id"]])), "required": 1}]
        a["verification"] = (
            "Đã xem ảnh; điều kiện thị giác phù hợp. Địa điểm dựa metadata chưa độc lập."
        )
        a["label_basis"] = "assistant_visual_review_with_source_identity"
        a["exhaustive"] = False
        a.pop("known_recall_at_10_ceiling", None)
        queries.append(q)
        answers.append(a)
    # Bài multi-target ghép các yêu cầu đã duyệt, cùng split, khác entity/ảnh.
    # Báo riêng; không coi các câu ghép là intent độc lập với các câu thành phần.
    for split in ("dev", "test"):
        bases = [
            (q, a)
            for q, a in zip(queries, answers, strict=True)
            if q["type"] == "single" and q["split"] == split
        ]
        for number in range(min(6, len(bases) // 2)):
            (left, la), (right, ra) = bases[2 * number : 2 * number + 2]
            if set(la["targets"][0]["image_ids"]) & set(ra["targets"][0]["image_ids"]):
                continue
            qid = f"reviewed-{split}-multi-{number + 1:02d}"
            query = dict(
                copy.deepcopy(left),
                query_id=qid,
                type="multi-target",
                text="Mỗi yêu cầu sau lấy một ảnh: " + left["text"] + " " + right["text"],
                intent_id=qid,
                origin="composed_from_reviewed_queries",
                category="reviewed_composition",
                component_query_ids=[left["query_id"], right["query_id"]],
            )
            answer = {
                "query_id": qid,
                "targets": copy.deepcopy(la["targets"] + ra["targets"]),
                "evidence": [],
                "exhaustive": False,
                "verification": "Ghép hai yêu cầu đã duyệt ảnh, giữ nguyên nhãn thành phần.",
            }
            queries.append(query)
            answers.append(answer)
    DEST.mkdir(exist_ok=True)
    write_jsonl(DEST / "queries.jsonl", queries)
    write_jsonl(DEST / "answers.jsonl", answers)
    write_jsonl(DEST / "visual-decisions.jsonl", decisions)
    write_jsonl(
        DEST / "excluded-queries.jsonl",
        [
            {
                "query_id": q["query_id"],
                "reason": "Chưa có đủ nhãn thị giác được duyệt cho tập này.",
            }
            for q in source_queries
            if q["query_id"] not in positive
        ],
    )
    manifest = {
        "version": "reviewed-reference-v2",
        "quality_tier": "assistant_reviewed_known_positives_not_independent_gold",
        "independent_review": False,
        "identity_independently_verified": False,
        "exhaustive_labels": False,
        "corpus_previously_seen": True,
        "source_manifest": "var/benchmark-v1/benchmark.json",
        "source_manifest_sha256": file_hash("var/benchmark-v1/benchmark.json"),
        "source_queries_sha256": file_hash(SOURCE / "queries.jsonl"),
        "source_answers_sha256": file_hash(SOURCE / "answers.jsonl"),
        "review_items_sha256": file_hash("var/gold-review-v2/visual-items.json"),
        "files": {
            name: {"path": str((DEST / name).resolve()), "sha256": file_hash(DEST / name)}
            for name in (
                "queries.jsonl",
                "answers.jsonl",
                "visual-decisions.jsonl",
                "excluded-queries.jsonl",
            )
        },
        "counts": dict(Counter(f"{q['split']}/{q['type']}" for q in queries)),
        "evaluation": {
            "methods": ["vector", "keyword", "hybrid"],
            "rrf_k": 60,
            "candidates": 100,
            "weights": [1, 1],
            "rounds": 3,
            "seed": 42,
            "top_k": 10,
            "threads": 4,
            "parameter_tuning": False,
            "report_types_separately": True,
            "precision_enabled": False,
        },
        "limitations": [
            "Không phải gold độc lập; danh tính địa điểm còn dựa nguồn CSV.",
            "Chỉ chấm known positives; không coi unjudged là nhãn âm đã xác nhận.",
            "Chưa kiểm chứng bridge nên không chấm multi-hop hoặc suy luận.",
            "Multi-target ghép từ single; báo riêng, không lấy tổng làm mẫu độc lập.",
            "Chưa đo từ chối; không có câu âm đã duyệt thị giác.",
            "Câu tổng hợp từ metadata, có thể thiên về BM25.",
        ],
    }
    write_json(DEST / "manifest.json", manifest)
    print(manifest["counts"])


if __name__ == "__main__":
    main()
