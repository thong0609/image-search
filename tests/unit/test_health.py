from fastapi.testclient import TestClient

from image_search.api.dependencies import get_readiness
from image_search.config import Settings
from image_search.main import create_app


class Probe:
    def __init__(self, healthy):
        self.healthy = healthy

    def check(self):
        return {"postgres": self.healthy, "qdrant": self.healthy, "storage": True}


def test_liveness_works_without_running_dependencies(tmp_path):
    app = create_app(Settings(storage_root=tmp_path))
    with TestClient(app) as client:
        assert client.get("/health/live").json() == {"status": "alive"}


def test_readiness_reports_unavailable_without_exposing_credentials(tmp_path):
    app = create_app(Settings(storage_root=tmp_path))
    app.dependency_overrides[get_readiness] = lambda: Probe(False)
    with TestClient(app) as client:
        response = client.get("/health/ready")
        assert response.status_code == 503
        assert response.json()["checks"]["postgres"] is False
        assert "postgresql" not in response.text


def test_readiness_succeeds_when_all_probes_succeed(tmp_path):
    app = create_app(Settings(storage_root=tmp_path))
    app.dependency_overrides[get_readiness] = lambda: Probe(True)
    with TestClient(app) as client:
        assert client.get("/health/ready").status_code == 200
