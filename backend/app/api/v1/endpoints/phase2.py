"""Phase 2 routes (screens 12/13/14). Flag-gated: 503 feature_disabled until enabled (spec §2)."""

from __future__ import annotations

from typing import Any, cast
from uuid import UUID

import sqlalchemy as sa
from fastapi import APIRouter
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.serializers import policy_brief
from app.api.v1.deps import CurrentUser, DbSession, PageQuery, PoliciesView, ReportsView, ScopeDep
from app.core.errors import FeatureDisabled
from app.models.clients import Client
from app.models.phase2 import Commission, Installment, IssuingCase, Policy
from app.repositories.scope_filters import with_scope
from app.schemas.out import InstallmentPlanOut, InsurerPerformanceOut, IssuingCaseOut, PageOut, PolicyKpisOut

router = APIRouter(tags=["phase 2 (flagged)"])

_FLAG = "phase2.enabled"


async def _flag(session: AsyncSession) -> bool:
    from app.models.masters import FeatureFlag

    row = (await session.execute(select(FeatureFlag).where(FeatureFlag.key == _FLAG))).scalar_one_or_none()
    return bool(row and row.enabled)


@router.get("/policies", summary="Active policies (Phase 2 · screen 12)", response_model=PageOut)
async def policies(session: DbSession, scope: ScopeDep, params: PageQuery, actor: PoliciesView) -> Any:
    if not await _flag(session):
        raise FeatureDisabled("Phase 2 is not enabled yet", details={"flag": _FLAG})
    stmt = with_scope(select(Policy), scope, "policy").order_by(Policy.created_at.desc())
    rows = list((await session.execute(stmt.offset(params.offset).limit(params.page_size))).scalars().unique())
    total = int((await session.execute(with_scope(select(func.count(Policy.id)), scope, "policy"))).scalar_one())
    from app.core.pagination import Page

    return Page.build([policy_brief(r) for r in rows], total, params)  # type: ignore[arg-type]


@router.get("/policies/kpis", summary="Phase-2 KPI row (policies, installments, commission)", response_model=PolicyKpisOut)
async def policy_kpis(session: DbSession, scope: ScopeDep, actor: PoliciesView) -> Any:
    if not await _flag(session):
        raise FeatureDisabled("Phase 2 is not enabled yet", details={"flag": _FLAG})
    from datetime import date, timedelta

    from app.domain.enums import PolicyStatus

    today = date.today()
    horizon = today + timedelta(days=90)
    month_start = today.replace(day=1)

    policies = list((await session.execute(with_scope(select(Policy), scope, "policy"))).scalars().all())
    active = sum(1 for row in policies if row.status == PolicyStatus.ISSUED)
    expiring = sum(1 for row in policies if row.end_date and today <= row.end_date <= horizon)

    ids = [row.id for row in policies]
    installments: list[Installment] = []
    if ids:
        installments = list(
            (
                await session.execute(
                    select(Installment).where(Installment.policy_id.in_(ids)).order_by(Installment.due_date)  # type: ignore[attr-defined]
                )
            )
            .scalars()
            .all()
        )
    month = sum(1 for row in installments if row.due_date == month_start or (month_start <= row.due_date <= today))
    late = sum(1 for row in installments if row.due_date < today and row.paid_at is None)

    commission = 0.0
    for row in policies:
        if row.premium_amount is None:
            continue
        rate = float(row.commission_rate or 0)
        commission += float(row.premium_amount) * rate / 100.0

    return {
        "active": active,
        "expiring_90d": expiring,
        "installments_this_month": month,
        "late_installments": late,
        "expected_commission": round(commission, 2),
    }


@router.get("/policies/{policy_id}/installments", response_model=InstallmentPlanOut)
async def installments(policy_id: UUID, session: DbSession, scope: ScopeDep, actor: PoliciesView) -> Any:
    if not await _flag(session):
        raise FeatureDisabled("Phase 2 is not enabled yet", details={"flag": _FLAG})
    policy = (await session.execute(with_scope(select(Policy).where(Policy.id == policy_id), scope, "policy"))).scalar_one_or_none()
    if policy is None:
        from app.core.errors import NotFound

        raise NotFound("Policy not found")
    rows = (
        (await session.execute(select(Installment).where(Installment.policy_id == policy.id).order_by(Installment.due_date)))
        .scalars()
        .all()
    )
    return {
        "policy": policy_brief(policy),
        "items": [
            {
                "id": str(r.id),
                "sequence_no": r.sequence_no,
                "due_date": r.due_date.isoformat(),
                "amount": float(r.amount),
                "status": r.status.value,
                "paid_at": r.paid_at.isoformat() if r.paid_at else None,
            }
            for r in rows
        ],
    }


@router.get("/commissions", summary="Brokerage commission ledger")
async def commissions(session: DbSession, scope: ScopeDep, actor: CurrentUser) -> Any:
    from app.domain import permissions as P

    if P.COMMISSIONS_VIEW not in scope.perms:
        from app.core.errors import Forbidden

        raise Forbidden("Not allowed")
    if not await _flag(session):
        raise FeatureDisabled("Phase 2 is not enabled yet", details={"flag": _FLAG})
    rows = (
        await session.execute(
            select(Commission, Policy, Client.name)
            .join(Policy, Policy.id == Commission.policy_id)
            .join(Client, Client.id == Policy.client_id)
            .where(Policy.client_id.in_(cast(Any, with_scope(select(Client.id), scope, "client"))))
            .limit(200)
        )
    ).all()
    return [
        {
            "id": str(c.id),
            "policy_id": str(c.policy_id),
            "client_name": client_name,
            "amount": float(c.amount),
            "status": c.status.value,
            "settled_at": c.settled_at.isoformat() if c.settled_at else None,
        }
        for c, _p, client_name in rows
    ]


@router.get("/issuing-cases", summary="Issuing pipeline (Phase 2 · screen 13)", response_model=list[IssuingCaseOut])
async def issuing_cases(session: DbSession, scope: ScopeDep, actor: PoliciesView) -> Any:
    if not await _flag(session):
        raise FeatureDisabled("Phase 2 is not enabled yet", details={"flag": _FLAG})
    rows = (await session.execute(select(IssuingCase).order_by(IssuingCase.created_at.desc()).limit(100))).scalars().all()
    return [
        {
            "id": str(c.id),
            "stage": c.stage.value,
            "client": None if c.client is None else c.client.name,
            "insurer": None if c.insurer is None else c.insurer.name,
            "premium_amount": float(c.premium_amount) if c.premium_amount else None,
            "documents": [{"name": d.name, "status": d.status.value} for d in c.documents],
        }
        for c in rows
    ]


@router.get("/reports/insurer-performance", summary="Reports (Phase 2 · screen 14)", response_model=list[InsurerPerformanceOut])
async def insurer_report(session: DbSession, scope: ScopeDep, actor: ReportsView) -> Any:
    if not await _flag(session):
        raise FeatureDisabled("Phase 2 is not enabled yet", details={"flag": _FLAG})
    from app.models.masters import Insurer
    from app.models.requests import ServiceRequest

    rows = (
        await session.execute(
            select(
                Insurer.name,
                func.count(ServiceRequest.id),
                func.avg(func.extract("epoch", ServiceRequest.first_response_at) - func.extract("epoch", ServiceRequest.created_at)),
                func.sum(sa.case((ServiceRequest.is_overdue.is_(True), 1), else_=0)),
            )
            .join(ServiceRequest, ServiceRequest.insurer_id == Insurer.id)
            .group_by(Insurer.name)
        )
    ).all()
    out = []
    for name, count, avg_first, overdue in rows:
        overdue_count = int(overdue or 0)
        sla_pct = round(((int(count) - overdue_count) / int(count)) * 100.0, 1) if count else 0.0
        out.append(
            {
                "insurer": name,
                "requests": int(count),
                "avg_first_response_minutes": round(float(avg_first) / 60.0, 1) if avg_first else None,
                "sla_pct": sla_pct,
                "tone": "g" if sla_pct >= 90 else ("a" if sla_pct >= 80 else "r"),
            }
        )
    return out
