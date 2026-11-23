import io

import httpx
import pytest
from PIL import Image

from image_search.baseline import download
from image_search.baseline.utils import read_jsonl, write_jsonl


def image_bytes():
    stream = io.BytesIO()
    Image.new("RGB", (3, 2), "red").save(stream, format="PNG")
    return stream.getvalue()


@pytest.fixture
def public_dns(monkeypatch):
    monkeypatch.setattr(
        download.socket, "getaddrinfo", lambda *a, **k: [(2, 1, 6, "", ("8.8.8.8", 443))]
    )


def test_download_deduplicates_bytes_and_resume_checks_file(tmp_path, monkeypatch, public_dns):
    real_client = httpx.Client
    calls = []
    content = image_bytes()

    def respond(request):
        calls.append(str(request.url))
        assert request.url.host == "8.8.8.8"
        assert request.headers["host"] == "example.com"
        assert request.extensions["sni_hostname"] == "example.com"
        return httpx.Response(200, content=content)

    client = httpx.Client(transport=httpx.MockTransport(respond))
    monkeypatch.setattr(download.httpx, "Client", lambda **kwargs: client)
    source = tmp_path / "records.jsonl"
    write_jsonl(
        source,
        [{"record_id": str(i), "image_url": f"https://example.com/{i % 2}"} for i in range(3)],
    )
    records = download.download_records(source, tmp_path)
    assert len(calls) == 2
    assert len({r["image_id"] for r in records}) == 1
    assert len(list((tmp_path / "images").glob("*.png"))) == 1
    assert records[0]["actual_width"] == 3
    # Không mở lại HTTP khi mọi URL đã có ảnh hợp lệ.
    monkeypatch.setattr(
        download.httpx,
        "Client",
        lambda **kwargs: real_client(
            transport=httpx.MockTransport(lambda request: pytest.fail("Không được tải lại"))
        ),
    )
    download.download_records(source, tmp_path)
    assert len(calls) == 2
    assert len(read_jsonl(tmp_path / "downloaded-records.jsonl")) == 3
    image_path = next((tmp_path / "images").glob("*.png"))
    image_path.write_bytes(b"broken")
    assert not download.reusable(records[0])


def test_rejects_private_redirect_before_request(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(
        download.socket,
        "getaddrinfo",
        lambda host, *a, **k: [
            (2, 1, 6, "", ("127.0.0.1" if host == "localhost" else "8.8.8.8", 443))
        ],
    )

    def respond(request):
        calls.append(request)
        return httpx.Response(302, headers={"location": "http://localhost/private"})

    with httpx.Client(transport=httpx.MockTransport(respond)) as client:
        result = download.download_image(client, "https://example.com/a", tmp_path, 1000, 0)
    assert result["download_status"] == "failed"
    assert "không public" in result["download_error"]
    assert len(calls) == 1


@pytest.mark.parametrize("content,limit", [(b"not an image", 100), (image_bytes(), 2)])
def test_invalid_or_oversized_image_is_not_saved(tmp_path, public_dns, content, limit):
    with httpx.Client(
        transport=httpx.MockTransport(lambda request: httpx.Response(200, content=content))
    ) as client:
        result = download.download_image(client, "https://example.com/a", tmp_path, limit, 0)
    assert result["download_status"] == "failed"
    assert not list(tmp_path.iterdir())


def test_timeout_retries_only_up_to_limit(tmp_path, monkeypatch, public_dns):
    calls = []
    monkeypatch.setattr(download.time, "sleep", lambda seconds: None)

    def respond(request):
        calls.append(request)
        raise httpx.ReadTimeout("timeout")

    with httpx.Client(transport=httpx.MockTransport(respond)) as client:
        result = download.download_image(client, "https://example.com/a", tmp_path, 1000, 2)
    assert result["download_status"] == "failed"
    assert len(calls) == 3


def test_resume_recovers_incomplete_last_log_entry(tmp_path):
    log = tmp_path / "download-log.jsonl"
    log.write_text('{"image_url":"https://example.com/a","download_status":"failed"}\n{"ima')
    previous = download.read_download_log(log)
    assert previous["https://example.com/a"]["download_status"] == "failed"
    assert len(read_jsonl(log)) == 1
