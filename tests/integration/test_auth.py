"""Real PostgreSQL transactions in a disposable schema; no production rows touched."""

import os
from concurrent.futures import ThreadPoolExecutor
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
    settings = Settings(auth_private_key=tmp_path / "private.pem", preload_search=False)
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


def test_rotate_reuse_revokes_access_and_child(accounts):
    service, _ = accounts
    add(service)
    first, refresh, _ = service.login("user@example.com", PASSWORD)
    second, child, _ = service.refresh(refresh)
    assert service.authenticate(first["access_token"])["role"] == "user"
    with pytest.raises(HTTPException, match="TOKEN_REUSE_DETECTED"):
        service.refresh(refresh)
    for token in (first["access_token"], second["access_token"]):
        with pytest.raises(HTTPException, match="TOKEN_REVOKED"):
            service.authenticate(token)
    with pytest.raises(HTTPException, match="INVALID_REFRESH_TOKEN"):
        service.refresh(child)


def test_logout_and_password_revoke_all(accounts):
    service, _ = accounts
    account = add(service)
    first, refresh, _ = service.login("user@example.com", PASSWORD)
    service.logout(refresh)
    service.logout(refresh)
    with pytest.raises(HTTPException, match="TOKEN_REVOKED"):
        service.authenticate(first["access_token"])
    second, _, _ = service.login("user@example.com", PASSWORD)
    service.change_password(UUID(account["id"]), PASSWORD, "new-test-password-1234")
    with pytest.raises(HTTPException, match="TOKEN_REVOKED"):
        service.authenticate(second["access_token"])
    with pytest.raises(HTTPException, match="INVALID_CREDENTIALS"):
        service.login("user@example.com", PASSWORD)


def test_last_admin_and_revision_guard(accounts):
    service, _ = accounts
    admin = add(service, role="admin")
    uid = UUID(admin["id"])
    with pytest.raises(HTTPException, match="LAST_ADMIN_REQUIRED"):
        service.update_user(uid, 1, {"status": "disabled"}, uid)
    second = add(service, "second@example.com", "admin")
    issued, _, _ = service.login("user@example.com", PASSWORD)
    result = service.update_user(uid, 1, {"role": "user"}, UUID(second["id"]))
    assert result["revision"] == 2
    with pytest.raises(HTTPException, match="TOKEN_REVOKED"):
        service.authenticate(issued["access_token"])
    with pytest.raises(HTTPException, match="STALE_VERSION"):
        service.update_user(uid, 1, {"display_name": "Other"}, UUID(second["id"]))


def test_concurrent_refresh_only_rotates_once(accounts):
    service, _ = accounts
    add(service)
    _, refresh, _ = service.login("user@example.com", PASSWORD)

    def rotate():
        try:
            return service.refresh(refresh)[0]
        except HTTPException as error:
            return error.detail["code"]

    with ThreadPoolExecutor(2) as pool:
        results = list(pool.map(lambda _: rotate(), range(2)))
    assert sum(isinstance(result, dict) for result in results) == 1
    assert "TOKEN_REUSE_DETECTED" in results


def test_http_policy_and_role_separation(accounts):
    service, settings = accounts
    add(service)
    app = create_app(settings)
    with TestClient(app) as client:
        app.state.auth = service
        assert (
            client.post(
                "/v1/auth/login", json={"email": "user@example.com", "password": PASSWORD}
            ).status_code
            == 403
        )
        headers = {"Origin": "http://127.0.0.1:3000", "X-Auth-Request": "1"}
        result = client.post(
            "/v1/auth/login",
            headers=headers,
            json={"email": "user@example.com", "password": PASSWORD},
        )
        assert result.status_code == 200
        assert "httponly" in result.headers["set-cookie"].lower()
        assert "samesite=strict" in result.headers["set-cookie"].lower()
        assert "refresh" not in result.json()
        assert result.headers["cache-control"] == "no-store"
        assert client.get("/v1/auth/me").status_code == 401
        bearer = {"Authorization": "Bearer " + result.json()["access_token"]}
        assert client.get("/v1/auth/me", headers=bearer).status_code == 200
        rotated = client.post("/v1/auth/refresh", headers=headers, json={})
        assert rotated.status_code == 200
        assert "httponly" in rotated.headers["set-cookie"].lower()
        assert client.get("/v1/admin/users", headers=bearer).status_code == 403
        client.post("/v1/auth/logout", headers=headers, json={})
        assert client.get("/v1/auth/me", headers=bearer).status_code == 401
