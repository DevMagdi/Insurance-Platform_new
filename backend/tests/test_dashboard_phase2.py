"""Dashboard KPIs are scoped; shipped modules are live with RBAC only (ADR-034)."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from app.core.db import get_sessionmaker
from app.domain.enums import ScopeType
from app.models.auth import User, UserScope
from app.models.requests import AuditLog
from sqlalchemy import select

from tests.helpers import login

ADMIN = "admin@brokerhub.test"
MANAGER = "manager@brokerhub.test"
REP_A = "rep_a@brokerhub.test"
CS = "cs@brokerhub.test"


async def test_dashboard_kpis_follow_the_scope(client, ids: dict[str, dict[str, str]]) -> None:
    """The KPI row counts exactly what the queue shows the same user — no leaked totals (§6)."""
    maker = get_sessionmaker()
    async with maker() as session:
        cs = (await session.execute(select(User).where(User.email == CS))).scalar_one()
        session.add(UserScope(user_id=cs.id, scope_type=ScopeType.CLIENT, scope_id=UUID(ids["clients"]["باء"])))
        await session.commit()

    async with login(client, MANAGER) as auth:
        for client_key, subject in (("ألف", "طلب لألف"), ("باء", "طلب لباء")):
            created = await client.post(
                "/api/v1/requests", json={"subject": subject, "client_id": ids["clients"][client_key]}, headers=auth
            )
            assert created.status_code == 201
        manager_view = await client.get("/api/v1/dashboard/summary", headers=auth)

    async with login(client, CS) as cs_auth:
        cs_view = await client.get("/api/v1/dashboard/summary", headers=cs_auth)

    manager = manager_view.json()
    scoped = cs_view.json()
    assert manager["requests_today"] == 2
    assert manager["open_requests"] == 2
    assert manager["clients_total"] == 2
    assert scoped["requests_today"] == 1  # only the client they are pinned to
    assert scoped["clients_total"] == 1


async def test_channel_and_status_breakdowns_are_shape_stable(client, ids: dict[str, dict[str, str]]) -> None:
    async with login(client, MANAGER) as auth:
        await client.post(
            "/api/v1/requests", json={"subject": "طلب للقنوات", "client_id": ids["clients"]["ألف"], "channel": "email"}, headers=auth
        )
        channels = await client.get("/api/v1/dashboard/channels?days=7", headers=auth)
        breakdown = await client.get("/api/v1/dashboard/status-breakdown", headers=auth)
        recent = await client.get("/api/v1/dashboard/recent-requests?limit=5", headers=auth)
    days = channels.json()
    assert len(days) == 7
    assert {"date", "whatsapp", "call", "email", "manual"} <= set(days[0])
    counts = {row["key"]: row for row in breakdown.json()}
    assert counts["new"]["count"] >= 1
    assert set(counts) == {"new", "in_progress", "replied", "overdue"}
    assert all("employee_name" in row and "sla_minutes_remaining" in row for row in recent.json())


async def test_seeded_scope_limits_the_queue(client, ids: dict[str, dict[str, str]]) -> None:
    """A service agent pinned to one client sees only that client's queue (§6.1 lists)."""
    maker = get_sessionmaker()
    async with maker() as session:
        cs = (await session.execute(select(User).where(User.email == CS))).scalar_one()
        session.add(UserScope(user_id=cs.id, scope_type=ScopeType.CLIENT, scope_id=UUID(ids["clients"]["باء"])))
        await session.commit()

    async with login(client, MANAGER) as auth:
        await client.post("/api/v1/requests", json={"subject": "طلب مقيد النطاق", "client_id": ids["clients"]["ألف"]}, headers=auth)
        await client.post("/api/v1/requests", json={"subject": "طلب داخل النطاق", "client_id": ids["clients"]["باء"]}, headers=auth)

    async with login(client, CS) as auth:
        inbox = await client.get("/api/v1/requests", headers=auth)
        subjects = {row["subject"] for row in inbox.json()["items"]}
    assert "طلب داخل النطاق" in subjects
    assert "طلب مقيد النطاق" not in subjects


async def test_modules_are_live_without_the_flag_and_flag_changes_stay_audited(client, ids: dict[str, dict[str, str]]) -> None:
    """ADR-034: a legacy `phase2.enabled=False` row must not gate anything — RBAC only."""
    from app.models.masters import FeatureFlag

    maker = get_sessionmaker()
    async with maker() as session:
        session.add(FeatureFlag(key="phase2.enabled", enabled=False, description="legacy row, no reader"))
        await session.commit()

    async with login(client, MANAGER) as auth:
        policies = await client.get("/api/v1/policies", headers=auth)
        assert policies.status_code == 200, policies.text
        assert policies.json()["total"] == 0
        for path in ("/api/v1/commissions", "/api/v1/issuing-cases", "/api/v1/reports/insurer-performance"):
            response = await client.get(path, headers=auth)
            assert response.status_code == 200, path

    async with login(client, REP_A) as rep_auth:
        denied = await client.patch("/api/v1/feature-flags/phase2.enabled", json={"enabled": True}, headers=rep_auth)
        assert denied.status_code == 403  # toggling needs settings.manage (admin + sales manager only)

    async with login(client, ADMIN) as auth:
        enabled = await client.patch("/api/v1/feature-flags/phase2.enabled", json={"enabled": True}, headers=auth)
        assert enabled.status_code == 200, enabled.text
        unknown = await client.patch("/api/v1/feature-flags/nope.enabled", json={"enabled": True}, headers=auth)
        assert unknown.status_code == 404
        await client.patch("/api/v1/feature-flags/phase2.enabled", json={"enabled": False}, headers=auth)
        still_live = await client.get("/api/v1/policies", headers=auth)
    assert still_live.status_code == 200  # off again — and nothing closes (ADR-034)

    async with maker() as session:
        rows = (
            (await session.execute(select(AuditLog).where(AuditLog.action == "feature_flag.update").order_by(AuditLog.occurred_at.desc())))
            .scalars()
            .all()
        )
    assert len(rows) == 2  # enabled, then disabled again — a rejected attempt writes nothing
    assert rows[0].after == {"key": "phase2.enabled", "enabled": False}
    assert {row.actor_email for row in rows} == {ADMIN}
    assert isinstance(rows[0].occurred_at, datetime)
