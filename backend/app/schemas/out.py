"""Response models for payloads the UI renders.

Why these exist: the frontend is only allowed to consume types generated from the OpenAPI file
(spec §3), so every response it reads must be described here. The models are deliberately
permissive (`extra="allow"`) — they *add* typing for the fields the UI depends on without
restricting what a serializer may return, which keeps them safe to introduce incrementally.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class Open(BaseModel):
    """Permissive base: typed where the UI needs it, extra keys pass through."""

    model_config = ConfigDict(from_attributes=True, extra="allow")


class PageOut(Open):
    items: list[Any] = Field(default_factory=list)
    total: int = 0
    page: int = 1
    page_size: int = 20
    pages: int | None = None


class LeadPageOut(PageOut):
    items: list[LeadOut] = Field(default_factory=list)


class RequestPageOut(PageOut):
    items: list[RequestOut] = Field(default_factory=list)


class ClientPageOut(PageOut):
    items: list[ClientOut] = Field(default_factory=list)


class InsuredPageOut(PageOut):
    items: list[InsuredOut] = Field(default_factory=list)


# ------------------------------------------------------------------ leads -------------------------
class LeadOut(Open):
    id: UUID
    name: str
    type: str
    status: str
    mobile: str | None = None
    contact_name: str | None = None
    contact_title: str | None = None
    headcount: int | None = None
    next_followup_at: datetime | None = None
    followup_overdue: bool = False
    insurance_type: str | None = None
    insurer: str | None = None
    assignee_name: str | None = None
    assignee_id: UUID | None = None
    last_activity_at: datetime | None = None
    converted_client_id: UUID | None = None


class LeadDetailOut(LeadOut):
    email: str | None = None
    source: str | None = None
    budget: float | str | None = None
    needs_text: str | None = None
    current_policy_expiry: date | None = None
    created_at: datetime | None = None
    converted_at: datetime | None = None
    lost_note: str | None = None
    lost_reason: str | None = None


class LeadBulkAssignOut(Open):
    assigned: int = 0
    per_rep: dict[str, int] = Field(default_factory=dict)
    skipped: list[dict[str, Any]] = Field(default_factory=list)


class LeadImportOut(Open):
    """Dry-run preview and final report of a lead import, in the same shape `ImportJobOut` uses."""

    id: UUID
    status: str
    filename: str | None = None
    total_rows: int = 0
    stats: dict[str, int] = Field(default_factory=dict)
    error_report: list[dict[str, Any]] = Field(default_factory=list)
    preview: list[dict[str, Any]] = Field(default_factory=list)
    created_at: datetime | None = None
    committed_at: datetime | None = None
    #: the two keys the UI needs to drive itself, mirroring the insured-import contract
    confirm_required: bool = False
    commit_url: str | None = None


class TeamMemberOut(Open):
    """One seat of the sales office, as screen 6's team tab lists it."""

    id: UUID
    email: str
    full_name: str
    mobile: str | None = None
    role: str
    role_name: str | None = None
    is_active: bool = True
    open_leads: int = 0
    last_login_at: str | None = None


class TeamAssignableRole(Open):
    code: str
    name: str


class TeamMemberCreatedOut(Open):
    id: UUID
    email: str
    role: str
    is_active: bool = True
    #: only present when the server generated it, and only ever in this one response
    temporary_password: str | None = None


class UserCreatedOut(Open):
    id: UUID
    email: str
    role: str
    #: only present when the server generated it, and only ever in this one response
    temporary_password: str | None = None


class LeadActivityOut(Open):
    id: UUID
    type: str
    body: str | None = None
    occurred_at: datetime
    actor_name: str | None = None


class LeadBoardColumnOut(Open):
    status: str
    count: int
    items: list[LeadOut] = Field(default_factory=list)


class LeadBoardOut(Open):
    columns: list[LeadBoardColumnOut] = Field(default_factory=list)


class LeadStatsOut(Open):
    my_leads: int = 0
    new_week: int = 0
    meetings_week: int = 0
    meetings_today: int = 0
    followups_overdue: int = 0
    converted_month: int = 0
    conversion_rate_pct: float | None = None


class LeadConvertOut(Open):
    """Returned by `POST /leads/{id}/convert` — the client the lead became, plus idempotency info."""

    client_id: UUID
    already_converted: bool = False
    account_owner_id: UUID | None = None


class RepWorkloadOut(Open):
    rep_id: UUID
    name: str
    is_active: bool = True
    open_leads: int
    meetings: int
    won: int
    unassigned: int = 0
    conversion_rate: float | None = None
    load: str | None = None
    stages: dict[str, int] = Field(default_factory=dict)
    stages_pct: dict[str, float] = Field(default_factory=dict)


# ---------------------------------------------------------------- clients -------------------------
class ClientOut(Open):
    id: UUID
    name: str
    type: str
    status: str
    since_date: date | None = None
    converted_at: datetime | None = None
    is_converted_from_lead: bool = False
    source_lead_id: UUID | None = None
    account_owner_id: UUID | None = None
    account_owner_name: str | None = None
    insurance_type: str | None = None
    insurer: str | None = None
    insured_count: int = 0
    open_requests: int = 0
    end_date: date | None = None


class ContactOut(Open):
    id: UUID
    name: str
    title: str | None = None
    mobile: str | None = None
    email: str | None = None
    is_primary: bool = False


class InsuredOut(Open):
    id: UUID
    name: str
    mobile: str | None = None
    national_id: str | None = None
    department: str | None = None
    job_title: str | None = None
    coverage_status: str
    coverage_start: date | None = None
    coverage_end: date | None = None
    notes: str | None = None
    external_ref: str | None = None


class ClientKpisOut(Open):
    insured: int = 0
    open_requests: int = 0
    avg_response_minutes: float | None = None
    renewal_in_days: int | None = None
    calls: int = 0


class ClientOverviewOut(Open):
    client: ClientOut
    contacts: list[ContactOut] = Field(default_factory=list)
    kpis: ClientKpisOut
    policy: PolicyOut | None = None


class InsuredListOut(Open):
    page: InsuredPageOut
    kpis: dict[str, int] = Field(default_factory=dict)


class ImportJobOut(Open):
    id: UUID
    client_id: UUID | None = None
    type: str
    status: str
    filename: str | None = None
    total_rows: int = 0
    stats: dict[str, int] = Field(default_factory=dict)
    error_report: list[dict[str, Any]] = Field(default_factory=list)
    preview: list[dict[str, Any]] = Field(default_factory=list)
    created_at: datetime | None = None


# -------------------------------------------------------------- requests ------------------------
class RequestOut(Open):
    id: UUID
    number: int
    subject: str
    status: str
    priority: str
    channel: str
    is_overdue: bool = False
    sla_due_at: datetime | None = None
    sla_minutes_remaining: int | None = None
    sla_hours_late: int | None = None
    employee_name: str | None = None
    client_id: UUID | None = None
    client_name: str | None = None
    insurance_type: str | None = None
    insurer: str | None = None
    assigned_to: str | None = None
    assignee_name: str | None = None
    mobile: str | None = None
    first_response_at: datetime | None = None
    created_at: datetime | None = None
    last_activity_at: datetime | None = None


class AttachmentOut(Open):
    id: UUID
    filename: str
    mime: str
    size: int = 0
    created_at: datetime | None = None
    url: str | None = None


class RequestMessageOut(Open):
    id: UUID
    direction: str
    channel: str
    body: str | None = None
    media_kind: str | None = None
    duration_s: int | None = None
    waveform: list[float] | None = None
    sender_ref: str | None = None
    delivery_status: str
    created_at: datetime
    attachments: list[AttachmentOut] = Field(default_factory=list)


class RequestNoteOut(Open):
    id: UUID
    body: str
    author_name: str | None = None
    created_at: datetime


class CallOut(Open):
    id: UUID
    direction: str
    from_number: str | None = None
    to_number: str | None = None
    caller_name: str | None = None
    started_at: datetime
    ended_at: datetime | None = None
    duration_s: int | None = None
    has_recording: bool = False
    recording_consent: bool = False
    listen_allowed: bool = False


class RequestDetailOut(RequestOut):
    description: str | None = None
    messages: list[RequestMessageOut] = Field(default_factory=list)
    notes: list[RequestNoteOut] = Field(default_factory=list)
    calls: list[CallOut] = Field(default_factory=list)
    attachments: list[AttachmentOut] = Field(default_factory=list)


class RecordingUrlOut(Open):
    url: str
    expires_at: str
    duration_s: int | None = None
    recording_consent: bool = False


# --------------------------------------------------------------- dashboard ----------------------
class DashboardSummaryOut(Open):
    requests_today: int = 0
    requests_yesterday: int = 0
    open_requests: int = 0
    overdue: int = 0
    sla_compliance_pct: float | None = None
    avg_first_response_minutes: float | None = None
    avg_first_response_delta_minutes: float | None = None
    clients_total: int = 0


class DashboardChannelOut(Open):
    date: date
    whatsapp: int = 0
    call: int = 0
    email: int = 0
    manual: int = 0


class DashboardStatusOut(Open):
    key: str
    count: int
    pct: int


class ClientKpiRowOut(Open):
    total_clients: int = 0
    converted_from_leads: int = 0
    expiring_90d: int = 0


# -------------------------------------------------------------- users & masters -----------------
class UserOut(Open):
    id: UUID
    email: str
    full_name: str
    mobile: str | None = None
    role: str
    role_name: str | None = None
    is_active: bool = True
    mfa_enabled: bool = False
    last_login_at: datetime | None = None
    scopes: list[Any] = Field(default_factory=list)
    portal_client_id: UUID | None = None


class RoleOut(Open):
    id: UUID
    code: str
    name: str
    is_system: bool = True
    permissions: list[str] = Field(default_factory=list)


class PermissionOut(Open):
    code: str
    group: str
    description: str | None = None


class FeatureFlagOut(Open):
    key: str
    enabled: bool
    description: str | None = None


class InsurerOut(Open):
    id: UUID
    code: str
    name: str
    name_en: str | None = None
    is_active: bool = True


class InsuranceTypeOut(Open):
    id: UUID
    code: str
    name: str
    name_en: str | None = None


class LostReasonOut(Open):
    id: UUID
    name: str
    sort_order: int = 0


class SlaPolicyOut(Open):
    priority: str
    first_response_minutes: int
    resolution_minutes: int
    warn_before_minutes: int = 0


# ------------------------------------------------------------------ phase 2 ---------------------
class InsurerRefOut(Open):
    id: UUID
    name: str


class InsuranceTypeRefOut(Open):
    id: UUID
    code: str
    name: str


class PolicyOut(Open):
    id: UUID
    client_id: UUID | None = None
    policy_no: str
    status: str
    start_date: date | None = None
    end_date: date | None = None
    premium_amount: float | str | None = None
    currency: str = "EGP"
    payment_plan: str | None = None
    commission_rate: float | str | None = None
    headcount: int | None = None
    insurer: InsurerRefOut | None = None
    insurance_type: InsuranceTypeRefOut | None = None


class InstallmentOut(Open):
    id: UUID
    sequence_no: int | None = None
    due_date: date
    amount: float
    status: str
    paid_at: datetime | None = None


class PolicyKpisOut(Open):
    active: int = 0
    expiring_90d: int = 0
    installments_this_month: int = 0
    late_installments: int = 0
    expected_commission: float | None = None
    currency: str = "EGP"


class InstallmentPlanOut(Open):
    policy: PolicyOut
    items: list[InstallmentOut] = Field(default_factory=list)


class IssuingDocumentOut(Open):
    name: str
    status: str


class IssuingCaseOut(Open):
    id: UUID
    stage: str
    client: str | None = None
    insurer: str | None = None
    premium_amount: float | None = None
    documents: list[IssuingDocumentOut] = Field(default_factory=list)


class IssuingDocumentDetailOut(Open):
    id: UUID
    name: str
    status: str
    requirement_id: UUID | None = None
    attachment_id: UUID | None = None


class IssuingCaseDetailOut(IssuingCaseOut):
    """Case header + the timestamps the pipeline screen needs (spec §9.13)."""

    headcount: int | None = None
    assigned_to: UUID | None = None
    started_at: str | None = None
    issued_at: str | None = None
    delivered_at: str | None = None


class InsurerPerformanceOut(Open):
    insurer: str
    requests: int
    avg_first_response_minutes: float | None = None
    sla_pct: float
    tone: str = "b"


class CommissionOut(Open):
    id: UUID
    policy_id: UUID | None = None
    amount: float
    status: str
    settled_at: datetime | None = None


# ------------------------------------------------------------------- portal ---------------------
class PortalClientOut(Open):
    id: UUID
    name: str
    type: str
    since_date: date | None = None


class PortalPolicySummaryOut(Open):
    policy_no: str | None = None
    status: str | None = None
    start_date: date | None = None
    end_date: date | None = None
    payment_plan: str | None = None
    insurer: str | None = None
    insurance_type: str | None = None


class PortalNextDueOut(Open):
    due_date: date | None = None
    amount: float | None = None


class PortalPremiumsOut(Open):
    """Installment money the owner is allowed to see. Commissions never appear here (spec §6)."""

    total: float | None = None
    paid: float | None = None
    overdue: float | None = None
    next_due: PortalNextDueOut | None = None


class PortalKpisOut(Open):
    requests_this_month: int = 0
    avg_response_minutes: float | None = None
    premiums: PortalPremiumsOut | None = None


class PortalOverviewOut(Open):
    """`policy_summary` is null until the client has a policy — the portal renders placeholders."""

    client: PortalClientOut
    policy_summary: PortalPolicySummaryOut | None = None
    kpis: PortalKpisOut
    covered_count: int = 0
    renewal_in_days: int | None = None


class PortalMessageOut(Open):
    """What the owner may read of a thread: the message itself, nothing about staff routing."""

    id: UUID
    direction: str
    channel: str
    body: str | None = None
    created_at: datetime | None = None


class PortalRequestItemOut(Open):
    """Portal-safe projection.

    It deliberately does *not* inherit `RequestOut`: the isolation test walks the response keys and
    any staff-only field name (assignee, insurer, internal flags) must be absent, not merely null.
    """

    id: UUID
    number: int
    subject: str
    status: str
    channel: str
    created_at: datetime | None = None
    last_activity_at: datetime | None = None
    messages: list[PortalMessageOut] = Field(default_factory=list)


class PortalRequestsOut(Open):
    items: list[PortalRequestItemOut] = Field(default_factory=list)
    total: int = 0
    page: int = 1
    page_size: int = 20


class PortalDocumentOut(Open):
    id: UUID
    filename: str
    mime: str
    size: int = 0
    created_at: datetime | None = None
    request_number: int | None = None
    download_url: str | None = None


class PortalRequestOut(Open):
    request_id: UUID
    number: int


class SignedUrlOut(Open):
    url: str
    expires_at: str


# Some page models reference classes declared later in this module; rebuild them once all exist.
for _model in (LeadPageOut, RequestPageOut, ClientPageOut, InsuredPageOut, InsuredListOut, ClientOverviewOut):
    _model.model_rebuild()


class TeamRosterOut(Open):
    """`GET /sales-team/members`: the office seats, and the roles the tab is allowed to hand out.

    The allowlist is served rather than copied into the client — a frontend that repeats `OFFICE_ROLES`
    would drift the day the set changes, and the dialog would offer an option the API refuses.
    """

    members: list[TeamMemberOut] = Field(default_factory=list)
    assignable_roles: list[TeamAssignableRole] = Field(default_factory=list)
