"""Lead request/response models. Enums are plain strings in the wire format for i18n freedom."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, Field

from app.schemas.common import EmailAddress, ORMModel

LeadType = Literal["company", "individual"]
LeadStatusValue = Literal[
    "new",
    "contacted",
    "interested",
    "meeting_scheduled",
    "meeting_done",
    "quote_sent",
    "negotiation",
    "won",
    "lost",
    "postponed",
]


class LeadCreate(BaseModel):
    type: LeadType = "company"
    name: str = Field(min_length=2, max_length=200)
    contact_name: str | None = Field(default=None, max_length=160)
    mobile: str | None = None
    email: EmailAddress | None = None
    source: str | None = Field(default=None, max_length=80)
    insurance_type_id: UUID | None = None
    headcount: int | None = Field(default=None, ge=1, le=2_000_000)
    current_insurer_id: UUID | None = None
    current_policy_expiry: date | None = None
    budget: Decimal | None = Field(default=None, ge=0)
    needs_text: str | None = None
    assigned_to: UUID | None = None
    next_followup_at: datetime | None = None
    allow_duplicate: bool = False


class LeadUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=2, max_length=200)
    type: LeadType | None = None
    contact_name: str | None = None
    mobile: str | None = None
    email: EmailAddress | None = None
    source: str | None = None
    insurance_type_id: UUID | None = None
    headcount: int | None = Field(default=None, ge=1)
    current_insurer_id: UUID | None = None
    current_policy_expiry: date | None = None
    budget: Decimal | None = Field(default=None, ge=0)
    needs_text: str | None = None
    next_followup_at: datetime | None = None


class LeadStatusUpdate(BaseModel):
    status: LeadStatusValue
    note: str | None = Field(default=None, max_length=2000)
    next_followup_at: datetime | None = None


class LeadAssign(BaseModel):
    assigned_to: UUID | None = None
    reason: str | None = Field(default=None, max_length=500)


class LeadLose(BaseModel):
    lost_reason_id: UUID
    note: str | None = Field(default=None, max_length=2000)


class LeadMeetingCreate(BaseModel):
    scheduled_at: datetime
    location: str | None = Field(default=None, max_length=200)


class LeadNoteCreate(BaseModel):
    body: str = Field(min_length=1, max_length=8000)


class LeadBrief(ORMModel):
    id: UUID
    name: str
    type: str
    status: str
    mobile: str | None = None
    contact_name: str | None = None
    headcount: int | None = None
    next_followup_at: datetime | None = None
    followup_overdue: bool = False
    insurance_type: str | None = None
    insurer: str | None = None
    assignee_name: str | None = None
    assignee_id: UUID | None = None
    last_activity_at: datetime | None = None
    converted_client_id: UUID | None = None


class LeadDetail(LeadBrief):
    email: str | None = None
    source: str | None = None
    budget: Decimal | None = None
    needs_text: str | None = None
    current_policy_expiry: date | None = None
    created_at: datetime
    converted_at: datetime | None = None
    lost_note: str | None = None
    lost_reason: str | None = None


class LeadActivityOut(BaseModel):
    id: UUID
    type: str
    body: str | None = None
    meta: dict[str, Any] | None = None
    occurred_at: datetime
    actor_name: str | None = None


class LeadBoardColumn(BaseModel):
    status: LeadStatusValue
    count: int
    items: list[LeadBrief]


class LeadStats(BaseModel):
    my_leads: int
    meetings_week: int
    followups_overdue: int
    converted_month: int


class ConvertResult(BaseModel):
    client_id: UUID
    already_converted: bool = False
    account_owner_id: UUID | None = None
