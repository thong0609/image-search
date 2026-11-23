import pytest
from pydantic import ValidationError

from image_search.baseline.cli import make_parser
from image_search.baseline.settings import BaselineSettings, get_baseline_settings


def test_settings_reads_env_file_and_environment_overrides_it(tmp_path, monkeypatch):
    env_file = tmp_path / ".env"
    env_file.write_text("IMAGE_SEARCH_BASELINE_TIMEOUT=20\nUNRELATED=value\n")
    monkeypatch.delenv("IMAGE_SEARCH_BASELINE_TIMEOUT", raising=False)
    assert BaselineSettings(_env_file=env_file).timeout == 20
    monkeypatch.setenv("IMAGE_SEARCH_BASELINE_TIMEOUT", "30")
    assert BaselineSettings(_env_file=env_file).timeout == 30


@pytest.mark.parametrize(
    "values",
    [
        {"timeout": 0},
        {"retries": -1},
        {"workers": 0},
        {"max_bytes": 0},
        {"max_pixels": 0},
        {"model_revision": "main"},
    ],
)
def test_settings_rejects_invalid_values(values):
    with pytest.raises(ValidationError):
        BaselineSettings(_env_file=None, **values)


def test_cli_overrides_environment_default(monkeypatch):
    monkeypatch.setenv("IMAGE_SEARCH_BASELINE_TIMEOUT", "30")
    get_baseline_settings.cache_clear()
    try:
        parser = make_parser()
        assert parser.parse_args(["download"]).timeout == 30
        assert parser.parse_args(["download", "--timeout", "5"]).timeout == 5
    finally:
        get_baseline_settings.cache_clear()


def test_cli_rejects_removed_keyword_weight_option():
    with pytest.raises(SystemExit):
        make_parser().parse_args(["run", "--method", "hybrid", "--keyword-weight", "0.75"])
