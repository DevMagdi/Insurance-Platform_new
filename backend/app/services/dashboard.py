"""Dashboard aggregates (screen 1) — everything reads through the same scope predicate."""

from __future__ import annotations

from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.scope import Scope
from app.models.clients import Client
from app.repositories import requests_repo as repo
from app.services import clients as clients_svc


async def summary(session: AsyncSession, scope: Scope) -> dict[str, Any]:
    kpis = await repo.kpis(session, scope)
    if scope.mode in {"all", "owner", "seeded"}:
        kpis["clients_total"] = int((await session.execute(_client_count_stmt(scope))).scalar_one())
    return kpis


def _client_count_stmt(scope: Scope) -> Any:
    from app.repositories.scope_filters import with_scope

    return with_scope(select(func.count(Client.id)), scope, "client")


async def channels(session: AsyncSession, scope: Scope, *, days: int = 7) -> list[dict[str, Any]]:
    return await repo.channels_breakdown(session, scope, days=days)


async def status_breakdown(session: AsyncSession, scope: Scope) -> list[dict[str, Any]]:
    return await repo.status_breakdown(session, scope)


async def recent_requests(session: AsyncSession, scope: Scope, *, limit: int = 8) -> list[dict[str, Any]]:
    rows = await repo.recent(session, scope, limit=limit)
    return [serialize_request(r) for r in rows]


def serialize_request(row: Any) -> dict[str, Any]:
    """Shared by dashboard + inbox: the row shape screen 1/2 tables expect."""
    from datetime import UTC, datetime

    person = row.insured_person
    client = row.client
    remaining = None
    hours_late = None
    if row.sla_due_at is not None:
        delta = row.sla_due_at - datetime.now(UTC)
        minutes = int(delta.total_seconds() // 60)
        if minutes >= 0:
            remaining = minutes
        else:
            hours_late = -minutes // 60
    return {
        "id": str(row.id),
        "number": row.number,
        "subject": row.subject,
        "status": row.status.value,
        "priority": row.priority.value,
        "channel": row.channel.value,
        "is_overdue": row.is_overdue,
        "sla_due_at": row.sla_due_at.isoformat() if row.sla_due_at else None,
        "sla_minutes_remaining": remaining,
        "sla_hours_late": hours_late,
        "employee_name": (person.name if person else None) or row.contact_name or "موظف غير معروف",
        "mobile": row.contact_mobile or (person.mobile if person else None),
        "client_id": str(client.id) if client else None,
        "client_name": client.name if client else "غير مصنّف",
        "insurance_type": row.insurance_type.name if row.insurance_type else None,
        "insurer": row.insurer.name if row.insurer else None,
        "assigned_to": str(row.assigned_to) if row.assigned_to else None,
        "assignee_name": row.assignee.full_name if row.assignee else None,
        "created_at": row.created_at.isoformat(),
        "last_activity_at": row.last_activity_at.isoformat(),
        "first_response_at": row.first_response_at.isoformat() if row.first_response_at else None,
    }


_ = clients_svc
