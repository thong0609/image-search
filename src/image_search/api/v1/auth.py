"""Account endpoints; bearer access never falls back to the refresh cookie."""

import time
from collections import defaultdict, deque
from datetime import UTC
from threading import Lock
from typing import Annotated, Literal
from uuid import UUID

import sqlalchemy as sa
from fastapi import APIRouter, Depends, Header, Request, Response
from pydantic import BaseModel, ConfigDict, Field, field_validator

from image_search.adapters.postgres.schema import users
from image_search.auth.service import fail, public_user

router = APIRouter(prefix="/v1", tags=["accounts"])


def auth_service(request: Request):
    return request.app.state.auth


Auth = Annotated[object, Depends(auth_service)]


def current_user(request: Request, auth: Auth):
    value = request.headers.get("authorization", "")
    if not value.startswith("Bearer "):
        fail("UNAUTHENTICATED", "Vui lòng đăng nhập.")
    return auth.authenticate(value[7:])


User = Annotated[dict, Depends(current_user)]


def admin_user(user: User):
    if user["role"] != "admin":
        fail("FORBIDDEN_ROLE", "Chỉ quản trị viên được thực hiện thao tác này.", 403)
    return user


Admin = Annotated[dict, Depends(admin_user)]


class Body(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Login(Body):
    email: str = Field(min_length=3, max_length=254)
    password: str = Field(min_length=1, max_length=1024)

    @field_validator("email")
    @classmethod
    def email_format(cls, value):
        value = value.strip().casefold()
        if value.count("@") != 1 or any(c.isspace() for c in value):
            raise ValueError("Email không hợp lệ")
        return value


class Password(Body):
    current_password: str = Field(min_length=1, max_length=1024)
    new_password: str = Field(min_length=12, max_length=1024)


class CreateUser(Body):
    email: str = Field(min_length=3, max_length=254)
    display_name: str = Field(min_length=1, max_length=100)
    initial_password: str = Field(min_length=12, max_length=1024)
    role: Literal["user", "admin"] = "user"

    @field_validator("email")
    @classmethod
    def email_format(cls, value):
        return Login.email_format(value)

    @field_validator("display_name")
    @classmethod
    def name_not_blank(cls, value):
        if not value.strip():
            raise ValueError("Tên không được để trống")
        return value.strip()


class UpdateUser(Body):
    display_name: str | None = Field(default=None, min_length=1, max_length=100)
    role: Literal["user", "admin"] | None = None
    status: Literal["active", "disabled"] | None = None

    @field_validator("display_name")
    @classmethod
    def name_not_blank(cls, value):
        return CreateUser.name_not_blank(value) if value is not None else value


class LoginLimiter:
    def __init__(self):
        self.entries = defaultdict(deque)
        self.lock = Lock()

    def check(self, key):
        now = time.monotonic()
        with self.lock:
            for stale in [k for k, v in self.entries.items() if not v or v[-1] < now - 60]:
                del self.entries[stale]
            entries = self.entries[key]
            while entries and entries[0] < now - 60:
                entries.popleft()
            if len(entries) >= 10:
                fail("RATE_LIMITED", "Quá nhiều lần đăng nhập. Hãy đợi một phút.", 429)
            entries.append(now)


def cookie_name(auth):
    return "__Secure-refresh" if auth.settings.auth_cookie_secure else "refresh_local"


def browser_auth(request, auth):
    if (
        request.headers.get("origin") not in auth.settings.auth_origins
        or request.headers.get("x-auth-request") != "1"
        or request.headers.get("content-type", "").split(";")[0] != "application/json"
    ):
        fail("AUTH_ORIGIN_REJECTED", "Yêu cầu đăng nhập không hợp lệ.", 403)


def set_cookie(response, auth, secret, deadline):
    response.set_cookie(
        cookie_name(auth),
        secret,
        expires=deadline.astimezone(UTC),
        httponly=True,
        secure=auth.settings.auth_cookie_secure,
        samesite="strict",
        path="/v1/auth",
    )
    response.headers["Cache-Control"] = "no-store"


def clear_cookie(response, auth):
    response.delete_cookie(
        cookie_name(auth),
        path="/v1/auth",
        secure=auth.settings.auth_cookie_secure,
        httponly=True,
        samesite="strict",
    )
    response.headers["Cache-Control"] = "no-store"


@router.post("/auth/login")
def login(body: Login, request: Request, response: Response, auth: Auth):
    browser_auth(request, auth)
    request.app.state.login_limiter.check(request.client.host if request.client else "unknown")
    result, secret, deadline = auth.login(body.email, body.password)
    set_cookie(response, auth, secret, deadline)
    return result


@router.post("/auth/refresh")
def refresh(body: Body, request: Request, response: Response, auth: Auth):
    browser_auth(request, auth)
    result, secret, deadline = auth.refresh(request.cookies.get(cookie_name(auth), ""))
    set_cookie(response, auth, secret, deadline)
    return result


@router.post("/auth/logout")
def logout(body: Body, request: Request, response: Response, auth: Auth):
    browser_auth(request, auth)
    auth.logout(request.cookies.get(cookie_name(auth), ""))
    clear_cookie(response, auth)
    return {"logged_out": True}


@router.get("/auth/me")
def me(user: User):
    return public_user(user)


@router.post("/auth/change-password")
def change_password(body: Password, response: Response, user: User, auth: Auth):
    auth.change_password(user["id"], body.current_password, body.new_password)
    clear_cookie(response, auth)
    return {"logged_out": True}


@router.post("/auth/logout-all")
def logout_all(body: Body, response: Response, user: User, auth: Auth):
    with auth.engine.begin() as conn:
        conn.execute(sa.select(users.c.id).where(users.c.id == user["id"]).with_for_update())
        auth.revoke_all(conn, user["id"])
    clear_cookie(response, auth)
    return {"logged_out": True}


@router.post("/admin/users", status_code=201)
def create_user(body: CreateUser, admin: Admin, auth: Auth):
    return auth.create_user(
        body.email, body.display_name.strip(), body.initial_password, body.role, admin["id"]
    )


@router.get("/admin/users")
def list_users(admin: Admin, auth: Auth, limit: int = 50, cursor: UUID | None = None):
    if not 1 <= limit <= 100:
        fail("INVALID_LIMIT", "Giới hạn phải từ 1 đến 100.", 422)
    query = sa.select(users).order_by(users.c.id).limit(limit + 1)
    if cursor:
        query = query.where(users.c.id > cursor)
    with auth.engine.connect() as conn:
        rows = conn.execute(query).mappings().all()
    return {
        "items": [public_user(r) for r in rows[:limit]],
        "next_cursor": str(rows[limit - 1]["id"]) if len(rows) > limit else None,
    }


@router.patch("/admin/users/{uid}")
def update_user(
    uid: UUID,
    body: UpdateUser,
    admin: Admin,
    auth: Auth,
    if_match: Annotated[str | None, Header()] = None,
):
    if if_match is None:
        fail("PRECONDITION_REQUIRED", "Thiếu phiên bản tài khoản.", 428)
    try:
        revision = int(if_match.strip('"'))
    except ValueError:
        fail("STALE_VERSION", "Phiên bản không hợp lệ.", 409)
    changes = body.model_dump(exclude_unset=True)
    if not changes or any(v is None for v in changes.values()):
        fail("INVALID_UPDATE", "Cần trường cập nhật hợp lệ.", 422)
    return auth.update_user(uid, revision, changes, admin["id"])
