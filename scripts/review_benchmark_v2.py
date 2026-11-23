# ruff: noqa: E501
# HTML templates keep long lines for readability.
"""Trang đọc bộ query và ảnh ứng viên; không tự ghi nhận nhãn đã duyệt."""

import html
import json
from collections import defaultdict
from pathlib import Path

from image_search.baseline.benchmark import validate_benchmark
from image_search.baseline.utils import file_hash, read_json, read_jsonl, write_json, write_jsonl

root = Path("var/benchmark-v2")
queries = read_jsonl(root / "queries.jsonl")
answers = read_jsonl(root / "answers.jsonl")
coverage = read_json(root / "coverage.json")
rows = [
    r
    for r in read_jsonl(root / "downloaded-records.jsonl")
    if r.get("download_status") == "success"
]
by_record = {r["record_id"]: r for r in rows}
by_image = {r["image_id"]: r for r in rows}
image_records = defaultdict(list)
for row in rows:
    image_records[row["image_id"]].append(row)
by_family = defaultdict(list)
for q in queries:
    by_family[q["intent_id"]].append(q["query_id"])


def esc(value):
    return html.escape(str(value), quote=True)


def image_card(iid):
    r = by_image[iid]
    url = esc(Path(r["local_path"]).resolve().as_uri())
    labels = "<hr>".join(
        esc(row["record_id"] + " · " + row["entity_name"] + " · " + row["mo_ta"])
        for row in image_records[iid]
    )
    return f'<figure><a href="{url}"><img loading="lazy" src="{url}" alt="Ảnh ứng viên"></a><figcaption>{labels}<br><code>{iid}</code></figcaption></figure>'


sections = []
queue = []
for q, a in zip(queries, answers, strict=True):
    assert q["query_id"] == a["query_id"]
    cards = []
    for i, t in enumerate(a["targets"], 1):
        ids = t["image_ids"]
        previews = "".join(image_card(iid) for iid in ids[:3])
        more = ""
        if len(ids) > 3:
            more = (
                f'<details><summary>Xem {len(ids) - 3} ảnh ứng viên còn lại</summary><div class="cards">'
                + "".join(image_card(iid) for iid in ids[3:])
                + "</div></details>"
            )
        cards.append(
            f'<h3>Mục tiêu {i}: cần {t["required"]} ảnh, có {len(ids)} ID ứng viên</h3><div class="cards">{previews}</div>{more}'
        )
    for e in a["evidence"]:
        r = by_record[e["record_id"]]
        cards.append(
            f"<h3>Bằng chứng {esc(e['role'])} · {esc(e['record_id'])}</h3>"
            + image_card(r["image_id"])
        )
    issues = a.get("label_quality_issues", [])
    if issues:
        cards.append("<h3>Ứng viên có vấn đề (không mặc nhiên là nhãn âm)</h3>")
        for issue in issues:
            status_text = "ĐÃ CÁCH LY" if issue["quarantined"] else "CẦN DUYỆT ĐỊA ĐIỂM"
            cards.append("<p>" + status_text + ": " + esc(", ".join(issue["reasons"])) + "</p>")
            cards.append(image_card(issue["image_id"]))
    if a.get("pending_targets"):
        cards.append("<p>Mục tiêu chưa đủ nhãn; giữ riêng pending_targets, chưa được chấm.</p>")
    status = (
        "CHƯA XÁC ĐỊNH ĐÁP ÁN"
        if q["answerable"] is None
        else "ỨNG VIÊN DƯƠNG"
        if q["answerable"]
        else "ÂM THEO DANH MỤC, KẾ THỪA V1"
    )
    family_links = " ".join(f'<a href="#{qid}">{qid}</a>' for qid in by_family[q["intent_id"]])
    tags = " ".join(q["tags"])
    details = (
        esc(a["verification"])
        + "<br>Bộ đánh giá: "
        + esc(q["evaluation_suite"])
        + "<br>Nhóm báo cáo: "
        + esc(q["report_group"])
    )
    sections.append(
        f'<section id="{q["query_id"]}" data-kind="{q["type"]}" data-category="{q["category"]}" data-split="{q["split"]}"><h2>{q["query_id"]} · {esc(q["type"])}</h2><p class="question">{esc(q["text"])}</p><p><b>{status} · Chưa được rà soát độc lập</b></p><p>Nhóm: {esc(q["category"])} · Split dự kiến: {esc(q["split"])} · {esc(tags)}</p><p>Cùng họ ý định <code>{q["intent_id"]}</code>: {family_links}</p><p>{details}</p><p>Xử lý mong đợi: {esc(q["expected_behavior"])}</p>'
        + "".join(cards)
        + "</section>"
    )
    actions = [
        "verify_intent_and_conditions",
        "inspect_candidate_images",
        "pool_missing_positives",
        "resolve_split_and_family",
        "independent_review",
    ]
    priority = 2
    if q["answerable"] is None:
        actions = [
            "resolve_user_intent",
            "verify_answerability",
            "decide_retrieval_or_clarification",
            "label_or_keep_out_of_scope",
        ]
        priority = 0
    elif q["evaluation_suite"] == "global_visual":
        actions = [
            "pool_full_corpus",
            "inspect_all_candidate_positives",
            "find_missing_positives",
            "resolve_cross_entity_split",
            "independent_review",
        ]
        priority = 0
    elif q["type"] == "multi-hop":
        actions = [
            "verify_bridge_matches",
            "verify_target_matches",
            "check_bridge_uniqueness",
            "check_bridge_is_needed",
            "add_distractors",
            "resolve_splits",
            "independent_review",
        ]
        priority = 1
    elif q["category"] == "robustness":
        actions = [
            "review_canonical_intent_first",
            "verify_same_meaning_and_answers",
            "keep_family_in_one_split",
        ]
        priority = 3
    queue.append(
        {
            "query_id": q["query_id"],
            "type": q["type"],
            "category": q["category"],
            "intent_id": q["intent_id"],
            "priority": priority,
            "text": q["text"],
            "source_record_ids": a["source_record_ids"],
            "actions": actions,
        }
    )


def options(values):
    return "".join(f"<option>{esc(v)}</option>" for v in sorted(set(values)))


header = """<!doctype html><html lang="vi"><meta charset="utf-8"><title>Ngân hàng query v2 — bản nháp</title>
<style>body{font:16px system-ui;margin:24px;background:#f7f8fa;color:#162334}header{position:sticky;top:0;background:#fff;padding:12px;border:1px solid #d0d7de;z-index:1}section{background:white;margin:18px 0;padding:20px;border:1px solid #d0d7de;border-radius:8px}.question{font-size:20px}.cards{display:flex;flex-wrap:wrap}figure{width:250px;margin:8px}img{width:250px;height:170px;object-fit:contain}figcaption{font-size:13px;overflow-wrap:anywhere}input,select{padding:8px;margin:4px}a{color:#1256a0}code{font-size:12px}summary{cursor:pointer}</style>
<h1>400 câu hỏi v2 — nháp để rà soát, chưa phải golden set</h1>
<p>342 câu mới + 58 câu v1. Các ảnh dưới đây là <b>ứng viên nhãn</b>, không phải kết luận mọi điều kiện đã đúng. Không có điểm benchmark v2.</p>
<p>Câu answerable=null cần xác minh; không được tự coi là không có đáp án. Các câu toàn kho thuộc global_visual, báo riêng; không ép nhãn vào dev/test. Canonical và robustness báo riêng theo intent_id.</p>
"""
filters = f'<header><input id="search" placeholder="Tìm câu hỏi, ID, tag..." size="35"><select id="kind"><option value="">Mọi loại</option>{options(q["type"] for q in queries)}</select><select id="category"><option value="">Mọi nhóm</option>{options(q["category"] for q in queries)}</select><select id="split"><option value="">Mọi split</option>{options(q["split"] for q in queries)}</select><b id="count"></b></header>'
script = """<script>
const inputs=['search','kind','category','split'].map(id=>document.getElementById(id));
const sections=[...document.querySelectorAll('section')];
const searchable=sections.map(section=>section.textContent.toLowerCase());
function filter(){let count=0;sections.forEach((section,index)=>{
const ok=searchable[index].includes(inputs[0].value.toLowerCase())&&inputs.slice(1).every(input=>!input.value||section.dataset[input.id]===input.value);
section.hidden=!ok;if(ok)count++;});document.getElementById('count').textContent=`${count}/400 câu`;}
inputs.forEach(input=>input.addEventListener('input',filter));filter();
</script></html>"""
(root / "review.html").write_text(header + filters + "".join(sections) + script, encoding="utf-8")
write_jsonl(
    root / "review-queue.jsonl", sorted(queue, key=lambda q: (q["priority"], q["query_id"]))
)
# Audit độc lập với bước tạo dữ liệu.
assert len(queries) == len(answers) == 400
assert len({q["query_id"] for q in queries}) == 400
assert len({q["text"].casefold().strip() for q in queries}) == 400
assert all(q["reviewed"] is False for q in queries)
assert coverage["source_records_sha256"] == file_hash("var/benchmark-v1/downloaded-records.jsonl")
assert coverage["v1_queries_sha256"] == file_hash("var/benchmark-v1/queries.jsonl")
legacy_q = read_jsonl("var/benchmark-v1/queries.jsonl")
legacy_a = read_jsonl("var/benchmark-v1/answers.jsonl")
if not (root / "label-cleanup-summary.json").exists():
    assert all(
        a["targets"] == old_a["targets"] for a, old_a in zip(answers[:58], legacy_a, strict=True)
    )
group_splits = defaultdict(set)
for q, a in zip(queries, answers, strict=True):
    for t in a["targets"]:
        assert all(iid in by_image for iid in t["image_ids"])
        if q["split"] in ("dev", "test"):
            for iid in t["image_ids"]:
                group_splits[by_image[iid]["split_group"]].add(q["split"])
    assert q["answerable"] is not None or not a["targets"]
assert all(len(splits) == 1 for splits in group_splits.values())
assert len({by_record[rid]["entity_id"] for a in answers for rid in a["source_record_ids"]}) == 183
# Vì còn unassigned/reviewed=false, pipeline freeze phải từ chối.

try:
    validate_benchmark(read_jsonl(root / "downloaded-records.jsonl"), queries, answers)
except ValueError as error:
    blocked = str(error)
else:
    raise AssertionError("Bản nháp không được vượt qua gate freeze")
audit = {
    "status": "passed_draft_checks",
    "query_count": 400,
    "families": len(by_family),
    "v1_source_unchanged": True,
    "all_reviewed_false": True,
    "unknown_answerability": sum(q["answerable"] is None for q in queries),
    "unassigned_split": sum(q["split"] == "unassigned" for q in queries),
    "candidate_ids_exist": True,
    "declared_dev_test_group_overlap": False,
    "freeze_correctly_rejected": blocked,
    "independent_human_review": False,
    "queries_sha256": file_hash(root / "queries.jsonl"),
    "answers_sha256": file_hash(root / "answers.jsonl"),
}
write_json(root / "audit.json", audit)
print(json.dumps(audit, ensure_ascii=False, indent=2))
