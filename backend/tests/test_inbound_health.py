"""INBOUND HEALTH (WhatsApp debugging round, item 3): «متصل» only proves the credentials can send.

`state(...).inbound_health` is derived from the webhook-event ledger — receiving within 24h /
stale / never / failing (a rejection newer than the last good delivery) — and the connection test
reports the app's WABA webhook subscription as a warning, never as a failed test.
"""

from __future__ import annotations

import time
from datetime import UTC, datetime, timedelta

import httpx
import pytest
from app.core.db import get_sessionmaker
from app.integrations import whatsapp as whatsapp_meta
from app.models.integrations import WebhookEvent
from app.services import integrations_settings


async def _seed_event(status: str, *, hours_ago: float) -> None:
    async with get_sessionmaker()() as session:
        session.add(
            WebhookEvent(
                provider="whatsapp",
                event_type="message",
                status=status,
                detail="seed",
                occurred_at=datetime.now(UTC) - timedelta(hours=hours_ago),
            )
        )
        await session.commit()


async def _health() -> str:
    async with get_sessionmaker()() as session:
        return (await integrations_settings.state(session, "whatsapp")).inbound_health


@pytest.mark.asyncio
async def test_inbound_health_states(client) -> None:
    assert await _health() == "never"
    await _seed_event("ok", hours_ago=1)
    assert await _health() == "receiving"
    await _seed_event("rejected", hours_ago=0.5)
    assert await _health() == "failing"
    await _seed_event("ok", hours_ago=0.25)
    assert await _health() == "receiving"


@pytest.mark.asyncio
async def test_inbound_health_stale(client) -> None:
    await _seed_event("ok", hours_ago=30)
    assert await _health() == "stale"


def _transport(subscribed: list | None, *, subs_status: int = 200):
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/debug_token"):
            return httpx.Response(
                200,
                json={
                    "data": {
                        "is_valid": True,
                        "app_id": "1234567890123456",
                        "expires_at": int(time.time()) + 30 * 86400,
                        "application": {"name": "Test App"},
                    }
                },
            )
        if request.url.path.endswith("/subscribed_apps"):
            if subs_status >= 400:
                return httpx.Response(subs_status, json={"error": {"message": "nope"}})
            return httpx.Response(200, json={"data": subscribed})
        return httpx.Response(200, json={"display_phone_number": "+20 100", "verified_name": "Acme"})

    return httpx.MockTransport(handler)


def _resolved() -> integrations_settings.ResolvedIntegration:
    return integrations_settings.ResolvedIntegration(
        provider="whatsapp",
        config={"phone_number_id": "111", "business_account_id": "999", "app_id": "1234567890123456"},
        secrets={"access_token": "tok", "app_secret": "real-secret"},
        is_live=True,
    )


@pytest.mark.asyncio
async def test_subscribed_apps_reported_and_failures_are_warnings() -> None:
    whatsapp_meta.use_transport(_transport([{"id": "1234567890123456"}]))
    try:
        outcome = await integrations_settings._test_whatsapp(_resolved())
        assert outcome.ok
        assert "مشترك في ويبوك" in outcome.detail

        whatsapp_meta.use_transport(_transport([]))
        outcome = await integrations_settings._test_whatsapp(_resolved())
        assert outcome.ok  # a missing subscription warns; it does not fail the credential test
        assert "لن تصل رسائل واردة" in outcome.detail

        whatsapp_meta.use_transport(_transport(None, subs_status=500))
        outcome = await integrations_settings._test_whatsapp(_resolved())
        assert outcome.ok
        assert "تعذّر فحص اشتراك" in outcome.detail
    finally:
        whatsapp_meta.use_transport(None)
