"""Lead pipeline use-cases: create (+dup detection), status, assign, lose, convert.

`convert()` is the transaction the spec calls out as the most business-critical: it must be atomic,
idempotent, and must freeze `account_owner_id` to the rep who owned the lead at conversion time.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from typing import TYPE_CHECKING, Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import Conflict, Forbidden, NotFound, ValidationFailed
from app.core.scope import Scope
from app.domain import lead_fsm
from app.domain.enums import (
    ActivityType,
    ClientStatus,
    ClientType,
    LeadStatus,
    PaymentPlan,
    PolicyStatus,
)
from app.domain.phone import normalize_mobile
from app.models.auth import User
from app.models.clients import Client, ClientContact
from app.models.leads import Lead, LeadMeeting
from app.models.phase2 import Policy
from app.repositories import leads as repo
from app.services import audit

if TYPE_CHECKING:
    from app.schemas.leads import LeadCreate, LeadStatusUpdate, LeadUpdate

_SNAPSHOT_FIELDS = (
    "name",
    "type",
    "status",
    "mobile",
    "email",
    "contact_name",
    "headcount",
    "budget",
    "needs_text",
    "assigned_to",
    "next_followup_at",
    "insurance_type_id",
    "current_insurer_id",
    "current_policy_expiry",
    "source",
)


async def create(session: AsyncSession, actor: User, scope: Scope, payload: LeadCreate, *, ip: str | None = None) -> dict[str, Any]:
    mobile = normalize_mobile(payload.mobile)
    duplicate: dict[str, Any] | None = None

    if mobile:
        existing = await repo.find_active_by_mobile(session, mobile, scope)
        if existing is not None:
            duplicate = {
                "lead_id": str(existing.id),
                "name": existing.name,
                "status": existing.status.value,
                "message": "A lead with this mobile number already exists in your pipeline",
            }
            if not payload.allow_duplicate:
                # Screen 10 wants a live warning + link to the existing lead.
                raise Conflict(str(duplicate["message"]), details=duplicate)
        elif await repo.mobile_exists_anywhere(session, mobile):
            # Owned by another rep: refuse the duplicate, but never leak whose it is.
            if not payload.allow_duplicate:
                raise Conflict(
                    "This mobile number already exists on another rep's lead. Ask a manager to redistribute.",
                    details={"duplicate_hidden": True},
                )

    if scope.can("leads.assign"):
        assigned_to = payload.assigned_to  # a manager may seed the pool with an explicit owner (or none)
    else:
        assigned_to = actor.id  # reps always own what they create

    lead = Lead(
        type=ClientType(payload.type),
        name=payload.name.strip(),
        contact_name=payload.contact_name,
        contact_title=payload.contact_title,
        mobile=mobile,
        email=payload.email,
        source=payload.source,
        insurance_type_id=payload.insurance_type_id,
        headcount=payload.headcount,
        current_insurer_id=payload.current_insurer_id,
        current_policy_expiry=payload.current_policy_expiry,
        budget=payload.budget,
        needs_text=payload.needs_text,
        status=LeadStatus.NEW,
        assigned_to=assigned_to,
        next_followup_at=payload.next_followup_at,
        created_by=actor.id,
    )
    session.add(lead)
    await session.flush()

    if assigned_to is not None and assigned_to != actor.id:
        await repo.add_activity(
            session,
            lead_id=lead.id,
            type_=ActivityType.ASSIGNMENT,
            body=f"assigned → {assigned_to}",
            meta={"assigned_to": str(assigned_to)},
            actor_id=actor.id,
        )
    await audit.write(
        session,
        actor=actor,
        action="lead.created",
        entity_type="lead",
        entity_id=lead.id,
        after=audit.snapshot(lead, _SNAPSHOT_FIELDS),
        ip=ip,
    )
    return {"lead_id": str(lead.id), "duplicate": duplicate}


async def update(session: AsyncSession, actor: User, scope: Scope, lead_id: UUID, payload: LeadUpdate, *, ip: str | None = None) -> Lead:
    lead = await _require(session, lead_id, scope)
    before = audit.snapshot(lead, _SNAPSHOT_FIELDS)
    data = payload.model_dump(exclude_unset=True)
    if "mobile" in data:
        data["mobile"] = normalize_mobile(data["mobile"])
    for field, value in data.items():
        setattr(lead, field, value)
    await session.flush()
    await audit.write(
        session,
        actor=actor,
        action="lead.updated",
        entity_type="lead",
        entity_id=lead.id,
        before=before,
        after=audit.snapshot(lead, _SNAPSHOT_FIELDS),
        ip=ip,
    )
    return lead


async def set_status(
    session: AsyncSession, actor: User, scope: Scope, lead_id: UUID, payload: LeadStatusUpdate, *, ip: str | None = None
) -> Lead:
    lead = await _require(session, lead_id, scope)
    target = LeadStatus(payload.status)
    if target in {LeadStatus.WON}:
        raise Conflict("A lead becomes a client only through POST /leads/{id}/convert")
    if target is LeadStatus.LOST:
        raise Conflict("Use POST /leads/{id}/lose so a lost reason is recorded")
    if not lead_fsm.can_transition(lead.status, target):
        raise Conflict(
            f"Illegal transition {lead.status.value} → {target.value}",
            details={"current": lead.status.value, "target": target.value},
        )
    before_status = lead.status.value
    lead.status = target
    if target is LeadStatus.MEETING_SCHEDULED and payload.next_followup_at:
        lead.next_followup_at = payload.next_followup_at
    await session.flush()
    await repo.add_activity(
        session,
        lead_id=lead.id,
        type_=ActivityType.STATUS_CHANGE,
        body=f"{before_status} → {target.value}",
        meta={"from": before_status, "to": target.value, "note": payload.note},
        actor_id=actor.id,
    )
    await audit.write(
        session,
        actor=actor,
        action="lead.status_changed",
        entity_type="lead",
        entity_id=lead.id,
        before={"status": before_status},
        after={"status": target.value},
        ip=ip,
    )
    return lead


async def _apply_assignment(
    session: AsyncSession,
    actor: User,
    lead: Lead,
    *,
    to_user_id: UUID | None,
    ip: str | None = None,
    reason: str | None = None,
    via: str = "single",
) -> tuple[UUID | None, str]:
    """The one implementation of "this lead now belongs to someone else": pointer, timeline row, audit row.

    Both the single-lead endpoint and the bulk redistribution call this, so a lead moved by the dialog
    cannot end up with a different history than one moved from its own detail sheet.
    """
    previous = lead.assigned_to
    lead.assigned_to = to_user_id
    await session.flush()
    label = "unassigned" if to_user_id is None else str(to_user_id)
    body = f"reassigned: {previous or 'none'} → {label}"
    if reason:
        body = f"{body} · {reason}"
    await repo.add_activity(
        session,
        lead_id=lead.id,
        type_=ActivityType.ASSIGNMENT,
        body=body,
        meta={"from": str(previous) if previous else None, "to": str(to_user_id) if to_user_id else None, "via": via},
        actor_id=actor.id,
    )
    await audit.write(
        session,
        actor=actor,
        action="lead.assigned",
        entity_type="lead",
        entity_id=lead.id,
        before={"assigned_to": str(previous) if previous else None},
        after={"assigned_to": str(to_user_id) if to_user_id else None},
        ip=ip,
    )
    return previous, label


async def assign(
    session: AsyncSession, actor: User, scope: Scope, lead_id: UUID, *, to_user_id: UUID | None, ip: str | None = None
) -> Lead:
    """Re-assignment is manager-only (spec §6). The event is recorded on the timeline."""
    if not scope.can("leads.assign"):
        raise Forbidden("Only a manager can re-assign leads")
    lead = await _require(session, lead_id, scope)  # managers can reach every lead
    if to_user_id is not None:
        await _require_rep(session, to_user_id)
    await _apply_assignment(session, actor, lead, to_user_id=to_user_id, ip=ip)
    return lead


async def _require_rep(session: AsyncSession, user_id: UUID) -> User:
    target = await session.get(User, user_id)
    if target is None or not target.is_active or target.deleted_at is not None:
        raise ValidationFailed("Target rep does not exist or is inactive", details={"user_id": str(user_id)})
    return target


async def assign_bulk(
    session: AsyncSession,
    actor: User,
    scope: Scope,
    *,
    lead_ids: list[UUID] | None,
    unassigned_only: bool,
    to: list[UUID],
    reason: str | None = None,
    ip: str | None = None,
) -> dict[str, Any]:
    """Redistribute a set of leads — or the whole unassigned pool — in one transaction.

    The rep list is validated *before* any row is touched, so a typo in a uuid cannot leave half the pool
    moved. Ids the caller cannot see land in `skipped` rather than failing the batch: a manager's list may
    legitimately contain a lead that was deleted while the dialog was open, and the answer the UI needs is
    "34 moved, 1 was gone", not a 404 that hides the 34.
    """
    if not scope.can("leads.assign"):
        raise Forbidden("Only a manager can re-assign leads", details={"required": ["leads.assign"]})
    targets = []
    for user_id in dict.fromkeys(to):  # the picker can repeat a rep; the split should not
        targets.append(await _require_rep(session, user_id))

    if unassigned_only:
        ids = await repo.unassigned_ids(session, scope)
    else:
        ids = list(dict.fromkeys(lead_ids or []))
    if not ids:
        return {"assigned": 0, "per_rep": {}, "skipped": []}

    per_rep: dict[str, int] = {str(target.id): 0 for target in targets}
    skipped: list[dict[str, Any]] = []
    assigned = 0
    cursor = 0
    for lead_id in ids:
        lead = await repo.get_by_id(session, lead_id, scope)
        if lead is None:
            skipped.append({"lead_id": str(lead_id), "reason": "not_found"})
            continue
        target = targets[cursor % len(targets)]
        cursor += 1
        if lead.assigned_to == target.id:
            skipped.append({"lead_id": str(lead_id), "reason": "already_assigned", "rep_id": str(target.id)})
            continue
        await _apply_assignment(session, actor, lead, to_user_id=target.id, ip=ip, reason=reason, via="redistribute")
        per_rep[str(target.id)] += 1
        assigned += 1

    await audit.write(
        session,
        actor=actor,
        action="lead.assigned_bulk",
        entity_type="lead",
        entity_id=None,
        after={"assigned": assigned, "per_rep": per_rep, "skipped": len(skipped), "pool": "unassigned" if unassigned_only else "selection"},
        ip=ip,
    )
    return {"assigned": assigned, "per_rep": {key: value for key, value in per_rep.items() if value}, "skipped": skipped}


async def lose(
    session: AsyncSession,
    actor: User,
    scope: Scope,
    lead_id: UUID,
    *,
    lost_reason_id: UUID,
    note: str | None = None,
    ip: str | None = None,
) -> Lead:
    lead = await _require(session, lead_id, scope)
    if lead.status in lead_fsm.TERMINAL and lead.status is not LeadStatus.LOST:
        raise Conflict(f"Lead is already {lead.status.value}")
    before = lead.status.value
    lead.status = LeadStatus.LOST
    lead.lost_reason_id = lost_reason_id
    lead.lost_note = note
    await session.flush()
    await repo.add_activity(
        session,
        lead_id=lead.id,
        type_=ActivityType.STATUS_CHANGE,
        body=note or "marked lost",
        meta={"from": before, "to": LeadStatus.LOST.value, "lost_reason_id": str(lost_reason_id)},
        actor_id=actor.id,
    )
    await audit.write(
        session,
        actor=actor,
        action="lead.lost",
        entity_type="lead",
        entity_id=lead.id,
        before={"status": before},
        after={"status": LeadStatus.LOST.value, "lost_reason_id": str(lost_reason_id)},
        ip=ip,
    )
    return lead


async def convert(session: AsyncSession, actor: User, scope: Scope, lead_id: UUID, *, ip: str | None = None) -> dict[str, Any]:
    """Atomic: client + primary contact + draft contract record + lead.won + audit + timeline.

    Idempotent: converting twice returns the same client instead of creating a second one.
    `account_owner_id` is the rep the lead was assigned to *at conversion time* — re-assigning the
    lead afterwards must not move the client (spec §12 M6 acceptance criterion).
    """
    lead = await _require(session, lead_id, scope)
    if not scope.can("leads.convert"):
        raise Forbidden("Not allowed to convert leads")

    if lead.converted_client_id is not None:
        existing = await session.get(Client, lead.converted_client_id)
        if existing is not None:
            return {
                "client_id": str(existing.id),
                "already_converted": True,
                "account_owner_id": str(existing.account_owner_id) if existing.account_owner_id else None,
            }

    owner_id = lead.assigned_to or actor.id
    now = datetime.now(UTC)
    client = Client(
        type=ClientType(lead.type.value),
        name=lead.name,
        status=ClientStatus.ACTIVE,
        account_owner_id=owner_id,
        source_lead_id=lead.id,
        converted_at=now,
        since_date=now.date(),
        notes=lead.needs_text,
    )
    session.add(client)
    await session.flush()

    if lead.contact_name or lead.mobile or lead.email:
        session.add(
            ClientContact(
                client_id=client.id,
                name=lead.contact_name or lead.name,
                mobile=lead.mobile,
                email=lead.email,
                is_primary=True,
            )
        )

    # Simplified contract record (Phase 1); Phase 2 upgrades it to a full policy lifecycle.
    session.add(
        Policy(
            client_id=client.id,
            insurer_id=lead.current_insurer_id,
            insurance_type_id=lead.insurance_type_id,
            start_date=now.date(),
            end_date=lead.current_policy_expiry or date(now.year + 1, now.month, min(now.day, 28)),
            premium_amount=lead.budget,
            payment_plan=PaymentPlan.MONTHLY,
            status=PolicyStatus.DRAFT,
            headcount=lead.headcount,
            notes="created from lead conversion",
        )
    )

    before = audit.snapshot(lead, _SNAPSHOT_FIELDS)
    lead.status = LeadStatus.WON
    lead.converted_client_id = client.id
    lead.converted_by = actor.id
    lead.converted_at = now
    await session.flush()

    await repo.add_activity(
        session,
        lead_id=lead.id,
        type_=ActivityType.STATUS_CHANGE,
        body=f"converted to client {client.name}",
        meta={"client_id": str(client.id), "account_owner_id": str(owner_id)},
        actor_id=actor.id,
    )
    await audit.write(
        session,
        actor=actor,
        action="lead.converted",
        entity_type="lead",
        entity_id=lead.id,
        before=before,
        after={**audit.snapshot(lead, _SNAPSHOT_FIELDS), "client_id": str(client.id)},
        ip=ip,
    )
    return {"client_id": str(client.id), "already_converted": False, "account_owner_id": str(owner_id)}


async def add_note(session: AsyncSession, actor: User, scope: Scope, lead_id: UUID, body: str) -> dict[str, Any]:
    lead = await _require(session, lead_id, scope)
    activity = await repo.add_activity(session, lead_id=lead.id, type_=ActivityType.NOTE, body=body, meta=None, actor_id=actor.id)
    return {"id": str(activity.id), "occurred_at": activity.occurred_at.isoformat()}


async def add_meeting(
    session: AsyncSession, actor: User, scope: Scope, lead_id: UUID, *, scheduled_at: datetime, location: str | None
) -> LeadMeeting:
    lead = await _require(session, lead_id, scope)
    meeting = LeadMeeting(lead_id=lead.id, scheduled_at=scheduled_at, location=location, created_by=actor.id)
    session.add(meeting)
    await session.flush()
    lead.status = LeadStatus.MEETING_SCHEDULED
    lead.next_followup_at = scheduled_at
    await session.flush()
    await repo.add_activity(
        session,
        lead_id=lead.id,
        type_=ActivityType.MEETING,
        body=f"meeting {scheduled_at.isoformat()}" + (f" @ {location}" if location else ""),
        meta={"scheduled_at": scheduled_at.isoformat(), "location": location},
        actor_id=actor.id,
    )
    return meeting


async def _require(session: AsyncSession, lead_id: UUID, scope: Scope) -> Lead:
    lead = await repo.get_by_id(session, lead_id, scope)
    if lead is None:
        raise NotFound("Lead not found")  # out-of-scope ids land here too — that is the point
    return lead
