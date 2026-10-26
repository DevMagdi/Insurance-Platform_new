from __future__ import annotations

import json
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from fastapi import APIRouter, BackgroundTasks, Header, Request
from fastapi.responses import HTMLResponse, PlainTextResponse
from pydantic import BaseModel, Field

from app.api.v1.deps import DbSession
from app.core.config import get_settings
from app.core.errors import Forbidden
from app.integrations.base import StorageProvider, WhatsAppProvider
from app.integrations.registry import telephony_provider, whatsapp_provider
from app.integrations.storage import storage
from app.services import intake

router = APIRouter(tags=["webhooks & simulator"])


async def stage_inbound_media(
    provider: WhatsAppProvider, storage_backend: StorageProvider, external_id: str, media_id: str | None
) -> tuple[str | None, str | None, int]:
    """Copy inbound provider media into our own bucket.

    Playback must never depend on the provider keeping the file, and the URLs the UI gets back are
    short-TTL signed ones (spec §6.4). Returns ``(object_key, mime, size)``; all ``None``/0 when the
    event carries no media.
    """
    if not media_id:
        return None, None, 0
    payload, mime = await provider.fetch_media(str(media_id))
    safe_external = re.sub(r"[^A-Za-z0-9_.-]", "_", external_id)[:80]
    safe_media = re.sub(r"[^A-Za-z0-9_.-]", "_", str(media_id))[:60]
    key = f"media/{safe_external}/{safe_media}"
    storage_backend.put_object(key, payload, mime or "application/octet-stream")
    return key, mime, len(payload)


@router.get("/webhooks/whatsapp", summary="Meta verification handshake")
async def whatsapp_verify(hub_mode: str | None = None, hub_challenge: str | None = None, hub_verify_token: str | None = None) -> Any:
    if hub_mode == "subscribe" and hub_verify_token == get_settings().WHATSAPP_VERIFY_TOKEN:
        return PlainTextResponse(hub_challenge or "")
    raise Forbidden("Verification failed")


@router.post("/webhooks/whatsapp", summary="Inbound WhatsApp (signature-checked, idempotent)")
async def whatsapp_webhook(request: Request, session: DbSession, background: BackgroundTasks) -> dict[str, Any]:
    raw = await request.body()
    provider = whatsapp_provider()
    if not provider.verify_signature(raw, request.headers.get("x-hub-signature-256")):
        raise Forbidden("Invalid webhook signature")
    from app.integrations.whatsapp import parse_inbound

    events = parse_inbound(raw)
    storage_backend = storage()

    results = []
    for event in events:
        if event.get("status"):
            results.append({"external_id": event["external_id"], "status": "delivery_update"})
            continue
        # Inbound media is copied into our own bucket, so playback never depends on the
        # provider keeping the file (and the portal/rep URLs stay short-lived & signed).
        media_key, media_mime, media_size = await stage_inbound_media(
            provider, storage_backend, str(event["external_id"]), event.get("media_id")
        )
        results.append(
            await intake.ingest_whatsapp_message(
                session,
                external_id=str(event["external_id"]),
                mobile=event.get("mobile"),
                body=event.get("body"),
                sender_name=event.get("sender_name"),
                media_kind=event.get("media_kind"),
                media_object_key=media_key,
                media_mime=media_mime,
                media_size=media_size,
                duration_s=event.get("duration_s"),
            )
        )
    await session.commit()
    _ = background
    return {"received": len(events), "results": results}


class _SimWhatsApp(BaseModel):
    mobile: str = Field(description="caller/employee mobile, any Egyptian format")
    body: str | None = None
    sender_name: str | None = None
    media_kind: str | None = None
    media_id: str | None = Field(default=None, description="set it to fetch (and store) a fake voice note")
    duration_s: int | None = None
    external_id: str | None = None


@router.post("/dev/sim/whatsapp", summary="Simulator: deliver an inbound WhatsApp message")
async def sim_whatsapp(body: _SimWhatsApp, session: DbSession) -> dict[str, Any]:
    settings = get_settings()
    if settings.INTEGRATIONS_DRIVER != "sim" and not settings.DEBUG:
        raise Forbidden("The simulator is disabled when INTEGRATIONS_DRIVER=live")
    external_id = body.external_id or f"wamid.sim_{datetime.now(UTC).timestamp():.6f}"
    provider = whatsapp_provider()
    media_key, media_mime, media_size = await stage_inbound_media(provider, storage(), external_id, body.media_id)
    result = await intake.ingest_whatsapp_message(
        session,
        external_id=external_id,
        mobile=body.mobile,
        body=body.body,
        sender_name=body.sender_name,
        media_kind=body.media_kind,
        media_object_key=media_key,
        media_mime=media_mime,
        media_size=media_size,
        duration_s=body.duration_s,
    )
    await session.commit()
    return result


_PANEL_HTML_PATH = Path(__file__).with_name("sim_panel.html")


def _panel_html() -> str:
    """The markup sits in a sibling file so the CSS lines stay readable."""
    return _PANEL_HTML_PATH.read_text(encoding="utf-8")


@router.get("/dev/sim", summary="Simulator panel (only when INTEGRATIONS_DRIVER=sim)", include_in_schema=False)
async def sim_panel() -> HTMLResponse:
    settings = get_settings()
    if settings.INTEGRATIONS_DRIVER != "sim" and not settings.DEBUG:
        raise Forbidden("The simulator panel is disabled when INTEGRATIONS_DRIVER=live")
    return HTMLResponse(_panel_html())


class _SimCall(BaseModel):
    provider_call_id: str | None = None
    from_number: str
    to_number: str | None = None
    caller_name: str | None = None
    duration_s: int = 45
    with_recording: bool = True
    recording_consent: bool = True


@router.post("/dev/sim/call", summary="Simulator: inbound call → request → recording in storage")
async def sim_call(body: _SimCall, session: DbSession) -> dict[str, Any]:
    settings = get_settings()
    if settings.INTEGRATIONS_DRIVER != "sim" and not settings.DEBUG:
        raise Forbidden("The simulator is disabled when INTEGRATIONS_DRIVER=live")
    call_id = body.provider_call_id or f"simcall_{datetime.now(UTC).strftime('%Y%m%d%H%M%S%f')}"
    started = datetime.now(UTC)
    started_result = await intake.ingest_call_event(
        session,
        provider_call_id=call_id,
        event="call.started",
        from_number=body.from_number,
        to_number=body.to_number,
        caller_name=body.caller_name,
        started_at=started,
        recording_consent=body.recording_consent,
    )
    await session.commit()
    ended = await intake.ingest_call_event(
        session,
        provider_call_id=call_id,
        event="call.ended",
        from_number=body.from_number,
        started_at=started,
        ended_at=datetime.now(UTC),
        duration_s=body.duration_s,
    )
    await session.commit()

    media_key = None
    if body.with_recording:
        from app.core.storage_bytes import silence_wav
        from app.integrations.storage import storage

        media_key = f"calls/{call_id}.wav"
        payload = silence_wav(seconds=max(1.0, min(float(body.duration_s), 120.0)), tone_hz=320.0)
        storage().put_object(media_key, payload, "audio/wav")
        attached = await intake.ingest_call_event(
            session,
            provider_call_id=call_id,
            event="recording_ready",
            from_number=body.from_number,
            recording_object_key=media_key,
            recording_consent=body.recording_consent,
            recording_size=len(payload),
        )
        await session.commit()
        ended["recording"] = attached.get("status")
    return {**started_result, **ended, "recording_object_key": media_key}


@router.post("/webhooks/telephony", summary="Call-centre events (started/ended/recording_ready)")
async def telephony_webhook(
    request: Request,
    session: DbSession,
    x_call_signature: str | None = Header(default=None),
) -> dict[str, Any]:
    raw = await request.body()
    if not telephony_provider().verify_signature(raw, x_call_signature):
        raise Forbidden("Invalid webhook signature")
    try:
        body = json.loads(raw or b"{}")
    except json.JSONDecodeError as exc:
        raise Forbidden("Body must be JSON") from exc
    result = await intake.ingest_call_event(
        session,
        provider_call_id=str(body.get("call_id") or body.get("provider_call_id") or ""),
        event=str(body.get("event", "call.started")),
        direction=str(body.get("direction", "inbound")),
        from_number=body.get("from"),
        to_number=body.get("to"),
        caller_name=body.get("caller_name"),
        started_at=_ts(body.get("started_at")),
        ended_at=_ts(body.get("ended_at")),
        duration_s=body.get("duration_s"),
        recording_object_key=body.get("recording_key"),
        recording_consent=bool(body.get("recording_consent", False)),
    )
    await session.commit()
    return result


def _ts(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)
