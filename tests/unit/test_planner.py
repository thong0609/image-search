# ruff: noqa: E402
# The OpenAI SDK is an optional project extra.
import copy
import json
from pathlib import Path

import httpx
import pytest
from pydantic import ValidationError

pytest.importorskip("openai")
from openai import OpenAI

from image_search.baseline.utils import read_jsonl
from image_search.planner.cli import main, validate_inputs
from image_search.planner.evaluate import evaluate_cases, score_case
from image_search.planner.router import make_client, route_query
from image_search.planner.schemas import QueryPlan
from image_search.planner.settings import PlannerSettings

CASES = Path(__file__).parents[1] / "fixtures/planner-cases.jsonl"


def expected(kind="single"):
    return copy.deepcopy(
        next(r["expected"] for r in read_jsonl(CASES) if r["expected"]["query_type"] == kind)
    )


def draft(**values):
    target = {
        "image_subject": "mặt tiền",
        "image_text": "mặt tiền cửa hàng A",
        "entities": [],
        "conditions": [],
        "count": None,
    }
    return {"targets": [target | values], "clarification_question": None}


def response_payload(plan=None, status="completed", refusal=False):
    content = (
        [{"type": "refusal", "refusal": "refused"}]
        if refusal
        else [{"type": "output_text", "text": json.dumps(plan or draft()), "annotations": []}]
    )
    return {
        "id": "resp_test",
        "object": "response",
        "created_at": 1,
        "status": status,
        "model": "test-model",
        "output": [
            {
                "type": "message",
                "id": "msg_test",
                "role": "assistant",
                "status": "completed",
                "content": content,
            }
        ],
        "usage": {
            "input_tokens": 100,
            "output_tokens": 20,
            "total_tokens": 120,
            "input_tokens_details": {"cached_tokens": 30},
            "output_tokens_details": {"reasoning_tokens": 0},
        },
    }


def mock_client(handler):
    return OpenAI(
        api_key="test-secret",
        max_retries=0,
        http_client=httpx.Client(transport=httpx.MockTransport(handler)),
    )


def test_curated_cases_have_balanced_splits_and_valid_plans():
    rows = read_jsonl(CASES)
    validate_inputs(rows, 4000)
    assert len(rows) == 60
    for split in ("dev", "test"):
        selected = [r for r in rows if r["split"] == split]
        assert len(selected) == 30
        assert sum(r["expected"]["query_type"] == "unclear" for r in selected) == 3


@pytest.mark.parametrize("change", ["duplicate", "forward", "wrong_type", "orphan", "wrong_target"])
def test_invalid_dependency_plans_are_rejected(change):
    plan = expected("multi-hop")
    if change == "duplicate":
        plan["steps"][1]["id"] = "s1"
    elif change == "forward":
        plan["steps"][0]["depends_on"] = ["s2"]
    elif change == "wrong_type":
        plan["query_type"] = "single"
    elif change == "orphan":
        plan["steps"][1]["depends_on"] = []
    else:
        plan["steps"][1]["target_id"] = "other"
    with pytest.raises(ValidationError):
        QueryPlan.model_validate(plan)


def test_clarification_cannot_silently_execute_steps():
    plan = expected()
    plan.update(needs_clarification=True, clarification_question="Bạn muốn tìm gì?")
    with pytest.raises(ValidationError):
        QueryPlan.model_validate(plan)


def test_real_sdk_request_sends_only_query_and_schema_and_records_usage():
    captured = {}

    def handler(request):
        captured.update(json.loads(request.content))
        return httpx.Response(200, json=response_payload())

    settings = PlannerSettings(
        _env_file=None, input_price=1, cached_input_price=0.5, output_price=2
    )
    with mock_client(handler) as client:
        result = route_query("Cho tôi 2 ảnh mặt tiền của cửa hàng A.", settings, client)
    assert result["status"] == "ok"
    assert result["response_id"] == "resp_test"
    assert result["cached_input_tokens"] == 30
    assert result["estimated_cost_usd"] == pytest.approx(0.000125)
    assert captured["store"] is False
    assert captured["text"]["format"]["strict"] is True
    assert len(captured["input"]) == 2
    assert captured["input"][1]["content"] == "Cho tôi 2 ảnh mặt tiền của cửa hàng A."
    assert "expected" not in captured
    assert "test-secret" not in json.dumps(result)


@pytest.mark.parametrize(
    "mode,code",
    [
        ("refusal", "model_refusal"),
        ("incomplete", "incomplete_response"),
        ("bad_plan", "invalid_plan"),
        ("timeout", "api_timeout"),
        ("unauthorized", "api_http_401"),
    ],
)
def test_errors_do_not_turn_into_single_route(mode, code):
    def handler(request):
        if mode == "timeout":
            raise httpx.ReadTimeout("timeout", request=request)
        if mode == "unauthorized":
            return httpx.Response(401, json={"error": {"message": "secret must not log"}})
        payload = response_payload(
            refusal=mode == "refusal", status="incomplete" if mode == "incomplete" else "completed"
        )
        if mode in ("bad_plan", "incomplete"):
            payload["output"][0]["content"] = [
                {"type": "output_text", "text": "{", "annotations": []}
            ]
        return httpx.Response(200, json=payload)

    with mock_client(handler) as client:
        result = route_query("Tìm ảnh cửa hàng A", PlannerSettings(_env_file=None), client)
    assert result["status"] == "error"
    assert result["plan"] is None
    assert result["error_code"] == code
    assert "secret must not log" not in json.dumps(result)


def test_empty_query_rejected_before_api():
    with pytest.raises(ValueError, match="rỗng"):
        route_query("  ", PlannerSettings(_env_file=None), None)


def test_missing_key_has_clear_message():
    settings = PlannerSettings(_env_file=None, OPENAI_API_KEY=None)
    with pytest.raises(ValueError, match="OPENAI_API_KEY"):
        make_client(settings)


def test_graph_score_ignores_step_ids_but_detects_wrong_count():
    plan = expected("multi-hop")
    renamed = copy.deepcopy(plan)
    renamed["steps"][0]["id"] = "bridge"
    renamed["steps"][1]["id"] = "end"
    renamed["steps"][1]["depends_on"] = ["bridge"]
    prediction = {"status": "ok", "plan": renamed}
    assert score_case(plan, prediction)["plan_correct"]
    renamed["steps"][1]["count"] = 3
    assert not score_case(plan, prediction)["counts_correct"]


def test_evaluation_keeps_failures_in_denominator_and_checks_ids():
    rows = read_jsonl(CASES)[:2]
    predictions = [
        {
            "query_id": rows[0]["query_id"],
            "status": "ok",
            "plan": rows[0]["expected"],
            "latency_ms": 10,
            "error_code": None,
        },
        {
            "query_id": rows[1]["query_id"],
            "status": "error",
            "plan": None,
            "latency_ms": 30,
            "error_code": "api_timeout",
        },
    ]
    report = evaluate_cases(rows, predictions)
    assert report["accuracy"]["overall"]["route_correct"] == 0.5
    assert report["confusion_matrix"]["single"]["ERROR"] == 1
    assert report["latency_ms"]["p90"] == 28
    assert report["usage"]["estimated_cost_usd"]["missing_queries"] == 2
    with pytest.raises(ValueError, match="Prediction"):
        evaluate_cases(rows, predictions[:1])


def test_batch_cli_uses_only_text_and_preserves_existing_outputs(tmp_path, monkeypatch):
    class Client:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

    received = []

    def fake_route(text, settings, client):
        received.append(text)
        return {"status": "ok", "plan": expected(), "error_code": None}

    monkeypatch.setattr("image_search.planner.cli.make_client", lambda settings: Client())
    monkeypatch.setattr("image_search.planner.cli.route_query", fake_route)
    output = tmp_path / "run"
    monkeypatch.setattr(
        "sys.argv", ["planner", "run", str(CASES), "--limit", "2", "--output-dir", str(output)]
    )
    main()
    assert received == [r["text"] for r in read_jsonl(CASES)[:2]]
    assert len(read_jsonl(output / "predictions.jsonl")) == 2
    assert "api_key" not in json.loads((output / "run.json").read_text())["settings"]
    with pytest.raises(SystemExit):
        main()


def test_count_must_be_integer_and_clarification_must_be_boolean():
    plan = expected()
    plan["steps"][0]["count"] = True
    with pytest.raises(ValidationError):
        QueryPlan.model_validate(plan)
    plan = expected()
    plan["needs_clarification"] = "false"
    with pytest.raises(ValidationError):
        QueryPlan.model_validate(plan)


def test_dependency_shape_misses_bridge_when_route_changes_to_direct_lookup():
    plan = expected("multi-hop")
    direct = expected("multi-hop")
    direct["query_type"] = "single"
    direct["steps"] = [direct["steps"][1]]
    direct["steps"][0]["depends_on"] = []
    result = score_case(plan, {"status": "ok", "plan": direct})
    assert not result["dependencies_correct"]
    assert not result["plan_correct"]


def test_graph_anchor_cannot_cross_targets_or_ignore_dependencies():
    plan = expected("multi-hop")
    step = plan["steps"][0]
    step["graph"] = {
        "target_name": None,
        "target_kind": "place",
        "target_category": None,
        "match": "all",
        "conditions": [
            {
                "relations": ["LOCATED_IN"],
                "direction": "out",
                "anchor_name": None,
                "anchor_step_id": "not-present",
            }
        ],
    }
    with pytest.raises(ValidationError, match="dependencies"):
        QueryPlan.model_validate(plan)


def test_client_uses_official_openai_endpoint_and_key(monkeypatch):
    from image_search.planner import router

    captured = []

    def handler(request):
        captured.append((request.url.host, request.url.path, request.headers["authorization"]))
        return httpx.Response(200, json=response_payload())

    monkeypatch.setenv("OPENAI_BASE_URL", "https://wrong.example/v1")
    monkeypatch.setattr(
        router,
        "OpenAI",
        lambda **kwargs: OpenAI(
            **kwargs, http_client=httpx.Client(transport=httpx.MockTransport(handler))
        ),
    )
    settings = PlannerSettings(_env_file=None, OPENAI_API_KEY="test-key")
    with make_client(settings) as client:
        result = route_query("Tìm ảnh cửa hàng A", settings, client)
    assert result["status"] == "ok"
    assert captured == [("api.openai.com", "/v1/responses", "Bearer test-key")]
    assert "test-key" not in json.dumps(settings.model_dump(mode="json", exclude={"api_key"}))


def test_missing_usage_fields_do_not_invent_cost():
    from types import SimpleNamespace

    from image_search.planner.router import usage_details

    settings = PlannerSettings(_env_file=None, input_price=1, output_price=2)
    result = usage_details(SimpleNamespace(usage=SimpleNamespace()), settings)
    assert result["estimated_cost_usd"] is None
    assert result["input_tokens"] is None
