"""Driver selection: the saved row wins, the environment is the fallback (spec §8, ADR-016 §1).

`prime(session)` loads `integration_configs` into process memory at startup and after every settings
write. It is a cache and not a second source of truth: the row is the source, and the two ways it can
disagree with a driver — a second API worker that never saw the write, a worker that started before the
row existed — are both fixed by the same line in `docs/runbook.md` (re-save, or restart the worker), which
is cheaper than a DB round trip on every outbound send.

Unprimed is a real state, not an error: the first boot of a fresh database has no rows, and unit tests call
`whatsapp_provider()` without a session. Both fall back to the environment so `INTEGRATIONS_DRIVER=live` +
env credentials still works exactly as it did before the settings screen existed.
"""

from __future__ import annotations

from typing import Any

from app.core.config import get_settings
from app.core.logging import get_logger
from app.integrations.ai_sim import AISim
from app.integrations.notifier import ConsoleNotifier, SmtpNotifier
from app.integrations.telephony import TelephonyGeneric, TelephonySim
from app.integrations.whatsapp import WhatsAppMeta, WhatsAppSim
from app.models.integrations import PROVIDERS
from app.services import integrations_settings as cfg

log = get_logger("integrations.registry")

_whatsapp: Any | None = None
_telephony: Any | None = None
_ai: Any | None = None
_email: Any | None = None
_primed: dict[str, cfg.ResolvedIntegration] | None = None
_env_fallback: dict[str, cfg.ResolvedIntegration] | None = None


async def prime(session: Any) -> None:
    """Load the saved rows into memory and rebuild the drivers. Never raises: an unavailable settings
    table (first boot, before `alembic upgrade`) must not take the API down with it."""
    global _primed
    try:
        _primed = await cfg.resolved_for_registry(session)
    except Exception as exc:  # pragma: no cover - depends on schema state, not on our logic
        log.warning("integrations_prime_skipped", error=f"{type(exc).__name__}: {str(exc)[:180]}")
        _primed = None
    reset_providers()


def is_primed() -> bool:
    return _primed is not None


def _snapshot() -> dict[str, cfg.ResolvedIntegration]:
    global _env_fallback
    if _primed:
        return _primed
    if _env_fallback is None:
        _env_fallback = {provider: _from_env(provider) for provider in PROVIDERS}
    return _env_fallback


def _from_env(provider: str) -> cfg.ResolvedIntegration:
    settings = get_settings()
    return cfg.ResolvedIntegration(
        provider=provider,
        is_live=settings.INTEGRATIONS_DRIVER == "live",
        config=cfg.effective_config(provider, None),
        secrets=cfg.secrets_for(provider, None),
    )


def resolved(provider: str) -> cfg.ResolvedIntegration:
    """Per-provider fallback: a snapshot that predates a new provider (or an empty primed cache because
    the settings table did not exist yet) must never raise inside a webhook handler."""
    return _snapshot().get(provider) or _from_env(provider)


def config_value(provider: str, key: str, fallback: Any = None) -> Any:
    """A non-secret setting, for the request paths that honor one (media staging, retention)."""
    value = resolved(provider).config.get(key)
    return fallback if value in (None, "") else value


def live_mode(provider: str) -> bool:
    return resolved(provider).is_live


def whatsapp_provider() -> Any:
    global _whatsapp
    if _whatsapp is None:
        state = resolved("whatsapp")
        token = state.secret("access_token")
        phone_number_id = state.value("phone_number_id")
        if state.is_live and token and phone_number_id:
            _whatsapp = WhatsAppMeta(
                token=token,
                phone_number_id=phone_number_id,
                app_secret=state.secret("app_secret"),
            )
        else:
            if state.is_live and (not token or not phone_number_id):
                log.warning("whatsapp_live_incomplete", has_token=bool(token), has_phone=bool(phone_number_id))
            _whatsapp = WhatsAppSim()
    return _whatsapp


def telephony_provider() -> Any:
    global _telephony
    if _telephony is None:
        state = resolved("telephony")
        # the provider dropdown is the operator's explicit choice; `sim` there beats a live row
        if state.is_live and state.config.get("provider") != "sim":
            _telephony = TelephonyGeneric(
                webhook_secret=state.secret("webhook_secret"),
                provider_url=str(state.value("provider_url") or ""),
            )
        else:
            _telephony = TelephonySim()
    return _telephony


def email_notifier() -> Any:
    """`SmtpNotifier` built from the saved row when live, the console when not.

    Sim mode is deliberately *not* an SMTP connection: a developer's machine has no mailpit running, and a
    worker that silently fails to reach port 1025 on every reminder is worse than one that logs the body.
    """
    global _email
    if _email is None:
        state = resolved("email")
        if not state.is_live or not state.value("host"):
            _email = ConsoleNotifier()
        else:
            _email = SmtpNotifier(
                host=state.value("host"),
                port=state.number("port", 1025),
                username=state.value("username"),
                password=state.secret("password"),
                encryption=str(state.config.get("encryption") or "none"),
                from_addr=state.value("from_email") or get_settings().EMAIL_FROM,
                from_name=state.value("from_name"),
                reply_to=state.value("reply_to"),
            )
    return _email


def ai_provider() -> Any:
    """Simulated by default (spec §8: every provider has a simulated driver).

    There is deliberately no `live` AI driver yet: no vendor is approved for the data this touches
    (recordings and client threads), so choosing a provider is a decision, not a ticket. Until it is
    made, `INTEGRATIONS_DRIVER=live` still returns the simulator and `docs/STATUS.md` says so.
    """

    global _ai
    if _ai is None:
        _ai = AISim()
    return _ai


def reset_providers() -> None:
    """Drop the built drivers *and* the env fallback, so the next call re-reads the snapshot."""
    global _whatsapp, _telephony, _email, _env_fallback
    _whatsapp = _telephony = _email = None
    _env_fallback = None
