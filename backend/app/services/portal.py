"""Client-company owner portal (screen 6). Sees one client, never internal notes/commissions/reps/recordings."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import Forbidden, NotFound
from app.core.scope import Scope
from app.domain import phone
from app.models.clients import Client, InsuredPerson
from app.models.phase2 import Installment, Policy
from app.models.requests import Attachment, RequestMessage, ServiceRequest


async def _client(session: AsyncSession, scope: Scope) -> Client:
    if not scope.is_portal or scope.portal_client_id is None:
        raise Forbidden("Portal access is only available to client accounts")
    client = await session.get(Client, scope.portal_client_id)
    if client is None or client.deleted_at is not None:
        raise NotFound("Client not found")
    return client


async def overview(session: AsyncSession, scope: Scope) -> dict[str, Any]:
    client = await _client(session, scope)
    now = datetime.now(UTC)
    month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)

    requests_month = int(
        (
            await session.execute(
                select(func.count(ServiceRequest.id)).where(ServiceRequest.client_id == client.id, ServiceRequest.created_at >= month_start)
            )
        ).scalar_one()
    )
    avg = (
        await session.execute(
            select(
                func.avg(func.extract("epoch", ServiceRequest.first_response_at) - func.extract("epoch", ServiceRequest.created_at))
            ).where(ServiceRequest.client_id == client.id, ServiceRequest.first_response_at.is_not(None))
        )
    ).scalar_one_or_none()
    policy = (
        await session.execute(select(Policy).where(Policy.client_id == client.id).order_by(Policy.created_at.desc()).limit(1))
    ).scalar_one_or_none()
    premiums = await _premiums(session, policy)
    covered = int(
        (
            await session.execute(
                select(func.count(InsuredPerson.id)).where(
                    InsuredPerson.client_id == client.id,
                    InsuredPerson.deleted_at.is_(None),
                    InsuredPerson.coverage_status == "active",
                )
            )
        ).scalar_one()
    )
    return {
        "client": {
            "id": str(client.id),
            "name": client.name,
            "type": client.type.value,
            "since_date": client.since_date.isoformat() if client.since_date else None,
        },
        "policy_summary": None
        if policy is None
        else {
            "policy_no": policy.policy_no,
            "status": policy.status.value,
            "start_date": policy.start_date.isoformat() if policy.start_date else None,
            "end_date": policy.end_date.isoformat() if policy.end_date else None,
            "payment_plan": policy.payment_plan.value,
            "insurer": None if policy.insurer is None else policy.insurer.name,
            "insurance_type": None if policy.insurance_type is None else policy.insurance_type.name,
        },
        "kpis": {
            "requests_this_month": requests_month,
            "avg_response_minutes": round(float(avg) / 60.0, 1) if avg is not None else None,
            "premiums": premiums,
        },
        "covered_count": covered,
        "renewal_in_days": (policy.end_date - date.today()).days if policy and policy.end_date else None,
    }


async def _premiums(session: AsyncSession, policy: Policy | None) -> dict[str, Any]:
    if policy is None:
        return {"total": None, "paid": None, "next_due": None, "overdue": None}
    rows = (
        (await session.execute(select(Installment).where(Installment.policy_id == policy.id).order_by(Installment.due_date)))
        .scalars()
        .all()
    )
    today = date.today()
    total = sum(float(r.amount) for r in rows)
    paid = sum(float(r.amount) for r in rows if r.paid_at is not None)
    overdue = sum(float(r.amount) for r in rows if r.paid_at is None and r.due_date < today)
    next_due = next((r for r in rows if r.paid_at is None), None)
    # Commissions are the brokerage's internal margin: they must not appear in this payload at all,
    # not even as a flag (spec §6). Staff reads them from /commissions.
    return {
        "total": round(total, 2),
        "paid": round(paid, 2),
        "overdue": round(overdue, 2),
        "next_due": None if next_due is None else {"due_date": next_due.due_date.isoformat(), "amount": float(next_due.amount)},
    }


async def my_requests(session: AsyncSession, scope: Scope, *, page: int = 1, page_size: int = 20) -> dict[str, Any]:
    client = await _client(session, scope)
    conds = [ServiceRequest.client_id == client.id]
    total = int((await session.execute(select(func.count(ServiceRequest.id)).where(*conds))).scalar_one())
    rows = (
        (
            await session.execute(
                select(ServiceRequest)
                .where(*conds)
                .order_by(ServiceRequest.last_activity_at.desc())
                .offset((page - 1) * page_size)
                .limit(page_size)
            )
        )
        .scalars()
        .all()
    )
    return {
        "items": [
            {
                **requests_svc_serialize(row),
                "messages": await thread(session, row.id),
            }
            for row in rows
        ],
        "total": total,
        "page": page,
        "page_size": page_size,
    }


def requests_svc_serialize(row: Any) -> dict[str, Any]:
    from app.services.dashboard import serialize_request

    data = serialize_request(row)
    # Portal-safe projection: no rep identity, no internal routing details.
    for key in ("assigned_to", "assignee_name", "mobile"):
        data.pop(key, None)
    data["mobile"] = phone.mask_mobile(row.contact_mobile)
    return data


async def thread(session: AsyncSession, request_id: Any) -> list[dict[str, Any]]:
    """Only the conversation body — internal notes are a separate table and are never queried here."""
    rows = (
        (
            await session.execute(
                select(RequestMessage).where(RequestMessage.request_id == request_id).order_by(RequestMessage.created_at.asc())
            )
        )
        .scalars()
        .all()
    )
    return [
        {
            "id": str(m.id),
            "direction": m.direction.value,
            "channel": m.channel.value,
            "body": m.body,
            "created_at": m.created_at.isoformat(),
            "delivery_status": m.delivery_status.value if m.delivery_status else None,
        }
        for m in rows
    ]


async def documents(session: AsyncSession, scope: Scope) -> list[dict[str, Any]]:
    """Contract documents visible to the owner: attachments hanging off their requests + policies."""
    client = await _client(session, scope)
    rows = (
        await session.execute(
            select(Attachment, ServiceRequest.number)
            .join(ServiceRequest, ServiceRequest.id == Attachment.request_id)
            .where(ServiceRequest.client_id == client.id)
            .order_by(Attachment.created_at.desc())
            .limit(100)
        )
    ).all()
    return [
        {
            "id": str(att.id),
            "filename": att.filename,
            "mime": att.mime,
            "size": att.size,
            "created_at": att.created_at.isoformat(),
            "request_number": number,
            "download_url": f"/api/v1/portal/attachments/{att.id}",
        }
        for att, number in rows
    ]


async def create_request(session: AsyncSession, scope: Scope, *, subject: str, body: str | None) -> dict[str, Any]:
    """Owner may open a request for their own company (channel=manual)."""
    if not scope.is_portal:
        raise Forbidden("Portal only")
    client = await _client(session, scope)
    from app.domain.enums import Channel
    from app.models.auth import User
    from app.schemas.requests import RequestCreate
    from app.services import requests_svc as svc

    actor = await session.get(User, scope.user_id) if scope.user_id else None
    if actor is None:
        raise Forbidden("Portal user is inactive")
    payload = RequestCreate(
        client_id=client.id,
        channel=Channel.MANUAL.value,
        subject=subject,
        description=body,
        priority="normal",
    )
    request = await svc.create(session, actor, scope, payload)
    return {"request_id": str(request.id), "number": request.number}


_ = timedelta
