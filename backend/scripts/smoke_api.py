"""End-to-end smoke over the seeded app (in-process ASGI, no server needed).

Prints each endpoint's response shape and asserts the basics. Useful in CI without Postgres
and while building the UI: `python scripts/smoke_api.py [--keys]`.
"""

from __future__ import annotations

import argparse
import json
import os
import pathlib
import sys
import tempfile
from typing import Any

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

DB = pathlib.Path(tempfile.gettempdir()) / "bh_smoke.db"
os.environ.setdefault("DATABASE_URL", f"sqlite+aiosqlite:///{DB}")
os.environ.setdefault("ENV", "dev")
os.environ.setdefault("INTEGRATIONS_DRIVER", "sim")
os.environ.setdefault("CELERY_TASK_ALWAYS_EAGER", "1")
os.environ.setdefault("MEDIA_ROOT", str(pathlib.Path(tempfile.gettempdir()) / "bh_media"))


def _prepare_db() -> None:
    import asyncio

    from app.core.db import create_dev_schema, get_sessionmaker

    asyncio.run(create_dev_schema())
    from app.seed import seed

    async def _seed() -> None:
        async with get_sessionmaker()() as session:
            await seed(session)

    asyncio.run(_seed())


def _shape(value: Any, depth: int = 0) -> Any:
    if isinstance(value, dict):
        return {k: _shape(v, depth + 1) for k, v in value.items()} if depth < 2 else "{...}"
    if isinstance(value, list):
        return [_shape(value[0], depth + 1)] if value else []
    return type(value).__name__


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--keys", action="store_true", help="print full JSON instead of shapes")
    args = parser.parse_args()

    if DB.exists():
        DB.unlink()
    _prepare_db()

    from app.main import create_app
    from fastapi.testclient import TestClient

    client = TestClient(create_app())
    failures: list[str] = []

    def check(name: str, status: int, expected: tuple[int, ...] = (200,)) -> Any:
        if status not in expected:
            failures.append(f"{name} -> {status}")
        return None

    def get(path: str, token: str | None = None, label: str | None = None) -> Any:
        headers = {"authorization": f"Bearer {token}"} if token else {}
        response = client.get(path, headers=headers)
        name = label or f"GET {path}"
        if response.status_code not in (200, 201, 204):
            failures.append(f"{name} -> {response.status_code} {response.text[:160]}")
            print(f"FAIL {name}: {response.status_code}")
            return None
        payload = response.json() if response.content else None
        print(f"ok   {name}")
        print(f"     {json.dumps(payload if args.keys else _shape(payload), ensure_ascii=False, default=str)[:600]}")
        return payload

    login = client.post("/api/v1/auth/login", json={"email": "manager@brokerhub.test", "password": "Br0kerHub!2026"})
    if login.status_code != 200:
        print(f"login failed: {login.status_code} {login.text[:200]}")
        return 1
    token = login.json()["access_token"]

    for path in [
        "/api/v1/auth/me",
        "/api/v1/dashboard/summary",
        "/api/v1/dashboard/channels",
        "/api/v1/dashboard/status-breakdown",
        "/api/v1/dashboard/recent-requests",
        "/api/v1/requests",
        "/api/v1/leads",
        "/api/v1/leads/board",
        "/api/v1/leads/stats",
        "/api/v1/sales/team",
        "/api/v1/clients",
        "/api/v1/clients/kpis",
        "/api/v1/insurers",
        "/api/v1/insurance-types",
        "/api/v1/lost-reasons",
        "/api/v1/sla-policies",
        "/api/v1/feature-flags",
        "/api/v1/notifications",
    ]:
        get(path, token)

    clients = client.get("/api/v1/clients", headers={"authorization": f"Bearer {token}"}).json()
    if clients.get("items"):
        client_id = clients["items"][0]["id"]
        get(f"/api/v1/clients/{client_id}/overview", token)
        get(f"/api/v1/clients/{client_id}/insured", token)
        get(f"/api/v1/clients/{client_id}/requests", token)

    leads = client.get("/api/v1/leads", headers={"authorization": f"Bearer {token}"}).json()
    if leads.get("items"):
        get(f"/api/v1/leads/{leads['items'][0]['id']}/activities", token)

    requests_ = client.get("/api/v1/requests", headers={"authorization": f"Bearer {token}"}).json()
    if requests_.get("items"):
        request_id = requests_["items"][0]["id"]
        get(f"/api/v1/requests/{request_id}/messages", token)
        get(f"/api/v1/requests/{request_id}/calls", token)
        get(f"/api/v1/requests/{request_id}/notes", token)

    portal_login = client.post("/api/v1/auth/login", json={"email": "owner.mantiq@company.test", "password": "Br0kerHub!2026"})
    if portal_login.status_code == 200:
        portal_token = portal_login.json()["access_token"]
        get("/api/v1/portal/overview", portal_token)
        get("/api/v1/portal/documents", portal_token)
        get("/api/v1/portal/requests", portal_token)

    # Phase-2 endpoints are flag-gated: 503 while `phase2.enabled` is off, then enabled for shape checks
    for path in ["/api/v1/policies", "/api/v1/commissions", "/api/v1/issuing-cases", "/api/v1/reports/insurer-performance"]:
        gated = client.get(path, headers={"authorization": f"Bearer {token}"})
        if gated.status_code == 503 and gated.json().get("code") == "feature_disabled":
            print(f"ok   GET {path} is feature-flagged off (503 feature_disabled)")
        else:
            failures.append(f"{path} should be flag-gated, got {gated.status_code}")

    admin_token = client.post("/api/v1/auth/login", json={"email": "admin@brokerhub.test", "password": "Br0kerHub!2026"}).json()[
        "access_token"
    ]
    admin = {"authorization": f"Bearer {admin_token}"}
    token = admin_token if False else token
    toggled = client.patch("/api/v1/feature-flags/phase2.enabled", json={"enabled": True}, headers=admin)
    if toggled.status_code == 200:
        for path in ["/api/v1/policies", "/api/v1/commissions", "/api/v1/issuing-cases", "/api/v1/reports/insurer-performance"]:
            get(path, admin_token)
        client.patch("/api/v1/feature-flags/phase2.enabled", json={"enabled": False}, headers=admin)
    else:
        failures.append(f"PATCH /api/v1/feature-flags/phase2.enabled -> {toggled.status_code}")
    for path in ["/api/v1/users", "/api/v1/roles", "/api/v1/permissions"]:
        get(path, admin_token)

    # Simulator (spec §8.4): inbound WhatsApp + inbound call
    wa = client.post("/api/v1/dev/sim/whatsapp", json={"mobile": "01001234567", "body": "عايز أزيد عدد الموظفين"})
    print(f"{'ok  ' if wa.status_code == 200 else 'FAIL'} POST /api/v1/dev/sim/whatsapp -> {wa.status_code}")
    print(f"     {wa.text[:280]}")
    call = client.post("/api/v1/dev/sim/call", json={"from_number": "01001234567", "duration_s": 95})
    print(f"{'ok  ' if call.status_code == 200 else 'FAIL'} POST /api/v1/dev/sim/call -> {call.status_code}")
    print(f"     {call.text[:280]}")
    if wa.status_code != 200:
        failures.append(f"sim whatsapp -> {wa.status_code}")
    if call.status_code != 200:
        failures.append(f"sim call -> {call.status_code}")

    # the two simulator events must land in the inbox as real requests (spec §8.4)
    if wa.status_code == 200 and call.status_code == 200:
        recent = client.get("/api/v1/requests?page_size=10&sort=created_at&order=desc", headers=admin).json()
        # the list is sorted newest-first, so take the first hit per channel (the simulator rows)
        by_channel: dict[str, dict[str, Any]] = {}
        for item in recent.get("items", []):
            if item["channel"] in {"whatsapp", "call"} and item["channel"] not in by_channel:
                by_channel[item["channel"]] = item
        if {"whatsapp", "call"} <= set(by_channel):
            print("ok   simulator → inbox: " + ", ".join(f"#{item['number']} [{item['channel']}]" for item in by_channel.values()))
        else:
            failures.append(f"simulator events missing from inbox: {sorted(by_channel)}")

        call_item = by_channel.get("call")
        if call_item:
            calls = client.get(f"/api/v1/requests/{call_item['id']}/calls", headers=admin).json()
            recording = next((row for row in calls if row.get("has_recording")), None)
            if recording is None:
                failures.append("the simulator call row carries no recording (has_recording=false)")
            else:
                url = client.get(f"/api/v1/calls/{recording['id']}/recording-url", headers=admin).json()
                print(f"ok   signed recording url issued (expires_at={url.get('expires_at')})")
                media = client.get(url["url"])
                if media.status_code == 200:
                    print(f"ok   signed media fetches ({len(media.content)} bytes)")
                else:
                    failures.append(f"signed media fetch -> {media.status_code}")
                # a rep without calls.listen must not be able to listen (spec §6.4)
                rep_token = client.post(
                    "/api/v1/auth/login", json={"email": "sara.elsayed@brokerhub.test", "password": "Br0kerHub!2026"}
                ).json()["access_token"]
                denied = client.get(f"/api/v1/calls/{recording['id']}/recording-url", headers={"authorization": f"Bearer {rep_token}"})
                if denied.status_code == 403:
                    print("ok   recording url without calls.listen -> 403")
                else:
                    failures.append(f"recording gate -> {denied.status_code}")

    print()
    if failures:
        print(f"SMOKE FAILED ({len(failures)}):")
        for line in failures:
            print(f"  - {line}")
        return 1
    print("SMOKE OK — every read endpoint answered with seeded data")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
