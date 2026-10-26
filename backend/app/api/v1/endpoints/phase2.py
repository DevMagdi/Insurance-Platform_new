"""Phase 2 routes (screens 12/13/14). Flag-gated: 503 feature_disabled until enabled (spec §2)."""

from __future__ import annotations

from typing import Any, cast
from uuid import UUID

from fastapi import APIRouter
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.serializers import policy_brief
from app.api.v1.deps import CurrentUser, DbSession, PageQuery, PoliciesView, ReportsView, ScopeDep
from app.core.errors import FeatureDisabled
from app.core.scope import Scope
from app.models.clients import Client
from app.models.phase2 import Commission, Installment, IssuingCase, Policy
from app.repositories.scope_filters import with_scope
from app.schemas.out import (
    InstallmentPlanOut,
    InsurerPerformanceOut,
    IssuingCaseDetailOut,
    IssuingCaseOut,
    IssuingDocumentDetailOut,
    PageOut,
    PolicyKpisOut,
)
from app.services.feature_flags import PHASE2_FLAG as _FLAG
from app.services.feature_flags import flag_enabled
from app.services.reports import insurer_performance

router = APIRouter(tags=["phase 2 (flagged)"])


async def _flag(session: AsyncSession) -> bool:
    """The single flag that gates this module (ADR-008). The lookup itself lives in `services.feature_flags`."""
    return await flag_enabled(session, _FLAG)


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


def _case_row(case: IssuingCase, *, documents: bool = True) -> dict[str, Any]:
    """One serializer for the three issuing routes, so the pipeline list and a case detail cannot drift."""
    row: dict[str, Any] = {
        "id": str(case.id),
        "stage": case.stage.value,
        "client": None if case.client is None else case.client.name,
        "insurer": None if case.insurer is None else case.insurer.name,
        "premium_amount": float(case.premium_amount) if case.premium_amount else None,
    }
    if documents:
        row["documents"] = [{"name": d.name, "status": d.status.value} for d in case.documents]
    return row


def _case_detail(case: IssuingCase) -> dict[str, Any]:
    # the checklist is embedded like in the list route, so the screen needs one round-trip, not two
    row = _case_row(case)
    row.update(
        {
            "headcount": case.headcount,
            "assigned_to": None if case.assigned_to is None else str(case.assigned_to),
            "started_at": None if case.started_at is None else case.started_at.isoformat(),
            "issued_at": None if case.issued_at is None else case.issued_at.isoformat(),
            "delivered_at": None if case.delivered_at is None else case.delivered_at.isoformat(),
        }
    )
    return row


async def _visible_case(session: AsyncSession, scope: Scope, case_id: UUID) -> IssuingCase:
    """Unknown id and foreign id answer the same 404 (§6: the API must not let anyone enumerate)."""
    from app.core.errors import NotFound

    row: IssuingCase | None = (
        await session.execute(with_scope(select(IssuingCase).where(IssuingCase.id == case_id), scope, "issuing_case").limit(1))
    ).scalar_one_or_none()
    if row is None:
        raise NotFound("Issuing case not found")
    return row


@router.get("/issuing-cases", summary="Issuing pipeline (Phase 2 · screen 13)", response_model=list[IssuingCaseOut])
async def issuing_cases(session: DbSession, scope: ScopeDep, actor: PoliciesView) -> Any:
    if not await _flag(session):
        raise FeatureDisabled("Phase 2 is not enabled yet", details={"flag": _FLAG})
    stmt = with_scope(select(IssuingCase).order_by(IssuingCase.created_at.desc()), scope, "issuing_case").limit(100)
    rows = (await session.execute(stmt)).scalars().unique().all()
    return [_case_row(c) for c in rows]


@router.get("/issuing-cases/{case_id}", summary="One issuing case (Phase 2)", response_model=IssuingCaseDetailOut)
async def issuing_case(case_id: UUID, session: DbSession, scope: ScopeDep, actor: PoliciesView) -> Any:
    if not await _flag(session):
        raise FeatureDisabled("Phase 2 is not enabled yet", details={"flag": _FLAG})
    return _case_detail(await _visible_case(session, scope, case_id))


@router.get(
    "/issuing-cases/{case_id}/documents",
    summary="Document checklist for one issuing case (Phase 2 · §7)",
    response_model=list[IssuingDocumentDetailOut],
)
async def issuing_case_documents(case_id: UUID, session: DbSession, scope: ScopeDep, actor: PoliciesView) -> Any:
    if not await _flag(session):
        raise FeatureDisabled("Phase 2 is not enabled yet", details={"flag": _FLAG})
    case = await _visible_case(session, scope, case_id)
    return [
        {
            "id": str(d.id),
            "name": d.name,
            "status": d.status.value,
            "requirement_id": None if d.requirement_id is None else str(d.requirement_id),
            "attachment_id": None if d.attachment_id is None else str(d.attachment_id),
        }
        for d in case.documents
    ]


@router.get("/reports/insurer-performance", summary="Reports (Phase 2 · screen 14)", response_model=list[InsurerPerformanceOut])
async def insurer_report(session: DbSession, scope: ScopeDep, actor: ReportsView) -> Any:
    if not await _flag(session):
        raise FeatureDisabled("Phase 2 is not enabled yet", details={"flag": _FLAG})
    # Shared with `POST /exports/insurer-performance`, so the downloaded file can never disagree with
    # the screen — and so scope predicates (spec §6) apply to both paths at once.
    return await insurer_performance(session, scope)
