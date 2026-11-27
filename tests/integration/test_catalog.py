"""Real PostgreSQL transactions in a disposable schema; no production rows touched."""

import os
from uuid import UUID, uuid4

import pytest
import sqlalchemy as sa
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi import HTTPException

from image_search.adapters.postgres.database import create_database_engine
from image_search.adapters.postgres.schema import metadata
from image_search.auth.service import AuthService
from image_search.config import Settings

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


def test_library_snapshot_checks_owner_deletion_and_index(accounts):
    from image_search.library import Library

    service, settings = accounts
    library = Library(service.engine, settings.auth_private_key)
    index = {
        "index_sha256": "index",
        "search_metadata_sha256": "metadata",
        "config": {},
        "image_ids": ["a", "b", "c"],
    }
    library.bootstrap(index)
    assert library.visible() == {"a", "b", "c"}
    owner = "a" * 32
    sid = library.save_search(
        {
            "query": "test",
            "groups": [{"id": "t1", "items": [{"id": iid} for iid in ["a", "b", "c"]]}],
        },
        owner,
        {},
    )
    first = library.page(UUID(sid), owner, 0, 1)
    assert first["groups"][0]["items"] == [{"id": "a", "record_id": None}]
    cursor = first["next_cursor"]
    with pytest.raises(HTTPException, match="INVALID_CURSOR"):
        library.parse_cursor(cursor + "x", owner)
    with pytest.raises(HTTPException, match="INVALID_CURSOR"):
        library.parse_cursor(cursor, "b" * 32)
    admin = add(service, role="admin")
    library.delete("b", 1, UUID(admin["id"]))
    assert library.visible() == {"a", "c"}
    with pytest.raises(HTTPException, match="RESOURCE_NOT_FOUND"):
        library.require_visible("b")
    page = library.page(
        *library.parse_cursor(cursor, owner)[:1], owner, library.parse_cursor(cursor, owner)[1], 2
    )
    assert page["groups"][0]["items"] == [{"id": "c", "record_id": None}]
    library.bootstrap(index)
    assert "b" not in library.visible()  # Restart/bootstrap never revives a tombstone.
