from __future__ import annotations

import pytest

from tests.helpers import login

pytestmark = pytest.mark.integration


async def test_login_returns_access_token_and_profile(client, ids) -> None:
    async with login(client, "rep_a@brokerhub.test") as h:
        me = (await client.get("/api/v1/auth/me", headers=h)).json()
        assert me["role"] == "sales_rep"
        assert me["scope_mode"] == "owner"
        assert "leads.view_own" in me["permissions"]
        assert "leads.view_all" not in me["permissions"]


async def test_wrong_password_is_401(client) -> None:
    response = await client.post("/api/v1/auth/login", json={"email": "rep_a@brokerhub.test", "password": "nope"})
    assert response.status_code == 401
    assert response.json()["code"] == "unauthorized"


async def test_brute_force_lockout(client) -> None:
    from app.core.config import get_settings
    from app.services import auth

    auth.clear_failures("rep_a@brokerhub.test|local")
    limit = get_settings().LOGIN_MAX_ATTEMPTS
    for _ in range(limit):
        assert (await client.post("/api/v1/auth/login", json={"email": "rep_a@brokerhub.test", "password": "x"})).status_code == 401
    locked = await client.post("/api/v1/auth/login", json={"email": "rep_a@brokerhub.test", "password": "x"})
    assert locked.status_code == 429
    assert "locked" in locked.json()["message"].lower()
    auth.clear_failures("rep_a@brokerhub.test|local")


async def test_refresh_rotates_and_invalidates_reuse(client) -> None:
    login_response = await client.post("/api/v1/auth/login", json={"email": "manager@brokerhub.test", "password": PASSWORD})
    refresh_cookie = login_response.cookies.get("bh_refresh")
    assert refresh_cookie, "refresh token must be an HttpOnly cookie"
    first = await client.post("/api/v1/auth/refresh", cookies={"bh_refresh": refresh_cookie})
    assert first.status_code == 200
    replay = await client.post("/api/v1/auth/refresh", cookies={"bh_refresh": refresh_cookie})
    assert replay.status_code == 401, "a rotated refresh token must not be reusable"


async def test_health_and_readiness(client) -> None:
    assert (await client.get("/healthz")).json() == {"status": "ok"}
    ready = await client.get("/readyz")
    assert ready.status_code == 200


from tests.conftest import PASSWORD  # noqa: E402
