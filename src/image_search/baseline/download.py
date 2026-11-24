"""Tải URL public, kiểm tra ảnh và lưu theo hash bytes gốc."""

import hashlib
import io
import ipaddress
import json
import socket
import time
import warnings
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import httpx
from PIL import Image

from image_search.baseline.settings import get_baseline_settings
from image_search.files import file_hash, read_jsonl, write_json, write_jsonl


def public_address(url):
    url = httpx.URL(url)
    if url.scheme not in {"http", "https"} or not url.host or url.username or url.password:
        raise ValueError("URL phải là HTTP(S) public, không chứa tài khoản")
    addresses = socket.getaddrinfo(url.host, url.port, type=socket.SOCK_STREAM)
    ips = [item[4][0] for item in addresses]
    if not ips or any(not ipaddress.ip_address(ip).is_global for ip in ips):
        raise ValueError("URL trỏ tới địa chỉ không public")
    return ips[0]


def fetch_bytes(client, url, max_bytes):
    for _ in range(6):
        original = httpx.URL(url)
        address = public_address(original)
        # Kết nối đúng IP đã kiểm tra; giữ Host và TLS hostname của URL gốc.
        request = client.build_request(
            "GET",
            original.copy_with(host=address),
            headers={"Host": original.netloc.decode()},
            extensions={"sni_hostname": original.host},
        )
        response = client.send(request, stream=True, follow_redirects=False)
        try:
            if response.is_redirect:
                if "location" not in response.headers:
                    raise ValueError("Redirect thiếu Location")
                url = str(original.join(response.headers["location"]))
                continue
            response.raise_for_status()
            chunks = []
            size = 0
            for chunk in response.iter_bytes():
                size += len(chunk)
                if size > max_bytes:
                    raise ValueError("Ảnh vượt giới hạn dung lượng")
                chunks.append(chunk)
            return b"".join(chunks)
        finally:
            response.close()
    raise ValueError("Quá nhiều redirect")


def inspect_image(data):
    with warnings.catch_warnings():
        warnings.simplefilter("error", Image.DecompressionBombWarning)
        with Image.open(io.BytesIO(data)) as image:
            if image.width * image.height > get_baseline_settings().max_pixels:
                raise ValueError("Ảnh vượt giới hạn số pixel")
            width, height = image.size
            image_format = image.format
            image.verify()
        with Image.open(io.BytesIO(data)) as image:
            image.load()
    extension = {"JPEG": "jpg", "PNG": "png", "WEBP": "webp", "GIF": "gif"}.get(image_format, "img")
    return width, height, extension


def reusable(result):
    if result.get("download_status") != "success":
        return False
    path = Path(result["local_path"])
    try:
        if file_hash(path) != result["image_id"]:
            return False
        inspect_image(path.read_bytes())
        return True
    except (OSError, ValueError, Image.DecompressionBombError, Image.DecompressionBombWarning):
        return False


def download_image(client, url, image_dir, max_bytes, retries):
    for attempt in range(retries + 1):
        try:
            data = fetch_bytes(client, url, max_bytes)
            width, height, extension = inspect_image(data)
            image_id = hashlib.sha256(data).hexdigest()
            path = image_dir / f"{image_id}.{extension}"
            # Mỗi worker ghi file tạm riêng, rồi thay thế nguyên file.
            temporary = image_dir / f"{image_id}.{hashlib.sha256(url.encode()).hexdigest()}.tmp"
            temporary.write_bytes(data)
            temporary.replace(path)
            return {
                "image_url": url,
                "download_status": "success",
                "image_id": image_id,
                "local_path": str(path.resolve()),
                "actual_width": width,
                "actual_height": height,
                "download_error": None,
            }
        except (
            httpx.HTTPError,
            OSError,
            ValueError,
            Image.DecompressionBombError,
            Image.DecompressionBombWarning,
        ) as error:
            retry = isinstance(error, (httpx.TransportError, socket.gaierror))
            if isinstance(error, httpx.HTTPStatusError):
                retry = error.response.status_code == 429 or error.response.status_code >= 500
            if retry and attempt < retries:
                time.sleep(0.5 * (attempt + 1))
                continue
            return {
                "image_url": url,
                "download_status": "failed",
                "image_id": None,
                "local_path": None,
                "download_error": str(error),
            }


def read_download_log(path):
    if not path.exists():
        return {}
    lines = path.read_text(encoding="utf-8").splitlines()
    rows = []
    for index, line in enumerate(lines):
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError:
            if index != len(lines) - 1:
                raise ValueError("Download log hỏng ở giữa file") from None
            print("Bỏ dòng log cuối chưa ghi xong do lần chạy trước bị ngắt")
    write_jsonl(path, rows)
    return {row["image_url"]: row for row in rows}


def download_records(
    records_path,
    output_dir,
    limit=None,
    workers=None,
    timeout=None,
    max_bytes=None,
    retries=None,
):
    settings = get_baseline_settings()
    workers = settings.workers if workers is None else workers
    timeout = settings.timeout if timeout is None else timeout
    max_bytes = settings.max_bytes if max_bytes is None else max_bytes
    retries = settings.retries if retries is None else retries
    if workers < 1 or timeout <= 0 or max_bytes < 1 or retries < 0:
        raise ValueError("Tham số tải ảnh không hợp lệ")
    if limit is not None and limit < 1:
        raise ValueError("limit phải lớn hơn 0")
    output_dir = Path(output_dir)
    image_dir = output_dir / "images"
    image_dir.mkdir(parents=True, exist_ok=True)
    records = read_jsonl(records_path)
    journal = output_dir / "download-log.jsonl"
    previous = read_download_log(journal)
    urls = list(dict.fromkeys(row["image_url"] for row in records))
    selected = urls[:limit] if limit else urls
    results = {}
    for url in urls:
        if url in previous and reusable(previous[url]):
            results[url] = previous[url]
        elif url in previous and previous[url]["download_status"] == "failed":
            results[url] = previous[url]
    pending = [url for url in selected if results.get(url, {}).get("download_status") != "success"]
    with httpx.Client(timeout=timeout, trust_env=False) as client:

        def run(url):
            return download_image(client, url, image_dir, max_bytes, retries)

        with ThreadPoolExecutor(max_workers=workers) as pool:
            with journal.open("a", encoding="utf-8") as log:
                for index, result in enumerate(pool.map(run, pending), start=1):
                    results[result["image_url"]] = result
                    log.write(json.dumps(result, ensure_ascii=False) + "\n")
                    log.flush()
                    print(f"Tải {index}/{len(pending)}: {result['download_status']}", flush=True)
    enriched = []
    for record in records:
        result = results.get(record["image_url"], {"download_status": "pending"})
        enriched.append({**record, **result})
    write_jsonl(output_dir / "downloaded-records.jsonl", enriched)
    write_jsonl(
        output_dir / "download-errors.jsonl",
        [row for row in results.values() if row["download_status"] == "failed"],
    )
    write_json(
        output_dir / "download-settings.json",
        {
            "timeout": timeout,
            "max_bytes": max_bytes,
            "max_pixels": settings.max_pixels,
            "workers": workers,
            "retries": retries,
            "limit": limit,
        },
    )
    print(
        f"URL thành công: {sum(r['download_status'] == 'success' for r in results.values())}; "
        f"URL lỗi: {sum(r['download_status'] == 'failed' for r in results.values())}"
    )
    return enriched
