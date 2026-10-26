"""Reading, writing, testing and switching the integration providers (spec §8, ADR-016).

The rules this module exists to enforce:

* **a secret never comes back out through a read.** `state()` returns the config values plus, for each
  secret field, only `{"set": bool, "display": "••••••••" | "not_set"}`. The single function that hands
  decrypted values onward is `resolved_for_registry()`, which feeds driver objects and is not reachable
  from an endpoint.
* **a blank means "keep", not "erase".** A form round-trips a config whose secrets it cannot see, so a
  half-filled save must never delete a production token. Removal is an explicit `null`.
* **live needs a green test and an explicit confirmation.** A wrong token is recoverable; a WhatsApp
  number that starts answering customers from a mis-typed credential is a support incident.
* **every write is audited** with masked before/after, and every test is recorded on the row so the screen
  can answer «آخر اختبار» without grepping a server.

Precedence: a stored row wins, otherwise the environment, otherwise the declared default — see
`effective_config`, which is what `integrations/registry.py` primes itself from.
"""

from __future__ import annotations

import functools
import hashlib
import hmac
import smtplib
import ssl
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

from pydantic import TypeAdapter, ValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.errors import Conflict, ValidationFailed
from app.core.rate_limit import test_limiter
from app.core.secrets import decrypt_map, encrypt_map, mask_report
from app.models.auth import User
from app.models.integrations import PROVIDERS, IntegrationConfig, WebhookEvent
from app.schemas.common import EmailAddress
from app.services import audit

_EMAIL = TypeAdapter(EmailAddress)


class IncompleteConfig(Conflict):
    """The row is saved, but not enough of it exists to go live — `409 incomplete_config`."""

    code = "incomplete_config"


# ---------------------------------------------------------------------------------------------
# the field tables: one description of what each provider stores, validates and masks
# ---------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class FieldSpec:
    key: str
    kind: str = "str"  # str | int | bool | email | choice
    default: Any = ""
    required_for_live: bool = False
    choices: tuple[str, ...] = ()
    minimum: int | None = None
    maximum: int | None = None


#: Only fields something in the code actually reads are offered. A setting nobody consumes is a lie with a
#: toggle on it: it survives a refactor by doing nothing, and the operator believes it did something. So
#: `receive_media` (webhook ingest), `recording_retention_days` (the beat task) and each driver's own
#: knobs are here, while `caller_id`, `log_lead_activity`, `auto_create_request`, `link_window_hours` and
#: the signed-URL TTL are deliberately **not** — see ADR-016 §8.
PROVIDER_FIELDS: dict[str, tuple[FieldSpec, ...]] = {
    "whatsapp": (
        FieldSpec("phone_number_id", required_for_live=True),
        FieldSpec("business_account_id"),
        FieldSpec("receive_media", "bool", True),
    ),
    "telephony": (
        FieldSpec("provider", "choice", "generic", choices=("generic", "sim")),
        FieldSpec("recording_retention_days", "int", 180, minimum=1, maximum=3650),
    ),
    "email": (
        # 0 means "not set" — `effective_config` fills the pair from the environment's DSN, so the screen
        # cannot show a host different from the one the mailer would dial.
        FieldSpec("host", required_for_live=True),
        FieldSpec("port", "int", 0, minimum=0, maximum=65535),
        FieldSpec("username"),
        FieldSpec("encryption", "choice", "none", choices=("none", "starttls", "ssl")),
        FieldSpec("from_name", default="Broker Hub"),
        FieldSpec("from_email", "email", "no-reply@brokerhub.local", required_for_live=True),
        FieldSpec("reply_to", "email", ""),
    ),
}

#: masked on every read; `null` on a write deletes, a blank leaves untouched
PROVIDER_SECRETS: dict[str, tuple[str, ...]] = {
    "whatsapp": ("access_token", "app_secret", "verify_token"),
    "telephony": ("webhook_secret", "api_key"),
    "email": ("password",),
}

#: which environment variable each field falls back to (ADR-016 §4)
ENV_FALLBACK: dict[str, dict[str, str]] = {
    "whatsapp": {
        "access_token": "WHATSAPP_ACCESS_TOKEN",
        "app_secret": "WHATSAPP_APP_SECRET",
        "verify_token": "WHATSAPP_VERIFY_TOKEN",
        "phone_number_id": "WHATSAPP_PHONE_NUMBER_ID",
        "business_account_id": "WHATSAPP_BUSINESS_ACCOUNT_ID",
    },
    "telephony": {
        "webhook_secret": "TELEPHONY_WEBHOOK_SECRET",
        "api_key": "TELEPHONY_API_KEY",
        "provider": "TELEPHONY_PROVIDER",
    },
    "email": {
        "host": "SMTP_HOST",
        "port": "SMTP_PORT",
        "username": "SMTP_USERNAME",
        "password": "SMTP_PASSWORD",
        "encryption": "SMTP_ENCRYPTION",
        "from_name": "SMTP_FROM_NAME",
        "from_email": "EMAIL_FROM",
        "reply_to": "SMTP_REPLY_TO",
    },
}

#: the credential whose absence makes a provider unusable — checked when switching to live
PRIMARY_SECRET = {"whatsapp": "access_token", "telephony": "webhook_secret", "email": "password"}

SIM_TEMPLATES = (
    {"name": "policy_reminder_ar", "language": "ar", "status": "APPROVED"},
    {"name": "renewal_notice_ar", "language": "ar", "status": "APPROVED"},
    {"name": "docs_needed_ar", "language": "ar", "status": "PENDING"},
)


def defaults(provider: str) -> dict[str, Any]:
    return {spec.key: spec.default for spec in PROVIDER_FIELDS[provider]}


def _field_error(field_name: str, message: str, kind: str = "invalid") -> ValidationFailed:
    return ValidationFailed(
        "Some fields need attention",
        details=[{"field": field_name, "message": message, "type": kind}],
    )


def _coerce(spec: FieldSpec, value: Any) -> Any:
    if value is None:
        return spec.default
    if spec.kind == "int":
        try:
            number = int(str(value).strip())
        except (TypeError, ValueError):
            raise _field_error(spec.key, "رقم صحيح مطلوب") from None
        if spec.minimum is not None and number < spec.minimum:
            raise _field_error(spec.key, f"الأقل {spec.minimum}")
        if spec.maximum is not None and number > spec.maximum:
            raise _field_error(spec.key, f"الأكثر {spec.maximum}")
        return number
    if spec.kind == "bool":
        if isinstance(value, bool):
            return value
        if isinstance(value, (int, float)) and value in (0, 1):
            return bool(value)
        if isinstance(value, str) and value.strip().lower() in {"true", "false", "1", "0", "on", "off", "yes", "no"}:
            return value.strip().lower() in {"true", "1", "on", "yes"}
        raise _field_error(spec.key, "قيمة صح/خطأ مطلوبة")
    if spec.kind == "choice":
        text = str(value).strip()
        if text not in spec.choices:
            raise _field_error(spec.key, " / ".join(spec.choices))
        return text
    if spec.kind == "email":
        text = str(value).strip()
        if not text:
            return ""
        try:
            return _EMAIL.validate_python(text)
        except ValidationError:
            raise _field_error(spec.key, "بريد إلكتروني صحيح مطلوب") from None
    return str(value).strip()[:512]


def validate_config(provider: str, candidate: dict[str, Any] | None) -> dict[str, Any]:
    """Coerce + range-check every declared field. Unknown keys are rejected by `update`, not silently kept."""
    values = dict(candidate or {})
    return {spec.key: _coerce(spec, values.get(spec.key, spec.default)) for spec in PROVIDER_FIELDS[provider]}


# ---------------------------------------------------------------------------------------------
# reads
# ---------------------------------------------------------------------------------------------


@dataclass
class State:
    """Everything the settings screen is allowed to know about one provider."""

    provider: str
    config: dict[str, Any] = field(default_factory=dict)
    secrets: list[dict[str, Any]] = field(default_factory=list)
    is_live: bool = False
    status: str = "unset"  # live | sim | unset | error — the badge in the card header
    last_tested_at: str | None = None
    last_test_status: str | None = None
    last_test_detail: str | None = None
    updated_at: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "provider": self.provider,
            "config": self.config,
            "secrets": self.secrets,
            "is_live": self.is_live,
            "status": self.status,
            "last_tested_at": self.last_tested_at,
            "last_test_status": self.last_test_status,
            "last_test_detail": self.last_test_detail,
            "updated_at": self.updated_at,
        }


async def _row(session: AsyncSession, provider: str) -> IntegrationConfig | None:
    return (await session.execute(select(IntegrationConfig).where(IntegrationConfig.provider == provider))).scalar_one_or_none()


def _env_value(provider: str, key: str) -> Any:
    env_name = ENV_FALLBACK.get(provider, {}).get(key)
    if not env_name:
        return None
    return getattr(get_settings(), env_name, None)


def _stored_config(provider: str, row: IntegrationConfig | None) -> dict[str, Any]:
    if row is None or not row.config:
        return {}
    return {key: value for key, value in dict(row.config).items() if key in defaults(provider)}


def effective_config(provider: str, row: IntegrationConfig | None) -> dict[str, Any]:
    """defaults → environment → stored row. The env layer is what keeps a deployment that only edited
    `.env` working, and it is also why a blank form field does not silently disable a credential the
    server already has."""
    merged = defaults(provider)
    for key in merged:
        env_value = _env_value(provider, key)
        if env_value not in (None, ""):
            merged[key] = env_value
    merged.update(_stored_config(provider, row))
    if provider == "email":
        # The mailer dials `smtp_endpoint`; showing anything else here would be a second truth about the
        # same server, so an unset host/port is filled from it rather than left blank.
        host, port = get_settings().smtp_endpoint
        if not merged.get("host"):
            merged["host"] = host
        if not merged.get("port"):
            merged["port"] = port
    for key, value in merged.items():
        spec = next(spec for spec in PROVIDER_FIELDS[provider] if spec.key == key)
        merged[key] = _coerce(spec, value)
    return merged


def secrets_for(provider: str, row: IntegrationConfig | None) -> dict[str, str]:
    """Stored secrets, topped up from the environment for anything not stored."""
    out = {key: value for key, value in decrypt_map(row.secrets_encrypted if row else None).items() if value}
    for key in PROVIDER_SECRETS[provider]:
        if key not in out:
            env_value = _env_value(provider, key)
            if env_value:
                out[key] = str(env_value)
    return out


async def state(session: AsyncSession, provider: str) -> State:
    _assert_provider(provider)
    row = await _row(session, provider)
    out = State(
        provider=provider,
        config=effective_config(provider, row),
        secrets=mask_report(PROVIDER_SECRETS[provider], secrets_for(provider, row)),
        is_live=bool(row.is_live) if row else False,
        last_tested_at=row.last_tested_at.astimezone(UTC).isoformat() if row and row.last_tested_at else None,
        last_test_status=row.last_test_status if row else None,
        last_test_detail=row.last_test_detail if row else None,
        updated_at=row.updated_at.astimezone(UTC).isoformat() if row and row.updated_at else None,
    )
    out.status = _status_of(out)
    return out


def _status_of(state: State) -> str:
    """The badge tones come from the approved screen, so the classification is stated once, in code."""
    if state.last_test_status == "failed":
        return "error"
    if state.is_live:
        return "live"
    if any(item["set"] for item in state.secrets):
        return "sim"
    return "unset"


async def all_states(session: AsyncSession) -> list[dict[str, Any]]:
    return [(await state(session, provider)).as_dict() for provider in PROVIDERS]


def webhook_urls() -> dict[str, Any]:
    settings = get_settings()
    base = settings.PUBLIC_BASE_URL.rstrip("/") or "http://localhost:8000"
    prefix = settings.API_V1_PREFIX
    return {
        "base_url": base,
        "items": [
            {
                "provider": "whatsapp",
                "label": "WhatsApp Webhooks",
                "url": f"{base}{prefix}/webhooks/whatsapp",
                "note": "Meta → App dashboard → WhatsApp → Configuration: callback URL, ثم verify token نفسه هنا.",
            },
            {
                "provider": "telephony",
                "label": "Telephony events",
                "url": f"{base}{prefix}/webhooks/telephony",
                "note": "اضبط السنترال أن يرسل started / ended / recording_ready مع ترويسة X-Call-Signature.",
            },
        ],
    }


# ---------------------------------------------------------------------------------------------
# writes
# ---------------------------------------------------------------------------------------------


async def update(
    session: AsyncSession,
    actor: User,
    provider: str,
    *,
    config: dict[str, Any] | None = None,
    secrets: dict[str, Any] | None = None,
    is_live: bool | None = None,
    confirm_live: bool = False,
    ip: str | None = None,
    user_agent: str | None = None,
) -> dict[str, Any]:
    """Merge a partial form into the row, switch live only on a green test, audit the masked diff."""
    _assert_provider(provider)
    row = await _row(session, provider)
    created = row is None
    if row is None:
        row = IntegrationConfig(provider=provider, config=defaults(provider), is_live=False)
        session.add(row)
        await session.flush()

    before_config = effective_config(provider, row)
    before_secrets = {key: bool(value) for key, value in secrets_for(provider, row).items()}
    before_is_live = bool(row.is_live)

    if config is not None:
        unknown = sorted(set(config) - set(defaults(provider)))
        if unknown:
            raise ValidationFailed(
                "Some fields need attention",
                details=[{"field": name, "message": "حقل غير معروف لهذا المزوّد", "type": "extra"} for name in unknown],
            )
        row.config = validate_config(provider, {**before_config, **config})

    after_secret_names = set()
    if secrets is not None:
        unknown_secret = sorted(set(secrets) - set(PROVIDER_SECRETS[provider]))
        if unknown_secret:
            raise ValidationFailed(
                "Some fields need attention",
                details=[{"field": name, "message": "حقل سري غير معروف لهذا المزوّد", "type": "extra"} for name in unknown_secret],
            )
        current = decrypt_map(row.secrets_encrypted)
        for key, value in secrets.items():
            if value is None:
                current.pop(key, None)
            else:
                text = str(value).strip()
                if text and text != "••••••••":
                    current[key] = text
            after_secret_names.add(key)
        row.secrets_encrypted = encrypt_map(current)

    if is_live is not None and is_live != row.is_live:
        _assert_switch(row, provider, to_live=is_live, confirm=confirm_live)
        row.is_live = is_live

    row.updated_by = actor.id
    await session.flush()
    after_config = effective_config(provider, row)
    after_secrets = {key: bool(value) for key, value in secrets_for(provider, row).items()}
    await audit.write(
        session,
        actor=actor,
        action="integration.update",
        entity_type="integration_config",
        entity_id=row.id,
        before={
            "config": _mask_dict(provider, before_config),
            "secrets": before_secrets,
            "is_live": before_is_live,
            "created": created,
        },
        after={
            "config": _mask_dict(provider, after_config),
            "secrets": after_secrets,
            "is_live": row.is_live,
            "changed": {
                "config": sorted(k for k in after_config if before_config.get(k) != after_config[k]),
                "secrets": sorted(after_secret_names),
                "is_live": before_is_live != row.is_live,
            },
        },
        ip=ip,
        user_agent=user_agent,
    )
    await session.commit()
    await _reprime(session)
    return (await state(session, provider)).as_dict()


def _mask_dict(provider: str, values: dict[str, Any]) -> dict[str, Any]:
    """Audit payloads must not carry secrets either — a config field could hold a token pasted by mistake."""
    out = dict(values)
    for key in PROVIDER_SECRETS[provider]:
        if key in out:
            out[key] = "••••••••" if out[key] else ""
    return out


def _assert_switch(row: IntegrationConfig, provider: str, *, to_live: bool, confirm: bool) -> None:
    if not to_live:
        return  # back to simulation is always safe, and always allowed
    if not confirm:
        raise Conflict(
            "التبديل إلى الوضع الحيّ يحتاج تأكيدًا صريحًا",
            details={"required": ["confirm_live"], "note": "أرسل confirm_live=true بعد مراجعة ما الذي سيبدأ بالكلام مع العملاء"},
        )
    if row.last_test_status != "ok":
        raise Conflict(
            "لم ينجح أي اختبار اتصال لهذا المزوّد بعد",
            details={"required": ["test"], "note": "شغّل اختبار الاتصال أولًا — التبديل بلا اختبار أخضر هو كيف يصمت الرقم"},
        )
    config = effective_config(provider, row)
    missing = [spec.key for spec in PROVIDER_FIELDS[provider] if spec.required_for_live and not str(config.get(spec.key, "")).strip()]
    secrets = secrets_for(provider, row)
    primary = PRIMARY_SECRET[provider]
    if not secrets.get(primary):
        missing.append(primary)
    if missing:
        raise IncompleteConfig("إعدادات ناقصة للوضع الحيّ", details={"missing": missing})


async def set_live(
    session: AsyncSession,
    actor: User,
    provider: str,
    *,
    is_live: bool,
    confirm: bool = False,
    ip: str | None = None,
    user_agent: str | None = None,
) -> dict[str, Any]:
    _assert_provider(provider)
    row = await _row(session, provider)
    if row is None:
        row = IntegrationConfig(provider=provider, config=defaults(provider), is_live=False)
        session.add(row)
        await session.flush()
    before = bool(row.is_live)
    _assert_switch(row, provider, to_live=is_live, confirm=confirm)
    row.is_live = is_live
    row.updated_by = actor.id
    await audit.write(
        session,
        actor=actor,
        action="integration.live",
        entity_type="integration_config",
        entity_id=row.id,
        before={"is_live": before},
        after={"is_live": is_live, "confirm": confirm},
        ip=ip,
        user_agent=user_agent,
    )
    await session.commit()
    await _reprime(session)
    return (await state(session, provider)).as_dict()


# ---------------------------------------------------------------------------------------------
# resolution for drivers, connection tests, template sync, event log
# ---------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class ResolvedIntegration:
    """Decrypted, merged provider config — the only type that carries a plaintext secret onward."""

    provider: str
    is_live: bool
    config: dict[str, Any]
    secrets: dict[str, str]

    def secret(self, name: str) -> str:
        return self.secrets.get(name) or str(_env_value(self.provider, name) or "")

    def value(self, name: str, fallback: str = "") -> str:
        raw = self.config.get(name)
        if raw in (None, ""):
            raw = _env_value(self.provider, name)
        return str(raw) if raw not in (None, "") else fallback

    def number(self, name: str, fallback: int) -> int:
        try:
            return int(self.config.get(name) or fallback)
        except (TypeError, ValueError):
            return fallback


async def resolved_for_registry(session: AsyncSession) -> dict[str, ResolvedIntegration]:
    """Called by `integrations/registry.py` at startup and after every settings write. Not a route."""
    settings = get_settings()
    out: dict[str, ResolvedIntegration] = {}
    for provider in PROVIDERS:
        row = await _row(session, provider)
        out[provider] = ResolvedIntegration(
            provider=provider,
            is_live=bool(row.is_live) if row is not None else settings.INTEGRATIONS_DRIVER == "live",
            config=effective_config(provider, row),
            secrets=secrets_for(provider, row),
        )
    return out


@dataclass(frozen=True)
class TestOutcome:
    ok: bool
    detail: str


# `run_connection_test`, not `test_connection`: a module-level name starting with `test_` is read as a pytest
# case by the linters (PT028 fired on the first draft), and a function that takes a request's body is not one.
async def run_connection_test(
    session: AsyncSession,
    actor: User,
    provider: str,
    *,
    to: str | None = None,
    ip: str | None = None,
    user_agent: str | None = None,
) -> dict[str, Any]:
    """A real check when live, an explicitly-labelled simulation when not — and always recorded."""
    _assert_provider(provider)
    test_limiter.check(f"integration-test|{actor.id}|{provider}")
    resolved = (await resolved_for_registry(session))[provider]
    started = time.monotonic()
    if not resolved.is_live:
        outcome = TestOutcome(True, "وضع المحاكاة: لم يخرج أي نداء إلى الشبكة. الإعدادات مقبولة والصيغة صحيحة.")
    elif provider == "whatsapp":
        outcome = await _test_whatsapp(resolved)
    elif provider == "telephony":
        outcome = _test_telephony(resolved)
    else:
        outcome = await _test_email(resolved, to=to or actor.email, probe_only=to is None)
    took_ms = int((time.monotonic() - started) * 1000)

    row = await _row(session, provider)
    if row is None:
        row = IntegrationConfig(provider=provider, config=defaults(provider), is_live=False)
        session.add(row)
        await session.flush()
    row.last_tested_at = datetime.now(UTC)
    row.last_test_status = "ok" if outcome.ok else "failed"
    row.last_test_detail = outcome.detail[:900]
    row.updated_by = actor.id
    await audit.write(
        session,
        actor=actor,
        action="integration.test",
        entity_type="integration_config",
        entity_id=row.id,
        after={
            "provider": provider,
            "ok": outcome.ok,
            "mode": "live" if resolved.is_live else "sim",
            "ms": took_ms,
            "detail": outcome.detail[:300],
        },
        ip=ip,
        user_agent=user_agent,
    )
    await session.commit()
    await _reprime(session)
    return {
        "provider": provider,
        "ok": outcome.ok,
        "detail": outcome.detail,
        "took_ms": took_ms,
        "mode": "live" if resolved.is_live else "sim",
        "tested_at": row.last_tested_at.isoformat(),
    }


async def sync_templates(session: AsyncSession, actor: User, *, ip: str | None = None, user_agent: str | None = None) -> dict[str, Any]:
    _assert_provider("whatsapp")
    resolved = (await resolved_for_registry(session))["whatsapp"]
    if not resolved.is_live:
        templates = [dict(item) for item in SIM_TEMPLATES]
        detail = "وضع المحاكاة: قوالب محاكاة محلية؛ المزامنة الحقيقية تقرأ من نشاط Business Account في الوضع الحيّ."
    else:
        account = resolved.value("business_account_id")
        token = resolved.secret("access_token")
        if not account or not token:
            raise IncompleteConfig(
                "تحتاج المزامنة Business Account ID وAccess Token في الوضع الحيّ",
                details={"missing": [key for key, value in {"business_account_id": account, "access_token": token}.items() if not value]},
            )
        templates, detail = await _fetch_meta_templates(account, token)

    row = await _row(session, "whatsapp")
    await audit.write(
        session,
        actor=actor,
        action="integration.templates_sync",
        entity_type="integration_config",
        entity_id=row.id if row else None,
        after={"count": len(templates), "mode": "live" if resolved.is_live else "sim", "detail": detail[:300]},
        ip=ip,
        user_agent=user_agent,
    )
    await session.commit()
    return {"provider": "whatsapp", "templates": templates, "detail": detail, "synced_at": datetime.now(UTC).isoformat()}


async def recent_events(session: AsyncSession, provider: str | None = None, *, limit: int = 20) -> list[dict[str, Any]]:
    """The last few inbound events, newest first, within 24 hours — the screen answers "did it arrive?"."""
    since = datetime.now(UTC) - timedelta(hours=24)
    stmt = (
        select(WebhookEvent)
        .where(WebhookEvent.occurred_at >= since)
        .order_by(WebhookEvent.occurred_at.desc())
        .limit(min(max(limit, 1), 50))
    )
    if provider:
        stmt = stmt.where(WebhookEvent.provider == provider)
    return [
        {
            "id": str(row.id),
            "provider": row.provider,
            "event_type": row.event_type,
            "external_id": row.external_id,
            "status": row.status,
            "detail": (row.detail or "")[:300] or None,
            "occurred_at": row.occurred_at.astimezone(UTC).isoformat() if row.occurred_at else None,
        }
        for row in list((await session.execute(stmt)).scalars().all())
    ]


async def record_event(
    session: AsyncSession,
    *,
    provider: str,
    event_type: str,
    external_id: str | None = None,
    status: str = "ok",
    detail: str | None = None,
) -> None:
    """Called from the webhook handlers. The caller commits: an event log must never decide a request's fate."""
    session.add(
        WebhookEvent(
            provider=provider,
            event_type=event_type,
            external_id=external_id,
            status=status,
            detail=(detail or "")[:900] or None,
        )
    )


async def _reprime(session: AsyncSession) -> None:
    from app.integrations import registry

    await registry.prime(session)


def _assert_provider(provider: str) -> None:
    if provider not in PROVIDERS:
        raise ValidationFailed(
            "مزوّد غير معروف",
            details=[{"field": "provider", "message": " / ".join(PROVIDERS), "type": "invalid"}],
        )


# ---------------------------------------------------------------------------------------------
# the three probes
# ---------------------------------------------------------------------------------------------


async def _test_whatsapp(resolved: ResolvedIntegration) -> TestOutcome:
    """Meta's own token introspection: proves the credential is alive without messaging a customer."""
    import httpx

    token = resolved.secret("access_token")
    phone_id = resolved.value("phone_number_id")
    if not token or not phone_id:
        return TestOutcome(False, "ناقص: access_token وphone_number_id مطلوبان في الوضع الحيّ")
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            response = await client.get("https://graph.facebook.com/v21.0/debug_token", params={"input_token": token})
    except httpx.HTTPError as exc:
        return TestOutcome(False, f"تعذّر الوصول إلى graph.facebook.com: {type(exc).__name__}")
    if response.status_code >= 400:
        return TestOutcome(False, f"Meta رفض الفحص ({response.status_code}): {response.text[:220]}")
    data = (response.json() or {}).get("data") or {}
    if not data.get("is_valid"):
        return TestOutcome(False, "الـToken غير صالح — منتهي أو ملغى من App dashboard")
    if data.get("phone_number_id") and str(data["phone_number_id"]) != str(phone_id):
        return TestOutcome(False, f"الـToken يخصّ رقمًا آخر: {data['phone_number_id']} ≠ {phone_id}")
    app_name = data.get("application") or {}
    label = app_name.get("name") if isinstance(app_name, dict) else str(app_name)
    return TestOutcome(True, f"الاتصال سليم — Number ID {phone_id}" + (f"، التطبيق {label}" if label else ""))


def _test_telephony(resolved: ResolvedIntegration) -> TestOutcome:
    """Self-test of the signature contract: a PBX is only as good as the HMAC both sides agree on."""
    from app.core.security import verify_webhook_signature

    secret = resolved.secret("webhook_secret")
    if not secret:
        return TestOutcome(False, "ناقص: webhook_secret غير مضبوط، فكل حدث وارد سيُرفض بالتوقيع")
    sample = b'{"event":"call_started","from":"+201000000000"}'
    signature = "sha256=" + hmac.new(secret.encode(), sample, hashlib.sha256).hexdigest()
    if not verify_webhook_signature(sample, signature, secret):
        return TestOutcome(False, "تحقّق التوقيع فشل محليًا — تهيئة الخادم غير متسقة")
    return TestOutcome(True, "التوقيع يعمل (sha256). ضع عنوان الاستدعاء المعروض أسفل البطاقة في السنترال.")


async def _test_email(resolved: ResolvedIntegration, *, to: str, probe_only: bool) -> TestOutcome:
    import anyio

    host = resolved.value("host")
    if not host:
        return TestOutcome(False, "ناقص: SMTP host غير مضبوط (لا في الإعدادات ولا في البيئة)")
    port = resolved.number("port", 1025)
    encryption = str(resolved.config.get("encryption") or "none")
    username = resolved.value("username")
    password = resolved.secret("password")
    from_email = resolved.value("from_email")
    args = (host, port, encryption, username, password, from_email, resolved.value("from_name"), resolved.value("reply_to"), to, probe_only)
    return await anyio.to_thread.run_sync(functools.partial(_smtp_probe, *args))


def _smtp_probe(
    host: str,
    port: int,
    encryption: str,
    username: str,
    password: str,
    from_email: str,
    from_name: str,
    reply_to: str,
    to: str,
    probe_only: bool,
) -> TestOutcome:
    from email.message import EmailMessage

    context = ssl.create_default_context()
    try:
        if encryption == "ssl":
            client: smtplib.SMTP = smtplib.SMTP_SSL(host, port, timeout=12, context=context)
        else:
            client = smtplib.SMTP(host, port, timeout=12)
        with client:
            client.ehlo()
            if encryption == "starttls":
                client.starttls(context=context)
                client.ehlo()
            if username:
                client.login(username, password)
            if probe_only:
                return TestOutcome(True, f"المصافحة نجحت مع {host}:{port} ({encryption}) ولم تُرسل رسالة.")
            message = EmailMessage()
            message["From"] = f"{from_name} <{from_email}>" if from_name else from_email
            message["To"] = to
            message["Subject"] = "Broker Hub — اختبار إعدادات البريد"
            if reply_to:
                message["Reply-To"] = reply_to
            message.set_content("رسالة اختبار من شاشة الإعدادات.\n")
            client.send_message(message)
            return TestOutcome(True, f"أُرسلت رسالة اختبار إلى {to} عبر {host}:{port}.")
    except (smtplib.SMTPException, OSError) as exc:
        return TestOutcome(False, f"{type(exc).__name__}: {str(exc)[:220]}")


async def _fetch_meta_templates(account: str, token: str) -> tuple[list[dict[str, Any]], str]:
    import httpx

    try:
        async with httpx.AsyncClient(timeout=20) as client:
            response = await client.get(
                f"https://graph.facebook.com/v21.0/{account}/message_templates",
                params={"fields": "name,language,status,category", "limit": 100},
                headers={"Authorization": f"Bearer {token}"},
            )
    except httpx.HTTPError as exc:
        return [], f"تعذّر الوصول إلى Meta: {type(exc).__name__}"
    if response.status_code >= 400:
        return [], f"Meta رفض الطلب ({response.status_code}): {response.text[:220]}"
    payload = response.json() or {}
    templates = [
        {
            "name": row.get("name") or "",
            "language": row.get("language") or "",
            "status": str(row.get("status") or "UNKNOWN").upper(),
            "category": row.get("category") or "",
        }
        for row in payload.get("data") or []
    ]
    return templates, f"جُمِّعت {len(templates)} قالبًا من Meta."
