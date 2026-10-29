"""Contract tests for the WhatsApp connection test + webhook media resilience (ADR-016 follow-up).

Meta's `debug_token` needs an *app* access token (`{app_id}|{app_secret}`); the live driver is
exercised through `httpx.MockTransport`, never the real network, and no secret value is printed.
"""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import time
from datetime import UTC, datetime, timedelta

import httpx
from app.core.db import get_sessionmaker
from app.integrations import whatsapp as whatsapp_mod
from app.integrations.whatsapp import WhatsAppMeta
from app.models.integrations import WebhookEvent
from app.services import integrations_settings as cfg
from sqlalchemy import select

TOKEN = "EAAG-connection-test-token"
PHONE_ID = "109999888777"


def _resolved(*, config: dict | None = None, secrets: dict | None = None) -> cfg.ResolvedIntegration:
    return cfg.ResolvedIntegration(
        provider="whatsapp",
        is_live=True,
        config={"phone_number_id": PHONE_ID, **(config or {})},
        secrets={"access_token": TOKEN, "app_secret": "real-app-secret", **(secrets or {})},
    )


def _run(resolved: cfg.ResolvedIntegration, handler) -> tuple[cfg.TestOutcome, list[httpx.Request]]:
    seen: list[httpx.Request] = []

    def counting(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return handler(request)

    whatsapp_mod.use_transport(httpx.MockTransport(counting))
    try:
        outcome = asyncio.run(cfg._test_whatsapp(resolved))
    finally:
        whatsapp_mod.use_transport(None)
    return outcome, seen


def _ok_handler(*, app_id: str = "111", expires_at: int = 0, probe_status: int = 200):
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/debug_token"):
            return httpx.Response(
                200,
                json={"data": {"is_valid": True, "app_id": app_id, "expires_at": expires_at, "application": {"name": "Broker App"}}},
            )
        return httpx.Response(probe_status, json={"display_phone_number": "+20 100 000 0000", "verified_name": "وسيط التأمين"})

    return handler


def test_debug_token_sends_app_access_token_when_app_id_saved() -> None:
    outcome, seen = _run(_resolved(config={"app_id": "111"}), _ok_handler())
    assert outcome.ok is True, outcome.detail
    debug = next(r for r in seen if r.url.path.endswith("/debug_token"))
    assert debug.url.params["input_token"] == TOKEN
    assert debug.url.params["access_token"] == "111|real-app-secret"
    assert "وسيط التأمين" in outcome.detail  # verified name from the phone probe


def test_debug_token_falls_back_to_stored_token_without_app_id() -> None:
    outcome, seen = _run(_resolved(), _ok_handler())
    assert outcome.ok is True, outcome.detail
    debug = next(r for r in seen if r.url.path.endswith("/debug_token"))
    assert debug.url.params["access_token"] == TOKEN


def test_app_id_mismatch_fails_and_names_both_ids() -> None:
    outcome, _ = _run(_resolved(config={"app_id": "111"}), _ok_handler(app_id="999"))
    assert outcome.ok is False
    assert "111" in outcome.detail and "999" in outcome.detail


def test_phone_probe_failure_fails_with_status() -> None:
    outcome, _ = _run(_resolved(config={"app_id": "111"}), _ok_handler(probe_status=400))
    assert outcome.ok is False
    assert "400" in outcome.detail


def test_placeholder_app_secret_fails_before_any_network_call() -> None:
    outcome, seen = _run(_resolved(secrets={"app_secret": "dev-app-secret"}), _ok_handler())
    assert outcome.ok is False
    assert seen == [], "a placeholder secret must fail locally, with zero network calls"
    assert "App Secret" in outcome.detail


def test_temporary_token_passes_with_system_user_warning() -> None:
    outcome, _ = _run(_resolved(config={"app_id": "111"}), _ok_handler(expires_at=int(time.time()) + 3600))
    assert outcome.ok is True, outcome.detail
    assert "System User" in outcome.detail


async def test_state_hides_an_error_that_a_later_success_superseded(client) -> None:
    async with get_sessionmaker()() as session:
        now = datetime.now(UTC)
        session.add_all(
            [
                WebhookEvent(
                    provider="whatsapp", event_type="rejected", status="error", detail="رفض قديم", occurred_at=now - timedelta(hours=2)
                ),
                WebhookEvent(provider="whatsapp", event_type="message", status="ok", occurred_at=now - timedelta(hours=1)),
            ]
        )
        await session.commit()
        fresh = (await cfg.state(session, "whatsapp")).last_error
        session.add(WebhookEvent(provider="whatsapp", event_type="rejected", status="error", detail="رفض أحدث", occurred_at=now))
        await session.commit()
        stale = (await cfg.state(session, "whatsapp")).last_error

    assert fresh is None, "an error older than the latest success is stale and must not show"
    assert stale == "رفض أحدث"


async def test_webhook_still_ingests_when_media_fetch_fails(client, monkeypatch) -> None:
    from app.api.v1.endpoints import webhooks

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, json={"error": {"message": "media gone"}})

    whatsapp_mod.use_transport(httpx.MockTransport(handler))
    monkeypatch.setattr(webhooks, "whatsapp_provider", lambda: WhatsAppMeta(token=TOKEN, phone_number_id=PHONE_ID, app_secret="s3cret-app"))
    try:
        raw = json.dumps(
            {
                "object": "whatsapp_business_account",
                "entry": [
                    {
                        "changes": [
                            {
                                "value": {
                                    "contacts": [{"wa_id": "201000000123", "profile": {"name": "عميل"}}],
                                    "messages": [
                                        {
                                            "id": "wamid.media_fail_1",
                                            "from": "201000000123",
                                            "type": "document",
                                            "document": {"id": "media-gone-1", "filename": "x.pdf", "caption": "مستند الوثيقة"},
                                        }
                                    ],
                                }
                            }
                        ]
                    }
                ],
            }
        ).encode()
        signature = "sha256=" + hmac.new(b"s3cret-app", raw, hashlib.sha256).hexdigest()
        response = await client.post(
            "/api/v1/webhooks/whatsapp",
            content=raw,
            headers={"content-type": "application/json", "x-hub-signature-256": signature},
        )
    finally:
        whatsapp_mod.use_transport(None)

    assert response.status_code == 200, response.text
    assert response.json()["results"][0]["status"] in {"created", "appended", "duplicate"}
    async with get_sessionmaker()() as session:
        events = (await session.execute(select(WebhookEvent).where(WebhookEvent.event_type == "media_fetch_failed"))).scalars().all()
    assert len(events) == 1
    assert events[0].status == "error"
    assert events[0].external_id == "wamid.media_fail_1"
