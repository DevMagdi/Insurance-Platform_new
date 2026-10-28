"""Installments as an operational object: paid, late, and what commission it earns (R7, spec §2/§8).

Before this module an installment was a row the schedule wrote once and nothing ever touched again: its
`status` stayed `upcoming` forever, `paid_at` was always `None`, and the screens had to re-derive "late" in
the browser — which meant two readers could disagree about the same row, and the ledger could not answer
"كم حصّلنا هذا الشهر؟" for any month at all.

Two rules decide the shape of this file:

* **lateness is derived, and persisted.** `due_date < today and paid_at is None` *is* the definition; the
  row's `status` is a cache of it. `refresh_late` writes that cache when a screen asks (and when a payment
  lands), so a query can filter on `status = late` instead of re-deriving dates in every caller. It is
  idempotent and only ever moves `upcoming → late`.
* **paying is a fact, and paying twice is a conflict.** A second `POST …/pay` is a `409` that says which
  installment it was, not a silent no-op: a double click must not quietly move the collected total.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from typing import Any, cast
from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import Conflict, NotFound
from app.core.scope import Scope
from app.domain.enums import InstallmentStatus
from app.models.auth import User
from app.models.phase2 import Commission, Installment, Policy
from app.repositories.scope_filters import row_visible
from app.services import audit


async def policy_in_scope(session: AsyncSession, scope: Scope, policy_id: UUID) -> Policy:
    """404 — never 403 — for a policy outside the caller's book, exactly like every other scoped read."""
    policy = await row_visible(session, select(Policy).where(Policy.id == policy_id), scope, "policy")
    if policy is None:
        raise NotFound("Policy not found")
    return cast("Policy", policy)


async def refresh_late(session: AsyncSession, policy_ids: list[UUID], *, today: date | None = None) -> int:
    """Flip `upcoming → late` for every unpaid installment whose due date has passed. Returns how many."""
    if not policy_ids:
        return 0
    moment = today or date.today()
    result = await session.execute(  # type: ignore[call-overload]
        update(Installment)
        .where(
            Installment.policy_id.in_(policy_ids),
            Installment.status == InstallmentStatus.UPCOMING,
            Installment.paid_at.is_(None),
            Installment.due_date < moment,
        )
        .values(status=InstallmentStatus.LATE)
    )
    return int(getattr(result, "rowcount", 0) or 0)


async def commission_summary(session: AsyncSession, policy: Policy) -> dict[str, Any]:
    """The commission this policy earns, or an explicit "not computed" — never a guessed number.

    A policy whose premium or rate is zero has no commission row at all (`services.policies` does not write
    an empty one). Reporting `0.00` there would be a claim that the office earned nothing, which is a
    different statement from "nobody has priced this yet" — so the state is spelled out instead.
    """
    row = (await session.execute(select(Commission).where(Commission.policy_id == policy.id))).scalars().first()
    rate = float(policy.commission_rate) if policy.commission_rate is not None else None
    if row is None:
        return {"state": "not_computed", "amount": None, "rate": rate, "status": None, "settled_at": None}
    return {
        "state": "computed",
        "amount": float(row.amount),
        "rate": rate,
        "status": row.status.value,
        "settled_at": row.settled_at.isoformat() if row.settled_at else None,
    }


def _row_brief(row: Installment) -> dict[str, Any]:
    return {
        "id": str(row.id),
        "sequence_no": row.sequence_no,
        "due_date": row.due_date.isoformat(),
        "amount": float(row.amount),
        "status": row.status.value,
        "paid_at": row.paid_at.isoformat() if row.paid_at else None,
    }


def totals(rows: list[Installment], *, today: date | None = None) -> dict[str, Any]:
    """What the plan adds up to, computed from the rows the screen is about to render."""
    moment = today or date.today()
    paid = [row for row in rows if row.status == InstallmentStatus.PAID or row.paid_at is not None]
    unpaid = [row for row in rows if row not in paid]
    late = [row for row in unpaid if row.due_date < moment]
    return {
        "count": len(rows),
        "paid_count": len(paid),
        "late_count": len(late),
        "due_count": len(unpaid) - len(late),
        "paid_amount": round(sum(float(row.amount) for row in paid), 2),
        "late_amount": round(sum(float(row.amount) for row in late), 2),
        "due_amount": round(sum(float(row.amount) for row in unpaid if row.due_date >= moment), 2),
        "outstanding_amount": round(sum(float(row.amount) for row in unpaid), 2),
    }


async def plan(session: AsyncSession, scope: Scope, policy_id: UUID) -> dict[str, Any]:
    """The plan a screen renders: rows (lateness applied), totals, and the commission in words."""
    from app.api.serializers import policy_brief

    policy = await policy_in_scope(session, scope, policy_id)
    # lazily persisted, so a row that says "late" is late for every reader, not only for a browser that
    # computed it. The caller commits (this is a read route, and the write is derived + idempotent).
    await refresh_late(session, [policy.id])
    await session.flush()
    rows = (
        (await session.execute(select(Installment).where(Installment.policy_id == policy.id).order_by(Installment.due_date)))
        .scalars()
        .all()
    )
    return {
        "policy": policy_brief(policy),
        "items": [_row_brief(row) for row in rows],
        "totals": totals(list(rows)),
        "commission": await commission_summary(session, policy),
    }


async def pay(
    session: AsyncSession,
    actor: User,
    scope: Scope,
    policy_id: UUID,
    installment_id: UUID,
    *,
    ip: str | None = None,
    user_agent: str | None = None,
) -> dict[str, Any]:
    """Mark one installment paid, once. A second attempt is a `409`, not a second receipt."""
    policy = await policy_in_scope(session, scope, policy_id)
    row = (
        await session.execute(select(Installment).where(Installment.id == installment_id, Installment.policy_id == policy.id))
    ).scalar_one_or_none()
    if row is None:
        raise NotFound("Installment not found")
    if row.status == InstallmentStatus.PAID or row.paid_at is not None:
        raise Conflict(
            "This installment was already marked paid",
            details={"installment_id": str(row.id), "paid_at": row.paid_at.isoformat() if row.paid_at else None},
        )

    row.paid_at = datetime.now(UTC)
    row.status = InstallmentStatus.PAID
    await session.flush()
    await audit.write(
        session,
        actor=actor,
        action="installment.paid",
        entity_type="installment",
        entity_id=row.id,
        after={
            "policy_id": str(policy.id),
            "policy_no": policy.policy_no,
            "sequence_no": row.sequence_no,
            "amount": float(row.amount),
        },
        ip=ip,
        user_agent=user_agent,
    )
    return {
        "policy_id": str(policy.id),
        "installment": _row_brief(row),
        "commission": await commission_summary(session, policy),
    }
