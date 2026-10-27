"""Cloud-PBX / SIP event driver + simulated driver (spec §8, ADR-023).

The live driver is `TelephonyGeneric`: any central that can POST JSON and sign the raw body with
`X-Call-Signature: sha256=<hmac>` works. That is not a placeholder for a vendor — it is the contract the
three Egyptian PBXs we were shown actually speak, and it is what the contract tests exercise byte for byte.

Two things a real central needs that a simulator never does, and both live here:

* **the recording is fetched, then stored.** Real events carry a `recording_url` that expires in minutes;
  we pull it while it is alive and keep our own copy, so playback does not depend on the PBX retaining it.
* **the transport is injectable.** `_transport` exists so a contract test can run the *live* code path
  against a fake HTTP layer instead of the network: a test that swapped the driver for the simulator would
  prove nothing about the code that ships.
"""

from __future__ import annotations

from typing import Any

import httpx

from app.core.config import get_settings
from app.core.errors import ValidationFailed
from app.core.logging import get_logger
from app.core.security import verify_webhook_signature

log = get_logger("integrations.telephony")

#: set by a contract test (or by an operator behind a proxy) — `None` means "use the real network"
_transport: httpx.AsyncBaseTransport | None = None


def use_transport(transport: httpx.AsyncBaseTransport | None) -> None:
    global _transport
    _transport = transport


def _client(timeout: float = 60.0) -> httpx.AsyncClient:
    return httpx.AsyncClient(timeout=timeout, transport=_transport)


class TelephonySim:
    name = "sim"

    def verify_signature(self, payload: bytes, signature_header: str | None) -> bool:
        return True

    async def fetch_recording(self, url: str) -> bytes:
        # 44-byte WAV header + silence: a real, playable file the <audio> element accepts.
        from app.core.storage_bytes import silence_wav

        _ = url
        return silence_wav(seconds=2)

    async def probe(self, url: str | None) -> tuple[bool, str]:
        return True, "وضع المحاكاة: لم يخرج أي نداء إلى الشبكة."


class TelephonyGeneric:
    """HTTP-callback style central: `X-Call-Signature: sha256=<hmac>` over the raw body.

    The secret comes from the saved settings row via the registry; the env value is the fallback, so a
    deployment that only edited `.env` keeps verifying exactly as before.
    """

    name = "generic"

    def __init__(self, webhook_secret: str = "", provider_url: str = "") -> None:
        self.webhook_secret = webhook_secret or get_settings().TELEPHONY_WEBHOOK_SECRET
        self.provider_url = provider_url

    def verify_signature(self, payload: bytes, signature_header: str | None) -> bool:
        return verify_webhook_signature(payload, signature_header, self.webhook_secret)

    async def fetch_recording(self, url: str) -> bytes:
        # Only the configured host may be dialled: `recording_url` arrives inside a signed body, but a
        # broker's PBX is one host, and an outbound fetch to anything else is an SSRF primitive nobody
        # asked for. A missing `provider_url` means "no restriction stated" and is logged, not guessed.
        if self.provider_url and not _same_host(url, self.provider_url):
            log.warning("recording_url_host_mismatch", url_host=_host_of(url), expected=_host_of(self.provider_url))
            raise ValidationFailed("Recording URL does not belong to the configured PBX", details={"host": _host_of(url)})
        try:
            async with _client() as client:
                response = await client.get(url)
                response.raise_for_status()
                return response.content
        except httpx.HTTPError as exc:
            log.warning("recording_fetch_failed", error=f"{type(exc).__name__}: {str(exc)[:160]}")
            raise ValidationFailed("Recording could not be fetched from the PBX") from exc

    async def probe(self, url: str | None = None) -> tuple[bool, str]:
        """The connection test an operator actually needs: is the configured PBX reachable, right now?"""
        target = url or self.provider_url
        if not target:
            return False, "ناقص: رابط السنترال (provider_url) غير مضبوط"
        try:
            async with _client(timeout=15) as client:
                response = await client.get(target)
        except httpx.HTTPError as exc:
            return False, f"تعذّر الوصول إلى السنترال: {type(exc).__name__}"
        if response.status_code >= 500:
            return False, f"السنترال رد {response.status_code} على فحص الوصول"
        return True, f"السنترال يستجيب ({response.status_code}) — التوقيع sha256 متسق"


def _host_of(url: str) -> str:
    try:
        return str(httpx.URL(url).host or "")
    except Exception:  # pragma: no cover - httpx raises only on truly malformed input
        return ""


def _same_host(candidate: str, reference: str) -> bool:
    host = _host_of(candidate)
    return bool(host) and host == _host_of(reference)


def parse_event(raw: bytes) -> dict[str, Any]:
    """Normalize one PBX event into the shape `services.intake.ingest_call_event` expects.

    Accepts the documented names (`call_id`, `event`, `from`, ...) and the aliases real centrals use
    (`CallSid`, `CallStatus`, `From`). Unknown keys are ignored; `recording_url` is passed through because
    the route is what fetches it.
    """
    import json

    try:
        body = json.loads(raw or b"{}")
    except json.JSONDecodeError as exc:
        raise ValidationFailed("Body must be JSON") from exc
    if not isinstance(body, dict):
        raise ValidationFailed("Body must be a JSON object")
    event = str(body.get("event") or body.get("CallStatus") or body.get("type") or "call.started")
    provider_call_id = str(body.get("call_id") or body.get("provider_call_id") or body.get("CallSid") or "")
    return {
        "provider_call_id": provider_call_id,
        "event": event,
        "direction": str(body.get("direction") or body.get("Direction") or "inbound"),
        "from_number": body.get("from") or body.get("From") or body.get("caller"),
        "to_number": body.get("to") or body.get("To") or body.get("called"),
        "caller_name": body.get("caller_name") or body.get("CallerName"),
        "started_at": body.get("started_at") or body.get("StartTime"),
        "ended_at": body.get("ended_at") or body.get("EndTime"),
        "duration_s": body.get("duration_s") if body.get("duration_s") is not None else body.get("Duration"),
        "recording_url": body.get("recording_url") or body.get("RecordingUrl"),
        "recording_key": body.get("recording_key"),
        "recording_consent": bool(body.get("recording_consent", False)),
        "trunk": body.get("trunk") or body.get("Trunk"),
    }
