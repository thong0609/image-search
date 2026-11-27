"""JWT access and rotating refresh families; PostgreSQL serializes account changes."""

import hashlib
import secrets
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import jwt
import sqlalchemy as sa
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError
from fastapi import HTTPException

from image_search.adapters.postgres.schema import audit_events, users
from image_search.adapters.postgres.schema import refresh_tokens as tokens

PASSWORDS = PasswordHasher()
DUMMY_HASH = PASSWORDS.hash(secrets.token_urlsafe(32))


def fail(code, message, status=401):
    raise HTTPException(status, {"code": code, "message": message})


def token_hash(value):
    return hashlib.sha256(value.encode()).hexdigest()


def public_user(row):
    return {
        "id": str(row["id"]),
        "email": row["email_normalized"],
        **{k: row[k] for k in ("display_name", "role", "status", "revision")},
    }


def verify_password(encoded, password):
    try:
        return PASSWORDS.verify(encoded, password)
    except (VerificationError, InvalidHashError):
        return False


class AuthService:
    def __init__(self, engine, settings):
        self.engine, self.settings = engine, settings

    def key(self):
        path = self.settings.auth_private_key
        if not path.is_file():
            fail("AUTH_NOT_CONFIGURED", "Chưa cấu hình khóa đăng nhập.", 503)
        return path.read_bytes()

    def access(self, user, family):
        now = datetime.now(UTC)
        return jwt.encode(
            {
                "iss": "image-search",
                "aud": "image-search-web",
                "sub": str(user["id"]),
                "iat": now,
                "nbf": now,
                "exp": now + timedelta(seconds=900),
                "jti": str(uuid4()),
                "token_use": "access",
                "family_id": str(family),
                "auth_version": user["auth_version"],
            },
            self.key(),
            algorithm="RS256",
            headers={"typ": "at+jwt", "kid": "local-v1"},
        )

    def issue(self, conn, user, parent=None, root=None):
        secret, tid = secrets.token_urlsafe(48), uuid4()
        family = root["id"] if root else tid
        deadline = root["expires_at"] if root else datetime.now(UTC) + timedelta(days=7)
        conn.execute(
            tokens.insert().values(
                id=tid,
                user_id=user["id"],
                family_id=family,
                parent_id=parent,
                token_hash=token_hash(secret),
                auth_version=user["auth_version"],
                expires_at=deadline,
            )
        )
        return (
            {
                "access_token": self.access(user, family),
                "token_type": "Bearer",
                "expires_in": 900,
                "user": public_user(user),
            },
            secret,
            deadline,
        )

    def login(self, email, password):
        with self.engine.begin() as conn:
            user = (
                conn.execute(
                    sa.select(users)
                    .where(users.c.email_normalized == email.strip().casefold())
                    .with_for_update()
                )
                .mappings()
                .first()
            )
            valid = verify_password(user["password_hash"] if user else DUMMY_HASH, password)
            if not valid or not user or user["status"] != "active":
                fail("INVALID_CREDENTIALS", "Email hoặc mật khẩu không đúng.")
            return self.issue(conn, user)

    def locked_token(self, conn, secret):
        row = (
            conn.execute(sa.select(tokens).where(tokens.c.token_hash == token_hash(secret)))
            .mappings()
            .first()
        )
        if not row:
            return None, None, None
        user = (
            conn.execute(sa.select(users).where(users.c.id == row["user_id"]).with_for_update())
            .mappings()
            .one()
        )
        root = (
            conn.execute(sa.select(tokens).where(tokens.c.id == row["family_id"]).with_for_update())
            .mappings()
            .one()
        )
        row = (
            conn.execute(sa.select(tokens).where(tokens.c.id == row["id"]).with_for_update())
            .mappings()
            .one()
        )
        return user, root, row

    def refresh(self, secret):
        reused = False
        with self.engine.begin() as conn:
            user, root, row = self.locked_token(conn, secret)
            now = datetime.now(UTC)
            if (
                not row
                or root["revoked_at"]
                or root["expires_at"] <= now
                or user["status"] != "active"
                or row["auth_version"] != user["auth_version"]
            ):
                fail("INVALID_REFRESH_TOKEN", "Vui lòng đăng nhập lại.")
            if row["consumed_at"] or row["revoked_at"]:
                conn.execute(
                    tokens.update()
                    .where(tokens.c.id == root["id"])
                    .values(revoked_at=now, revoke_reason="reuse")
                )
                reused = True
            else:
                conn.execute(
                    tokens.update().where(tokens.c.id == row["id"]).values(consumed_at=now)
                )
                result = self.issue(conn, user, row["id"], root)
        # Commit revocation before raising; otherwise the transaction rolls it back.
        if reused:
            fail("TOKEN_REUSE_DETECTED", "Phiên đăng nhập đã bị thu hồi. Hãy đăng nhập lại.")
        return result

    def authenticate(self, token):
        from cryptography.hazmat.primitives.serialization import load_pem_private_key

        try:
            header = jwt.get_unverified_header(token)
            if header.get("typ") != "at+jwt" or header.get("kid") != "local-v1":
                raise ValueError
            payload = jwt.decode(
                token,
                load_pem_private_key(self.key(), password=None).public_key(),
                algorithms=["RS256"],
                audience="image-search-web",
                issuer="image-search",
                options={
                    "require": [
                        "exp",
                        "iat",
                        "nbf",
                        "sub",
                        "jti",
                        "family_id",
                        "auth_version",
                        "token_use",
                    ]
                },
            )
            if payload["token_use"] != "access":
                raise ValueError
            uid, fid = UUID(payload["sub"]), UUID(payload["family_id"])
        except jwt.ExpiredSignatureError:
            fail("ACCESS_TOKEN_EXPIRED", "Token đăng nhập đã hết hạn.")
        except (jwt.InvalidTokenError, ValueError, TypeError, KeyError):
            fail("INVALID_ACCESS_TOKEN", "Token đăng nhập không hợp lệ.")
        with self.engine.connect() as conn:
            user = conn.execute(sa.select(users).where(users.c.id == uid)).mappings().first()
            root = conn.execute(sa.select(tokens).where(tokens.c.id == fid)).mappings().first()
            if (
                not user
                or not root
                or root["user_id"] != uid
                or root["family_id"] != fid
                or user["status"] != "active"
                or root["revoked_at"]
                or root["expires_at"] <= datetime.now(UTC)
                or user["auth_version"] != payload["auth_version"]
            ):
                fail("TOKEN_REVOKED", "Phiên đăng nhập đã bị thu hồi.")
            return dict(user)

    def logout(self, secret):
        with self.engine.begin() as conn:
            _, root, _ = self.locked_token(conn, secret)
            if root and not root["revoked_at"]:
                conn.execute(
                    tokens.update()
                    .where(tokens.c.id == root["id"])
                    .values(revoked_at=datetime.now(UTC), revoke_reason="logout")
                )

    def revoke_all(self, conn, uid):
        conn.execute(
            tokens.update()
            .where(tokens.c.user_id == uid, tokens.c.revoked_at.is_(None))
            .values(revoked_at=datetime.now(UTC), revoke_reason="account_changed")
        )
        conn.execute(
            users.update()
            .where(users.c.id == uid)
            .values(
                auth_version=users.c.auth_version + 1,
                revision=users.c.revision + 1,
                updated_at=datetime.now(UTC),
            )
        )

    def change_password(self, uid, current, new):
        with self.engine.begin() as conn:
            user = (
                conn.execute(sa.select(users).where(users.c.id == uid).with_for_update())
                .mappings()
                .one()
            )
            if not verify_password(user["password_hash"], current):
                fail("INVALID_CREDENTIALS", "Mật khẩu hiện tại không đúng.")
            conn.execute(
                users.update().where(users.c.id == uid).values(password_hash=PASSWORDS.hash(new))
            )
            self.revoke_all(conn, uid)

    def create_user(self, email, display_name, password, role="user", actor=None):
        try:
            with self.engine.begin() as conn:
                row = (
                    conn.execute(
                        users.insert()
                        .values(
                            id=uuid4(),
                            email_normalized=email.strip().casefold(),
                            display_name=display_name,
                            password_hash=PASSWORDS.hash(password),
                            role=role,
                        )
                        .returning(users)
                    )
                    .mappings()
                    .one()
                )
                self.audit(conn, actor, "user.create", row["id"])
                return public_user(row)
        except sa.exc.IntegrityError:
            fail("EMAIL_EXISTS", "Email đã được sử dụng.", 409)

    def update_user(self, uid, revision, changes, actor):
        with self.engine.begin() as conn:
            # Serialize all role/status edits, including simultaneous last-admin demotions.
            conn.execute(sa.text("SELECT pg_advisory_xact_lock(1948601)"))
            row = (
                conn.execute(sa.select(users).where(users.c.id == uid).with_for_update())
                .mappings()
                .first()
            )
            if not row:
                fail("RESOURCE_NOT_FOUND", "Không tìm thấy tài khoản.", 404)
            if row["revision"] != revision:
                fail("STALE_VERSION", "Tài khoản đã thay đổi. Hãy tải lại.", 409)
            final = {**row, **changes}
            if (
                row["role"] == "admin"
                and row["status"] == "active"
                and (final["role"] != "admin" or final["status"] != "active")
            ):
                count = conn.scalar(
                    sa.select(sa.func.count())
                    .select_from(users)
                    .where(users.c.role == "admin", users.c.status == "active")
                )
                if count <= 1:
                    fail(
                        "LAST_ADMIN_REQUIRED", "Phải giữ ít nhất một quản trị viên hoạt động.", 409
                    )
            if any(final[k] != row[k] for k in ("role", "status")):
                self.revoke_all(conn, uid)
            else:
                changes["revision"] = row["revision"] + 1
            result = (
                conn.execute(
                    users.update()
                    .where(users.c.id == uid)
                    .values(**changes, updated_at=datetime.now(UTC))
                    .returning(users)
                )
                .mappings()
                .one()
            )
            self.audit(conn, actor, "user.update", uid)
            return public_user(result)

    @staticmethod
    def audit(conn, actor, action, resource):
        conn.execute(
            audit_events.insert().values(
                id=uuid4(),
                actor_id=actor,
                action=action,
                resource_type="user",
                resource_id=str(resource),
                safe_context={},
            )
        )
