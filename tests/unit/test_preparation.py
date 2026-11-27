from threading import Event
from unittest.mock import Mock

from fastapi.testclient import TestClient

from image_search.api.v1.health import get_readiness
from image_search.config import Settings
from image_search.main import create_app
from image_search.preparation import SearchPreparation
from image_search.search import SearchService


class Healthy:
    def check(self):
        return {"postgres": True, "qdrant": True, "storage": True}


def test_startup_prepares_once_and_rejects_search_until_ready(tmp_path, monkeypatch):
    entered, release = Event(), Event()
    calls = []

    def prepare(self):
        calls.append(self)
        entered.set()
        release.wait(5)

    monkeypatch.setattr(SearchService, "prepare", prepare)
    app = create_app(Settings(storage_root=tmp_path))
    app.dependency_overrides[get_readiness] = Healthy
    with TestClient(app) as client:
        try:
            assert entered.wait(2)
            assert client.get("/health/live").status_code == 200
            assert client.get("/health/search").json() == {"status": "preparing"}
            assert client.get("/health/ready").status_code == 503
            response = client.post("/v1/search", json={"query": "ảnh"})
            assert response.status_code == 503
            assert response.json()["error"]["code"] == "SEARCH_PREPARING"
            assert response.headers["retry-after"] == "1"
            release.set()
            assert app.state.preparation.done.wait(2)
            assert client.get("/health/search").json() == {"status": "ready"}
            assert client.get("/health/ready").status_code == 200
            assert len(calls) == 1
        finally:
            release.set()


def test_failed_preparation_does_not_report_ready_or_expose_error(tmp_path, monkeypatch):
    def prepare(self):
        raise RuntimeError("private path and credential")

    monkeypatch.setattr(SearchService, "prepare", prepare)
    app = create_app(Settings(storage_root=tmp_path))
    app.dependency_overrides[get_readiness] = Healthy
    with TestClient(app) as client:
        assert app.state.preparation.done.wait(2)
        response = client.get("/health/search")
        assert response.json() == {"status": "failed"}
        assert "private" not in response.text
        assert client.get("/health/ready").status_code == 503
        assert client.post("/v1/search", json={"query": "ảnh"}).status_code == 503


def test_preparation_warms_text_encoder_and_retrieval_without_planner(tmp_path):
    service = SearchService(tmp_path)
    service.load = Mock()
    service.encoder = Mock()
    service.encoder.encode_texts.return_value = (["vector"], [{}])
    service.engine = Mock()
    service.plan = Mock(side_effect=AssertionError("No paid planner during startup"))
    preparation = SearchPreparation(service)
    preparation.close()
    assert preparation.status == "ready"
    service.load.assert_called_once_with()
    service.encoder.encode_texts.assert_called_once_with(["ảnh"])
    service.engine.search.assert_called_once_with("ảnh", "vector", "hybrid", 1)
    service.plan.assert_not_called()
