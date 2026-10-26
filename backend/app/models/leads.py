"""Leads: pipeline row, activity timeline, meetings."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import TYPE_CHECKING, Any
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.domain.enums import ActivityType, ClientType, LeadStatus
from app.models.base import Base, SoftDeleteMixin, TimestampMixin, TZDateTime, UUIDPkMixin, enum_col

if TYPE_CHECKING:
    from app.models.auth import User
    from app.models.clients import Client
    from app.models.masters import InsuranceType, Insurer, LostReason


class Lead(UUIDPkMixin, TimestampMixin, SoftDeleteMixin, Base):
    __tablename__ = "leads"
    __table_args__ = (
        # Partial (active-only) uniqueness on mobile is created PG-only in a migration; a plain
        # index here keeps lookups fast everywhere.
        sa.Index("ix_leads_mobile", "mobile"),
        sa.Index("ix_leads_assigned_status", "assigned_to", "status"),
        sa.Index("ix_leads_followup", "next_followup_at"),
        sa.Index("ix_leads_status", "status"),
    )

    type: Mapped[ClientType] = mapped_column(enum_col(ClientType), default=ClientType.COMPANY, nullable=False)
    name: Mapped[str] = mapped_column(sa.String(200), nullable=False)
    contact_name: Mapped[str | None] = mapped_column(sa.String(160))
    mobile: Mapped[str | None] = mapped_column(sa.String(20))  # E.164, normalized
    email: Mapped[str | None] = mapped_column(sa.String(255))
    source: Mapped[str | None] = mapped_column(sa.String(80))
    insurance_type_id: Mapped[UUID | None] = mapped_column(sa.Uuid(), sa.ForeignKey("insurance_types.id"))
    headcount: Mapped[int | None] = mapped_column(sa.Integer)
    current_insurer_id: Mapped[UUID | None] = mapped_column(sa.Uuid(), sa.ForeignKey("insurers.id"))
    current_policy_expiry: Mapped[date | None] = mapped_column(sa.Date)
    budget: Mapped[Decimal | None] = mapped_column(sa.Numeric(14, 2))
    needs_text: Mapped[str | None] = mapped_column(sa.Text)

    status: Mapped[LeadStatus] = mapped_column(enum_col(LeadStatus), default=LeadStatus.NEW, nullable=False)
    assigned_to: Mapped[UUID | None] = mapped_column(sa.Uuid(), sa.ForeignKey("users.id"))
    next_followup_at: Mapped[datetime | None] = mapped_column(TZDateTime())

    lost_reason_id: Mapped[UUID | None] = mapped_column(sa.Uuid(), sa.ForeignKey("lost_reasons.id"))
    lost_note: Mapped[str | None] = mapped_column(sa.Text)
    converted_client_id: Mapped[UUID | None] = mapped_column(sa.Uuid(), sa.ForeignKey("clients.id"))
    converted_by: Mapped[UUID | None] = mapped_column(sa.Uuid(), sa.ForeignKey("users.id"))
    converted_at: Mapped[datetime | None] = mapped_column(TZDateTime())

    created_by: Mapped[UUID | None] = mapped_column(sa.Uuid(), sa.ForeignKey("users.id"))

    assignee: Mapped[User | None] = relationship(foreign_keys=[assigned_to], lazy="joined")
    insurance_type: Mapped[InsuranceType | None] = relationship(lazy="joined")
    current_insurer: Mapped[Insurer | None] = relationship(lazy="joined")
    lost_reason: Mapped[LostReason | None] = relationship(lazy="joined")
    # Two independent many-to-one links between leads/clients (leads.converted_client_id and
    # clients.source_lead_id); they cannot be a writable back_populates pair, so each side stands alone.
    converted_client: Mapped[Client | None] = relationship(foreign_keys=[converted_client_id], lazy="selectin")
    activities: Mapped[list[LeadActivity]] = relationship(back_populates="lead", lazy="noload", cascade="all, delete-orphan")


class LeadActivity(UUIDPkMixin, TimestampMixin, Base):
    __tablename__ = "lead_activities"
    __table_args__ = (sa.Index("ix_lead_activities_lead_time", "lead_id", "occurred_at"),)

    lead_id: Mapped[UUID] = mapped_column(sa.Uuid(), sa.ForeignKey("leads.id", ondelete="CASCADE"), nullable=False)
    type: Mapped[ActivityType] = mapped_column(enum_col(ActivityType), nullable=False)
    body: Mapped[str | None] = mapped_column(sa.Text)
    meta: Mapped[dict[str, Any] | None] = mapped_column(sa.JSON)
    actor_id: Mapped[UUID | None] = mapped_column(sa.Uuid(), sa.ForeignKey("users.id"))
    occurred_at: Mapped[datetime] = mapped_column(TZDateTime(), nullable=False)

    lead: Mapped[Lead] = relationship(back_populates="activities")
    actor: Mapped[User | None] = relationship(lazy="joined")


class LeadMeeting(UUIDPkMixin, TimestampMixin, Base):
    __tablename__ = "lead_meetings"
    __table_args__ = (sa.Index("ix_lead_meetings_when", "scheduled_at"),)

    lead_id: Mapped[UUID] = mapped_column(sa.Uuid(), sa.ForeignKey("leads.id", ondelete="CASCADE"), nullable=False)
    scheduled_at: Mapped[datetime] = mapped_column(TZDateTime(), nullable=False)
    location: Mapped[str | None] = mapped_column(sa.String(200))
    outcome: Mapped[str | None] = mapped_column(sa.Text)
    created_by: Mapped[UUID | None] = mapped_column(sa.Uuid(), sa.ForeignKey("users.id"))

    lead: Mapped[Lead] = relationship()
