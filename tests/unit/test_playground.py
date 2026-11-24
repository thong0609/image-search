from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from fastapi.testclient import TestClient

from image_search.api.v1.playground import get_playground
from image_search.config import Settings
from image_search.main import create_app
from image_search.playground import PlaygroundBusy, PlaygroundService


@pytest.fixture
def api(tmp_path):
    app = create_app(Settings(storage_root=tmp_path))
    service = Mock()
    app.dependency_overrides[get_playground] = lambda: service
    with TestClient(app) as client:
        yield client, service


@pytest.mark.parametrize(
    "body",
    [
        {"text": "  "},
        {"text": "x" * 4001},
        {"text": "ảnh", "mode": "other"},
        {"text": "ảnh", "method": "other"},
        {"text": "ảnh", "api_key": "unwanted"},
    ],
)
def test_invalid_queries_do_not_call_model(api, body):
    client, service = api
    assert client.post("/v1/playground/run", json=body).status_code == 422
    service.run.assert_not_called()


def test_api_forwards_requested_mode_and_method(api):
    client, service = api
    service.run.return_value = {"planner": {"status": "ok"}, "execution": None}
    response = client.post(
        "/v1/playground/run", json={"text": "  tìm ảnh  ", "mode": "search", "method": "keyword"}
    )
    assert response.status_code == 200
    service.run.assert_called_once_with("tìm ảnh", "search", "keyword")


def test_api_errors_do_not_expose_credentials(api):
    client, service = api
    for error in (ValueError("secret credential"), ConnectionError("secret credential")):
        service.run.side_effect = error
        response = client.post("/v1/playground/run", json={"text": "ảnh"})
        assert response.status_code == 503
        assert "secret" not in response.text
    service.run.side_effect = PlaygroundBusy()
    assert client.post("/v1/playground/run", json={"text": "ảnh"}).status_code == 409


def test_only_allowlisted_images_can_be_served(api, tmp_path):
    client, service = api
    path = tmp_path / "image.png"
    path.write_bytes(b"fixture image bytes")
    service.image_path.side_effect = lambda iid: path if iid == "known-id" else None
    assert client.get("/v1/playground/images/unknown").status_code == 404
    response = client.get("/v1/playground/images/known-id")
    assert response.status_code == 200
    assert response.content == b"fixture image bytes"
    assert response.headers["x-content-type-options"] == "nosniff"


def planned(clarify=False):
    return {
        "text": "ảnh A",
        "status": "ok",
        "latency_ms": 10,
        "plan": {
            "query_type": "unclear" if clarify else "single",
            "needs_clarification": clarify,
            "clarification_question": "Nơi nào?" if clarify else None,
            "steps": []
            if clarify
            else [
                {
                    "id": "s1",
                    "target_id": "t1",
                    "action": "retrieve_images",
                    "entity_mention": None,
                    "conditions": [],
                    "count": None,
                    "search_text": "ảnh A",
                    "depends_on": [],
                }
            ],
        },
    }


@pytest.fixture
def model(monkeypatch):
    pytest.importorskip("openai")
    from image_search.planner import router

    client = Mock()
    client.__enter__ = Mock(return_value=client)
    client.__exit__ = Mock(return_value=False)
    monkeypatch.setattr(router, "make_client", lambda _: client)
    route = Mock(return_value=planned())
    monkeypatch.setattr(router, "route_query", route)
    return route


def test_planner_only_does_not_load_encoder_or_retrieval(model):
    service = PlaygroundService()
    service.load = Mock(side_effect=AssertionError("Không nạp retrieval"))
    result = service.run("ảnh A", "planner", "hybrid")
    assert result["planner"]["status"] == "ok"
    assert result["execution"] is None
    model.assert_called_once()
    service.load.assert_not_called()


def listing_engine(strict):
    engine = Mock()
    engine.settings.list_size, engine.settings.top_k = 20, 100
    engine.execute.return_value = strict
    engine.search.return_value = [{"image_id": "image2", "score": 0.1}]
    engine.catalog.records = {
        "image1": [
            {"entity_id": "A", "entity_name": "Cửa hàng A", "mo_ta": "Bên trong"},
            {"entity_id": "B", "entity_name": "Cửa hàng B", "mo_ta": "Khác"},
        ],
        "image2": [{"entity_id": "C", "entity_name": "Cửa hàng C", "mo_ta": "Chung"}],
    }
    return engine


def test_planner_error_still_lists_images_from_the_whole_query(model):
    service = PlaygroundService()
    service.load = Mock()
    service.engine = listing_engine(None)
    model.return_value = {
        "status": "error",
        "error_code": "invalid_plan",
        "plan": None,
        "latency_ms": 5,
    }
    execution = service.run("ảnh A", "search", "keyword")["execution"]
    service.engine.execute.assert_not_called()
    assert execution["status"] == "fallback_results"
    assert execution["groups"][0]["results"][0]["entity_names"] == ["Cửa hàng C"]


def test_clarification_does_not_trigger_retrieval(model):
    service = PlaygroundService()
    service.load = Mock(side_effect=AssertionError("Không nạp retrieval"))
    model.return_value = planned(clarify=True)
    assert service.run("ảnh A", "search", "hybrid")["execution"]["status"] == "needs_clarification"
    service.load.assert_not_called()


def test_keyword_search_uses_pipeline_and_provides_same_origin_image_urls(model):
    service = PlaygroundService()
    service.load = Mock()
    found = [{"image_id": "image1", "score": 0.2}]
    service.engine = listing_engine(
        {
            "status": "candidate_results",
            "trace": [],
            "groups": [
                {
                    "target_id": "t1",
                    "status": "candidates",
                    "entity_scope": ["A"],
                    "candidates": found,
                    "results": found,
                    "verification_status": "trusted_metadata_scope",
                }
            ],
        }
    )
    result = service.run("ảnh A", "search", "keyword")
    service.load.assert_called_once_with(False)
    assert service.engine.execute.call_args.args[1:] == ("keyword", {})
    image, other = result["execution"]["groups"][0]["results"]
    assert other["entity_names"] == ["Cửa hàng C"] and other["source"] == "query"
    assert image["image_url"] == "/v1/playground/images/image1"
    assert image["entity_names"] == ["Cửa hàng A"]
    assert image["caption"] == "Bên trong"
    assert "local_path" not in str(result)


def test_busy_service_prevents_duplicate_paid_requests(model):
    service = PlaygroundService()
    service.lock.acquire()
    try:
        with pytest.raises(PlaygroundBusy):
            service.run("ảnh A", "planner", "hybrid")
    finally:
        service.lock.release()
    model.assert_not_called()


def test_image_path_only_resolves_existing_corpus_ids(tmp_path):
    service = PlaygroundService()
    path = tmp_path / "image.jpg"
    path.write_bytes(b"image")
    service.images = {"known": path, "missing": Path("/does/not/exist")}
    assert service.image_path("known") == path
    assert service.image_path("missing") is None
    assert service.image_path("../../etc/passwd") is None


def test_service_closes_both_qdrant_clients_and_graph():
    service = PlaygroundService()
    service.encoder = SimpleNamespace(vector_store=Mock())
    service.engine = Mock()
    service.close()
    service.encoder.vector_store.client.close.assert_called_once()
    service.engine.vector_store.client.close.assert_called_once()
    service.engine.graph_store.driver.close.assert_called_once()


def test_retrieval_failure_preserves_plan_without_leaking_error(model):
    service = PlaygroundService()
    service.load = Mock(side_effect=ConnectionError("secret database address"))
    result = service.run("ảnh A", "search", "hybrid")
    assert result["planner"]["status"] == "ok"
    assert result["planner"]["plan"]
    assert result["execution"]["status"] == "execution_error"
    assert result["execution"]["groups"] == []
    assert "secret" not in str(result)
