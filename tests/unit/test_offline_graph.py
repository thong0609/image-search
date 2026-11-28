"""Offline graph identities and provider behavior without live requests."""

import json
from unittest.mock import patch

import httpx
import pytest

from image_search.files import read_json
from image_search.graph.offline.extract import Settings, run
from image_search.graph.offline.models import Extraction
from image_search.graph.offline.registry import build


@pytest.fixture
def response():
    return {
        "input": {
            "entity_id": "place-A",
            "records": [
                {"record_id": "r1", "entity_name": "Ga A", "caption": "Lối vào Ga A màu đỏ"}
            ],
        },
        "output": {
            "records": [
                {
                    "record_id": "r1",
                    "triples": [
                        ["Lối vào Ga A", "PART_OF", "Ga A"],
                        ["Lối vào Ga A", "HAS_COLOR", "Đỏ"],
                    ],
                }
            ]
        },
    }


def test_rejects_missing_records_self_loops_and_bad_relations(response):
    result = Extraction.model_validate(response["output"])
    with pytest.raises(ValueError):
        result.check_input({"records": [{"record_id": "other"}]})
    for triple in (["A", "PART_OF", " a "], ["A", "part of", "B"], ["A", "REL"]):
        with pytest.raises(ValueError):
            Extraction.model_validate({"records": [{"record_id": "r1", "triples": [triple]}]})


def test_scopes_mentions_and_preserves_source_identity(response):
    other = json.loads(json.dumps(response))
    other["input"]["entity_id"] = "place-B"
    other["input"]["records"][0]["record_id"] = "r2"
    other["output"]["records"][0]["record_id"] = "r2"
    artifact = build([response, other])
    assert len(artifact["entities"]) == 6
    assert len({r["id"] for r in artifact["entities"]}) == 6
    assert len(artifact["relations"]) == 2
    assert build([response])["generation"] == build([response])["generation"]


def test_merge_cycles_and_collapsed_facts_fail(response):
    artifact = build([response])
    a, b = artifact["facts"][0]["source"], artifact["facts"][0]["target"]
    with pytest.raises(ValueError, match="cycle"):
        build([response], {"entities": {a: b, b: a}})
    with pytest.raises(ValueError, match="self-loop"):
        build([response], {"entities": {a: b}})


def test_checkpoint_reuses_success_and_retries_http_error(response, tmp_path):
    calls = []

    def handler(request):
        calls.append(request)
        if len(calls) == 1:
            return httpx.Response(503)
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "finish_reason": "stop",
                        "message": {"content": json.dumps(response["output"])},
                    }
                ],
                "usage": {"prompt_tokens": 10},
            },
        )

    client = httpx.Client(
        transport=httpx.MockTransport(handler), base_url="https://api.shopaikey.com/v1/"
    )
    settings = Settings(_env_file=None, api_key="test", retries=1)
    with (
        patch("image_search.graph.offline.extract.httpx.Client", return_value=client),
        patch("image_search.graph.offline.extract.time.sleep"),
    ):
        results = run([response["input"]], tmp_path, settings, 2)
    assert len(calls) == 2
    assert results[0]["output"] == response["output"]
    client = httpx.Client(
        transport=httpx.MockTransport(handler), base_url="https://api.shopaikey.com/v1/"
    )
    with patch("image_search.graph.offline.extract.httpx.Client", return_value=client):
        run([response["input"]], tmp_path, settings, 1)
    assert len(calls) == 2
    assert read_json(tmp_path / "usage.json")["requests_this_run"] == 0


def test_budget_prevents_extra_requests(response, tmp_path):
    settings = Settings(_env_file=None, api_key="test")
    with pytest.raises(ValueError, match="giới hạn"):
        run([response["input"]], tmp_path, settings, 0)


def test_staging_and_vector_candidates_with_qdrant_in_memory(response):
    from types import SimpleNamespace
    from unittest.mock import Mock

    import numpy as np
    from qdrant_client import QdrantClient

    from image_search.graph.offline.publish import stage
    from image_search.graph.offline.resolve import vector_candidates

    artifact = build([response])
    client = QdrantClient(":memory:")
    encoder = SimpleNamespace(
        vector_store=SimpleNamespace(client=client),
        dimensions=2,
        index={"config": {"model": "fake", "revision": "pinned"}, "processor_sha256": "test"},
        encode_texts=lambda texts: (
            np.array([[1.0, 0.0]] * len(texts)),
            [{"truncated": False}] * len(texts),
        ),
    )
    tx = Mock()
    tx.run.return_value.single.side_effect = [
        {"n": len(artifact["entities"])},
        {"n": len(artifact["facts"])},
    ]
    driver = Mock()
    driver.session.return_value.__enter__ = Mock(return_value=driver.session.return_value)
    driver.session.return_value.__exit__ = Mock(return_value=False)
    driver.session.return_value.execute_write.side_effect = lambda callback: callback(tx)
    try:
        result = stage(artifact, encoder, driver, "neo4j")
        rows = vector_candidates(artifact, client, result["registry_collection"])
        assert result["state"] == "staged"
        assert rows and all(not row["auto_merge"] for row in rows)
        assert all(row["candidate"] != row["source"] for row in rows)
    finally:
        client.close()


def test_parallel_circuit_breaker_stops_after_ten_errors(response, tmp_path):
    from image_search.graph.offline.parallel import run_parallel

    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(503)

    client = httpx.Client(
        transport=httpx.MockTransport(handler), base_url="https://api.shopaikey.com/v1/"
    )
    settings = Settings(_env_file=None, api_key="test")
    # 1 worker makes the exact stop point deterministic; retries have no real waiting here.
    with (
        patch("image_search.graph.offline.parallel.httpx.Client", return_value=client),
        patch("threading.Event.wait", return_value=False),
    ):
        result = run_parallel([response["input"]], tmp_path, settings, 100, workers=1)
    assert len(calls) == 10
    assert result["state"] == "paused"
    assert result["pause_reason"] == "consecutive_api_errors"
    assert result["errors_at_pause"] == 10
    assert not (tmp_path / "extractions.json").exists()
    events = [json.loads(line) for line in (tmp_path / "events.jsonl").read_text().splitlines()]
    assert [e["seconds"] for e in events if e["event"] == "retry_wait"] == [
        2,
        4,
        8,
        16,
        32,
        64,
        128,
        256,
        512,
    ]


def test_parallel_success_resets_error_streak_and_counts_invalid_output_tokens(response, tmp_path):
    from image_search.graph.offline.parallel import run_parallel

    statuses = iter([429, 200])

    def handler(request):
        status = next(statuses)
        return httpx.Response(
            status,
            json={
                "choices": [
                    {
                        "finish_reason": "stop",
                        "message": {"content": json.dumps(response["output"])},
                    }
                ],
                "usage": {"prompt_tokens": 3, "completion_tokens": 4},
            },
        )

    client = httpx.Client(
        transport=httpx.MockTransport(handler), base_url="https://api.shopaikey.com/v1/"
    )
    with (
        patch("image_search.graph.offline.parallel.httpx.Client", return_value=client),
        patch("threading.Event.wait", return_value=False),
    ):
        result = run_parallel(
            [response["input"]], tmp_path, Settings(_env_file=None, api_key="test"), 2, workers=1
        )
    assert result["state"] == "completed"
    assert result["consecutive_api_errors"] == 0
    assert result["api_errors"] == 1
    assert result["input_tokens"] == 6
    assert result["completed_records"] == 1


def test_parallel_workers_are_bounded_and_each_record_is_saved(response, tmp_path):
    import threading
    import time

    from image_search.graph.offline.parallel import run_parallel

    lock = threading.Lock()
    active = 0
    peak = 0

    def handler(request):
        nonlocal active, peak
        with lock:
            active += 1
            peak = max(peak, active)
        time.sleep(0.02)
        body = json.loads(request.content)
        group = json.loads(body["messages"][1]["content"])
        out = {"records": [{"record_id": r["record_id"], "triples": []} for r in group["records"]]}
        with lock:
            active -= 1
        return httpx.Response(
            200,
            json={"choices": [{"finish_reason": "stop", "message": {"content": json.dumps(out)}}]},
        )

    groups = []
    for i in range(12):
        group = json.loads(json.dumps(response["input"]))
        group["records"][0]["record_id"] = str(i)
        groups.append(group)
    client = httpx.Client(
        transport=httpx.MockTransport(handler), base_url="https://api.shopaikey.com/v1/"
    )
    with patch("image_search.graph.offline.parallel.httpx.Client", return_value=client):
        result = run_parallel(
            groups, tmp_path, Settings(_env_file=None, api_key="test"), max_requests=12, workers=4
        )
    assert 1 < peak <= 4
    assert result["state"] == "completed"
    assert result["requests"] == 12
    assert len(read_json(tmp_path / "extractions.json")) == 12
