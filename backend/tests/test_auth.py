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


async def test_password_hashing_does_not_block_the_event_loop(client, monkeypatch) -> None:
    """A burst of sign-ins must not freeze every other request in the process.

    Argon2 costs ~110 ms per check, so running it inline means a handful of simultaneous logins is a
    self-inflicted outage: measured before the fix, 16 concurrent wrong passwords held `/healthz` for
    **1.24 s**, and a CI e2e run lost 21 mobile tests to 20 s timeouts in exactly that window
    (`settings.spec.ts` reported `login failed for manager@brokerhub.test`).

    The hasher is replaced with a *blocking* sleep, so this asserts **where** it runs, not how fast the
    machine is: on the event loop `/healthz` waits for the whole burst, in a worker thread it does not.
    """
    import asyncio
    import time

    from app.core import security
    from app.services import auth

    def slow_verify(password: str, hashed: str) -> bool:  # same signature as the real one
        time.sleep(0.4)
        return False

    monkeypatch.setattr(security, "verify_password", slow_verify)
    auth.clear_failures("rep_a@brokerhub.test|local")
    try:
        # 4 concurrent failures stay under LOGIN_MAX_ATTEMPTS (5) — 1.6 s of hashing if it ran inline
        logins = [
            asyncio.create_task(client.post("/api/v1/auth/login", json={"email": "rep_a@brokerhub.test", "password": "x"}))
            for _ in range(4)
        ]
        await asyncio.sleep(0.05)  # let them all reach the hasher
        started = time.perf_counter()
        health = await asyncio.wait_for(client.get("/healthz"), timeout=5)
        waited_ms = (time.perf_counter() - started) * 1000
        assert [response.status_code for response in await asyncio.gather(*logins)] == [401] * 4
        assert health.status_code == 200
        assert waited_ms < 400, f"/healthz waited {waited_ms:.0f} ms behind the password hashes"
    finally:
        auth.clear_failures("rep_a@brokerhub.test|local")
