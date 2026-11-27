"""Real PostgreSQL transactions in a disposable schema; no production rows touched."""

import os
from uuid import UUID, uuid4

import pytest
import sqlalchemy as sa
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi import HTTPException
from fastapi.testclient import TestClient

from image_search.adapters.postgres.database import create_database_engine
from image_search.adapters.postgres.schema import metadata
from image_search.auth.service import AuthService
from image_search.config import Settings
from image_search.main import create_app

pytestmark = pytest.mark.skipif(
    os.getenv("RUN_AUTH_INTEGRATION") != "1", reason="Requires local PostgreSQL"
)
PASSWORD = "test-only-password-1234"


@pytest.fixture
def accounts(tmp_path):
    settings = Settings(auth_private_key=tmp_path / "private.pem")
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    settings.auth_private_key.write_bytes(
        key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        )
    )
    base = create_database_engine(settings)
    schema = "test_auth_" + uuid4().hex
    with base.begin() as conn:
        conn.execute(sa.text(f'CREATE SCHEMA "{schema}"'))
    engine = sa.create_engine(
        settings.database_url.get_secret_value(),
        connect_args={"options": f"-csearch_path={schema}"},
    )
    metadata.create_all(engine)
    service = AuthService(engine, settings)
    try:
        yield service, settings
    finally:
        engine.dispose()
        with base.begin() as conn:
            conn.execute(sa.text(f'DROP SCHEMA "{schema}" CASCADE'))
        base.dispose()


def add(service, email="user@example.com", role="user"):
    return service.create_user(email, "Test", PASSWORD, role)


def test_csv_admission_preview_idempotency_and_retry(accounts):
    import csv
    import io

    from image_search.baseline.records import REQUIRED_COLUMNS
    from image_search.ingestion.service import Imports
    from image_search.library import COLLECTION, Library

    service, settings = accounts
    admin = add(service, role="admin")
    library = Library(service.engine, settings.auth_private_key)
    library.bootstrap(
        {"index_sha256": "x", "search_metadata_sha256": "m", "config": {}, "image_ids": ["a"]}
    )
    stream = io.StringIO()
    writer = csv.DictWriter(stream, fieldnames=REQUIRED_COLUMNS)
    writer.writeheader()
    writer.writerow(
        {
            k: {
                "entity_id": "E",
                "entity_name": "Place",
                "approve": "yes",
                "image_url": "https://example.com/image.jpg",
            }.get(k, "")
            for k in REQUIRED_COLUMNS
        }
    )
    data = stream.getvalue().encode()
    imports = Imports(service.engine)
    root = imports.submit(data, COLLECTION, UUID(admin["id"]), "same-request")
    assert imports.submit(data, COLLECTION, UUID(admin["id"]), "same-request") == root
    report = imports.report(UUID(root), True)
    assert report["counts"] == {"pending": 1}
    with pytest.raises(HTTPException, match="IDEMPOTENCY_CONFLICT"):
        imports.submit(data + b"\n", COLLECTION, UUID(admin["id"]), "same-request")
    app = create_app(settings)
    from image_search.api.v1.auth import admin_user

    app.dependency_overrides[admin_user] = lambda: {"id": UUID(admin["id"]), "role": "admin"}
    with TestClient(app) as client:
        app.state.auth = service
        preview = client.post(
            "/v1/admin/imports/preview", files={"file": ("data.csv", data, "text/csv")}
        )
        assert preview.status_code == 200, preview.text
        assert preview.json()["counts"] == {"pending": 1}
