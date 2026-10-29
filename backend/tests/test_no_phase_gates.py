"""ADR-034 — no phase gates: every shipped module is live, RBAC is the only gate.

The legacy `phase2.enabled=False` row is planted on purpose: nothing may read it.
With the right permission the answer is 200/201; without it, 403 — never 503.
"""

from __future__ import annotations

from app.core.db import get_sessionmaker
from app.models.masters import FeatureFlag
from sqlalchemy import select

from tests.helpers import login

MANAGER = "manager@brokerhub.test"
REP = "rep_a@brokerhub.test"


async def _plant_disabled_flag() -> None:
    async with get_sessionmaker()() as session:
        row = (await session.execute(select(FeatureFlag).where(FeatureFlag.key == "phase2.enabled"))).scalar_one_or_none()
        if row is None:
            session.add(FeatureFlag(key="phase2.enabled", enabled=False, description="legacy row, must have no reader"))
        else:
            row.enabled = False
        await session.commit()


async def test_live_modules_answer_with_permission_despite_disabled_flag(client, ids) -> None:
    await _plant_disabled_flag()
    async with login(client, MANAGER) as auth:
        created = await client.post(
            "/api/v1/policies",
            headers=auth,
            json={"client_id": ids["clients"]["ألف"], "start_date": "2026-01-01", "premium_amount": 1200, "payment_plan": "monthly"},
        )
        assert created.status_code == 201, created.text
        policy_id = created.json()["id"]

        for path in (
            "/api/v1/policies",
            "/api/v1/policies/kpis",
            f"/api/v1/policies/{policy_id}/installments",
            "/api/v1/commissions",
            "/api/v1/issuing-cases",
            "/api/v1/reports/insurer-performance",
        ):
            response = await client.get(path, headers=auth)
            assert response.status_code == 200, (path, response.text)

        exported = await client.post("/api/v1/exports/insurer-performance", headers=auth, json={})
        assert exported.status_code == 200, exported.text
        catalogue = await client.get("/api/v1/exports", headers=auth)
        assert catalogue.status_code == 200
        assert all(kind["requires_flag"] is None for kind in catalogue.json()["kinds"])


async def test_live_modules_refuse_without_permission_not_with_a_flag_code(client, ids) -> None:
    await _plant_disabled_flag()
    async with login(client, REP) as rep:
        for method, path in (
            ("GET", "/api/v1/policies"),
            ("GET", "/api/v1/reports/insurer-performance"),
            ("GET", "/api/v1/issuing-cases"),
        ):
            response = await client.request(method, path, headers=rep)
            assert response.status_code == 403, (path, response.text)
            assert response.json()["code"] != "feature_disabled"

        create = await client.post(
            "/api/v1/policies",
            headers=rep,
            json={"client_id": ids["clients"]["ألف"], "start_date": "2026-01-01", "premium_amount": 100},
        )
        assert create.status_code == 403
        assert create.json()["details"]["missing"] == ["policies.manage"]
