import argparse
from io import BytesIO
from pathlib import Path

import httpx
from PIL import Image

from image_search.adapters.object_storage.local import LocalObjectStorage
from image_search.config import get_settings


def main() -> None:
    parser = argparse.ArgumentParser(description="Decode/store fixture and optionally probe API")
    parser.add_argument("--api-url")
    args = parser.parse_args()
    fixture = Path("assets/sample-images/fixture.ppm").read_bytes()
    with Image.open(BytesIO(fixture)) as image:
        image.load()
        assert image.size == (2, 2)
    storage = LocalObjectStorage(get_settings().storage_root)
    digest = storage.put("smoke/fixture.ppm", fixture)
    assert storage.read("smoke/fixture.ppm") == fixture
    print(f"Fixture decoded and stored: sha256={digest}")
    if args.api_url:
        response = httpx.get(args.api_url.rstrip("/") + "/health/ready", timeout=15)
        response.raise_for_status()
        print("API readiness:", response.json())
