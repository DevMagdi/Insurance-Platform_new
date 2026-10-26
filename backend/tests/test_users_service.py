"""Screen 14 (users & roles) end to end: the admin toggles must change what other people can do."""

from __future__ import annotations

from uuid import UUID

from app.domain.permissions import ALL_PERMISSIONS

from tests.helpers import login

ADMIN = "admin@brokerhub.test"
PASSWORD = "Test-Pass-2026"


async def test_create_rep_with_scopes_and_login(client, ids) -> None:
    async with login(client, ADMIN) as h:
        created = await client.post(
            "/api/v1/users",
            headers=h,
            json={
                "email": "new.rep@brokerhub.test",
                "password": PASSWORD,
                "full_name": "زميلة جديدة",
                "role_code": "sales_rep",
                "mobile": "01001234567",
                "scopes": [{"type": "client", "id": ids["clients"]["ألف"]}],
            },
        )
        assert created.status_code == 201, created.text
        body = created.json()
        assert body["role"] == "sales_rep"

        listed = await client.get("/api/v1/users", headers=h)
        assert listed.status_code == 200
        row = next(u for u in listed.json() if u["id"] == body["id"])
        assert row["role"] == "sales_rep"
        # the mobile went through the one shared normaliser, so it is stored as E.164
        assert row["mobile"] == "+201001234567"
        assert {s["id"] for s in row["scopes"]} == {ids["clients"]["ألف"]}

    # the new account can log in, and its scope is the seeded union, not the whole office
    async with login(client, "new.rep@brokerhub.test") as rep:
        clients = await client.get("/api/v1/clients", headers=rep)
        assert clients.status_code == 200
        names = {c["name"] for c in clients.json()["items"]}
        assert names == {"شركة ألف"}
        assert (await client.get("/api/v1/users", headers=rep)).status_code == 403


async def test_duplicate_email_unknown_role_and_weak_password_are_refused(client) -> None:
    async with login(client, ADMIN) as h:
        duplicate = await client.post(
            "/api/v1/users",
            headers=h,
            json={"email": "rep_a@brokerhub.test", "password": PASSWORD, "full_name": "تكرار", "role_code": "sales_rep"},
        )
        assert duplicate.status_code == 409
        unknown_role = await client.post(
            "/api/v1/users",
            headers=h,
            json={"email": "ghost@brokerhub.test", "password": PASSWORD, "full_name": "شبح", "role_code": "vice_president"},
        )
        assert unknown_role.status_code == 422
        assert unknown_role.json()["code"] == "validation_failed"
        weak = await client.post(
            "/api/v1/users",
            headers=h,
            json={"email": "weak@brokerhub.test", "password": "12345", "full_name": "ضعيف", "role_code": "sales_rep"},
        )
        assert weak.status_code == 422  # rejected by the request model before the service runs


async def test_deactivate_revokes_access_and_self_lockout_is_blocked(client, ids) -> None:
    async with login(client, ADMIN) as h:
        created = await client.post(
            "/api/v1/users",
            headers=h,
            json={"email": "temp@brokerhub.test", "password": PASSWORD, "full_name": "مؤقت", "role_code": "customer_service"},
        )
        temp_id = created.json()["id"]

        # the account works first, so the revocation below is the thing under test
    async with login(client, "temp@brokerhub.test") as temp:
        assert (await client.get("/api/v1/requests", headers=temp)).status_code == 200

    async with login(client, ADMIN) as h:
        off = await client.patch(f"/api/v1/users/{temp_id}", headers=h, json={"is_active": False})
        assert off.status_code == 200
        assert off.json()["is_active"] is False
        refused = await client.post("/api/v1/auth/login", json={"email": "temp@brokerhub.test", "password": PASSWORD})
        assert refused.status_code in (401, 403)

        # an admin cannot lock themselves out of their own instance
        me = await client.get("/api/v1/auth/me", headers=h)
        self_off = await client.patch(f"/api/v1/users/{me.json()['id']}", headers=h, json={"is_active": False})
        assert self_off.status_code == 409


async def test_refresh_rotates_and_logout_revokes_the_family(client) -> None:
    """The refresh cookie rotates; logging out kills the family, so the last token stops working."""
    async with login(client, "cs@brokerhub.test"):
        first = await client.post("/api/v1/auth/refresh")
        assert first.status_code == 200
        token_a = first.json()["access_token"]
        second = await client.post("/api/v1/auth/refresh")
        assert second.status_code == 200
        token_b = second.json()["access_token"]
        assert token_a != token_b
        # the newest access token keeps working until logout
        assert (await client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token_b}"})).status_code == 200
        assert (await client.post("/api/v1/auth/logout", headers={"Authorization": f"Bearer {token_b}"})).status_code == 204
        assert (await client.post("/api/v1/auth/refresh")).status_code == 403


async def test_password_change_forces_a_fresh_login(client) -> None:
    async with login(client, ADMIN) as h:
        created = await client.post(
            "/api/v1/users",
            headers=h,
            json={"email": "rotate@brokerhub.test", "password": PASSWORD, "full_name": "تدوير", "role_code": "customer_service"},
        )
        user_id = created.json()["id"]
        changed = await client.patch(f"/api/v1/users/{user_id}", headers=h, json={"password": "Second-Pass-2026"})
        assert changed.status_code == 200

    assert (await client.post("/api/v1/auth/login", json={"email": "rotate@brokerhub.test", "password": PASSWORD})).status_code in (
        401,
        403,
    )
    async with login(client, "rotate@brokerhub.test", "Second-Pass-2026"):
        pass


async def test_roles_grid_and_permission_toggle_changes_access(client) -> None:
    async with login(client, ADMIN) as h:
        roles = await client.get("/api/v1/roles", headers=h)
        assert roles.status_code == 200
        grid = roles.json()
        assert {r["code"] for r in grid} >= {"system_admin", "sales_manager", "sales_rep", "customer_service", "client_owner"}
        rep_role = next(r for r in grid if r["code"] == "sales_rep")
        assert "leads.view_own" in rep_role["permissions"]
        assert "clients.view_all" not in rep_role["permissions"]

        permissions = await client.get("/api/v1/permissions", headers=h)
        assert permissions.status_code == 200
        # every slug the domain declares is offered in the UI grid — no orphan rows
        assert {p["code"] for p in permissions.json()} == set(ALL_PERMISSIONS)
        group = {p["group"] for p in permissions.json()}
        assert {"leads", "clients", "requests"} <= group

        # grant the rep role a manager-only permission, then take it away again
        granted = await client.put(
            f"/api/v1/roles/{rep_role['id']}/permissions",
            headers=h,
            json={"permissions": sorted(set(rep_role["permissions"]) | {"clients.view_all"})},
        )
        assert granted.status_code == 200
        assert "clients.view_all" in granted.json()["permissions"]

    async with login(client, "rep_a@brokerhub.test") as rep:
        everyone = await client.get("/api/v1/clients", headers=rep)
        assert everyone.status_code == 200
        assert {c["name"] for c in everyone.json()["items"]} == {"شركة ألف", "شركة باء"}

    async with login(client, ADMIN) as h:
        revoked = await client.put(
            f"/api/v1/roles/{rep_role['id']}/permissions",
            headers=h,
            json={"permissions": rep_role["permissions"]},
        )
        assert "clients.view_all" not in revoked.json()["permissions"]


async def test_unknown_user_and_role_answer_404(client) -> None:
    async with login(client, ADMIN) as h:
        missing = UUID(int=0)
        assert (await client.patch(f"/api/v1/users/{missing}", headers=h, json={"full_name": "لا شيء"})).status_code == 404
        assert (await client.put(f"/api/v1/users/{missing}/scopes", headers=h, json={"scopes": []})).status_code == 404
        assert (
            await client.put(f"/api/v1/roles/{missing}/permissions", headers=h, json={"permissions": ["leads.view_own"]})
        ).status_code == 404
