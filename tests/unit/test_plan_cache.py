import threading
import time
from unittest.mock import MagicMock, Mock

import pytest

from image_search.planner.cache import PlanCache, normalize_query
from image_search.search import SearchService


@pytest.mark.parametrize(
    "text", ["ảnh  Chợ Hàn", " ảnh Chợ Hàn? ", "ảnh Chợ Hàn.", "ảnh Cho\u031b\u0323 Hàn"]
)
def test_spacing_final_punctuation_and_unicode_form_share_a_plan(text):
    assert normalize_query(text) == "ảnh Chợ Hàn"


@pytest.mark.parametrize("text", ["ảnh chợ Hàn", "ảnh Cho Han", "2 ảnh Chợ Hàn"])
def test_case_diacritics_and_wording_stay_different(text):
    assert normalize_query(text) != "ảnh Chợ Hàn"


def test_repeated_key_calls_model_once_and_least_recent_is_evicted():
    cache, create = PlanCache(2), Mock(side_effect=lambda: object())
    first = cache.get_or_create("a", create)
    assert cache.get_or_create("a", create) == (first[0], True) and first[1] is False
    cache.get_or_create("b", create)
    cache.get_or_create("a", create)
    cache.get_or_create("c", create)
    assert list(cache.plans) == ["a", "c"] and create.call_count == 3


def test_failures_are_not_stored():
    cache = PlanCache(2)
    assert cache.get_or_create("a", lambda: None) == (None, False)
    with pytest.raises(ValueError):
        cache.get_or_create("a", Mock(side_effect=ValueError))
    assert cache.get_or_create("a", lambda: "plan") == ("plan", False)
    assert not cache.pending


def test_zero_size_disables_cache():
    create = Mock(return_value="plan")
    cache = PlanCache(0)
    assert [cache.get_or_create("a", create) for _ in range(2)] == [("plan", False)] * 2
    assert create.call_count == 2


@pytest.mark.parametrize("outcome", ["plan", None, ValueError("lỗi")])
def test_concurrent_requests_share_one_call(outcome):
    cache, started, release = PlanCache(2), threading.Event(), threading.Event()
    calls, results = [], []

    def create():
        calls.append(1)
        started.set()
        release.wait(5)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome

    def request():
        try:
            results.append(cache.get_or_create("a", create)[0])
        except ValueError as error:
            results.append(error)

    threads = [threading.Thread(target=request) for _ in range(4)]
    threads[0].start()
    started.wait(5)
    for thread in threads[1:]:
        thread.start()
    time.sleep(0.05)
    release.set()
    for thread in threads:
        thread.join(5)
    assert len(calls) == 1 and results == [outcome] * 4


def test_service_reuses_plan_until_prompt_or_model_changes(tmp_path, monkeypatch):
    pytest.importorskip("openai")
    from image_search.planner import router

    plan = {
        "query_type": "single",
        "needs_clarification": False,
        "clarification_question": None,
        "steps": [
            {
                "id": "s1",
                "target_id": "t1",
                "action": "retrieve_images",
                "search_text": "chợ",
                "entity_mention": None,
                "conditions": [],
                "count": None,
                "depends_on": [],
            }
        ],
    }
    route = Mock(return_value={"status": "ok", "plan": plan})
    monkeypatch.setattr(router, "make_client", MagicMock())
    monkeypatch.setattr(router, "route_query", route)
    service = SearchService(tmp_path)
    assert service.plan("ảnh chợ")[1] is False
    assert service.plan(" ảnh  chợ? ")[1] is True
    assert route.call_count == 1
    monkeypatch.setattr(router, "PROMPT", "prompt mới")
    assert service.plan("ảnh chợ")[1] is False
    monkeypatch.setenv("IMAGE_SEARCH_PLANNER_MODEL", "other-model")
    assert service.plan("ảnh chợ")[1] is False
    assert route.call_count == 3
