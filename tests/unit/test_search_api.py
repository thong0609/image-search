from unittest.mock import Mock

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from image_search.api.v1.auth import current_user
from image_search.api.v1.search import get_search
from image_search.config import Settings
from image_search.main import create_app
from image_search.planner.schemas import QueryPlan
from image_search.search import SearchService


@pytest.fixture
def service(tmp_path):
    service = SearchService(tmp_path / "thumbnails")
    service.plan = Mock(return_value=(None, False))
    service.retrieve = Mock(
        return_value={
            "groups": [
                {
                    "target_id": "t1",
                    "search_text": "chợ",
                    "status": "candidates",
                    "entity_scope": ["B"],
                    "results": [{"image_id": "a", "score": 1.0}, {"image_id": "c", "score": 0.5}],
                }
            ]
        }
    )
    service.engine = Mock()
    service.engine.catalog.records = {
        "a": [record("A"), record("B", actual_width=1200, actual_height=800)],
        "c": [record("C", page_url="", image_domain=None)],
    }
    return service


def record(entity, **values):
    return {
        "entity_id": entity,
        "entity_name": f"Nơi {entity}",
        "mo_ta": "Mô tả",
        "page_url": "https://example.com/bai",
        "image_domain": "example.com",
        "local_path": "/private/path.jpg",
        **values,
    }


@pytest.fixture
def client(tmp_path, service):
    app = create_app(Settings(storage_root=tmp_path, preload_search=False))
    app.dependency_overrides[get_search] = lambda: service
    with TestClient(app) as client:
        yield client


@pytest.mark.parametrize("body", [{"query": "  "}, {"query": "x" * 501}, {"query": "a", "k": 1}])
def test_invalid_query_never_reaches_planner(client, service, body):
    assert client.post("/v1/search", json=body).status_code == 422
    service.plan.assert_not_called()


def test_items_use_the_matching_place_and_hide_local_paths(client):
    body = client.post("/v1/search", json={"query": " chợ "}).json()
    first, second = body["groups"][0]["items"]
    assert body["query"] == "chợ" and body["planned"] is False
    assert (first["title"], first["width"], first["height"]) == ("Nơi B", 1200, 800)
    assert (second["title"], second["source_url"], second["source_name"]) == ("Nơi C", None, None)
    assert "/private" not in str(body)


def test_fallback_group_is_marked_approximate(client, service):
    service.retrieve.return_value["groups"][0]["status"] = "fallback_results"
    assert client.post("/v1/search", json={"query": "chợ"}).json()["groups"][0]["approximate"]


def test_clarification_question_is_returned_without_images(client, service):
    service.retrieve.return_value = {"question": "Nơi nào?", "groups": []}
    service.plan.return_value = (Mock(spec=QueryPlan), True)
    body = client.post("/v1/search", json={"query": "ảnh vừa rồi"}).json()
    assert body["question"] == "Nơi nào?" and body["groups"] == []
    assert body["planned"] and body["plan_cached"]


def test_failure_does_not_expose_configuration(client, service):
    service.retrieve.side_effect = ConnectionError("secret address")
    response = client.post("/v1/search", json={"query": "chợ"})
    assert response.status_code == 503 and "secret" not in response.text


def test_planner_without_key_falls_back_to_whole_query(tmp_path, monkeypatch):
    pytest.importorskip("openai")
    monkeypatch.setenv("OPENAI_API_KEY", "")
    assert SearchService(tmp_path).plan("chợ") == (None, False)


def test_only_corpus_images_are_served_and_thumbnails_are_bounded(client, service, tmp_path):
    source = tmp_path / "big.png"
    Image.new("RGBA", (2000, 1000), "red").save(source)
    service.images = {"known": source, "gone": tmp_path / "gone.png"}
    client.app.dependency_overrides[current_user] = lambda: {"role": "user"}
    service.load = Mock()
    for path in ("unknown", "gone", "..%2F..%2Fetc%2Fpasswd"):
        assert client.get(f"/v1/images/{path}/preview").status_code == 404
        assert client.get(f"/v1/images/{path}/thumbnail").status_code == 404
    assert client.get("/v1/images/known/preview").content == source.read_bytes()
    response = client.get("/v1/images/known/thumbnail")
    assert response.headers["content-type"] == "image/jpeg"
    assert response.headers["x-content-type-options"] == "nosniff"
    saved = service.thumbnail_path("known")
    with Image.open(saved) as image:
        assert image.size == (640, 320)
    modified = saved.stat().st_mtime_ns
    assert service.thumbnail_path("known").stat().st_mtime_ns == modified
    assert not list(saved.parent.glob("*.tmp"))


def test_close_releases_every_client(tmp_path):
    service = SearchService(tmp_path)
    service.encoder, service.engine = Mock(), Mock()
    service.close()
    service.encoder.vector_store.client.close.assert_called_once()
    service.engine.vector_store.client.close.assert_called_once()
    service.engine.graph_store.driver.close.assert_called_once()


def test_original_media_requires_login(client):
    for path in ("/v1/images/a", "/v1/images/a/preview"):
        assert client.get(path).status_code == 401
    assert client.post("/v1/images/a/download").status_code == 401


def test_filter_validation_before_planner(client, service):
    for filters in (
        {"orientation": "diagonal"},
        {"min_width": 0},
        {"collection_ids": []},
        {"min_height": True},
    ):
        assert (
            client.post("/v1/search", json={"query": "chợ", "filters": filters}).status_code == 422
        )
    service.plan.assert_not_called()


def test_dimension_filters_exclude_unknown_sizes(service):
    service.images = {"a": None, "c": None}
    service.engine.catalog.records["a"][0].update(actual_width=1200, actual_height=800)
    assert service.matching_images({"orientation": "landscape", "min_width": 1000}) == {"a"}
    assert service.matching_images({"orientation": "portrait"}) == set()
