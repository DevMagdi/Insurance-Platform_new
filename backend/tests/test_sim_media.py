"""Simulator media must survive a live-configured WhatsApp driver (item 2).

The panel invents `sim-media-<ts>` ids; fetching one from Meta would 400 and the panel would
500. Panel media is stored locally as fake bytes; a real-looking id still goes through
`stage_inbound_media`, but a provider failure degrades to text-only ingest, never a 500.
"""

from __future__ import annotations

from app.core.db import get_sessionmaker
from app.models.integrations import WebhookEvent
from sqlalchemy import select

from tests.helpers import login

MANAGER = "manager@brokerhub.test"


async def test_sim_voice_note_with_live_provider_stores_fake_bytes(client, monkeypatch) -> None:
    from app.api.v1.endpoints import dev_sim

    def forbidden_provider():
        raise AssertionError("panel media must never reach the provider")

    monkeypatch.setattr(dev_sim, "whatsapp_provider", forbidden_provider)
    inbound = await client.post(
        "/api/v1/dev/sim/whatsapp",
        json={
            "mobile": "+201127778899",
            "sender_name": "عميل محاكاة",
            "body": None,
            "media_kind": "audio",
            "media_id": "sim-media-12345",
            "duration_s": 7,
        },
    )
    assert inbound.status_code == 200, inbound.text
    request_id = inbound.json()["request_id"]
    assert request_id

    async with login(client, MANAGER) as auth:
        detail = await client.get(f"/api/v1/requests/{request_id}", headers=auth)
    assert detail.status_code == 200, detail.text
    message = detail.json()["messages"][0]
    assert message["attachments"], "the fake voice note must land as an attachment row"
    assert message["attachments"][0]["mime"].startswith("audio/")


class _FailingProvider:
    async def fetch_media(self, media_id: str):
        raise RuntimeError(f"Meta media lookup failed (500) for {media_id}")


async def test_real_looking_media_id_with_failing_provider_ingests_text(client, monkeypatch) -> None:
    from app.api.v1.endpoints import dev_sim

    monkeypatch.setattr(dev_sim, "whatsapp_provider", lambda: _FailingProvider())
    inbound = await client.post(
        "/api/v1/dev/sim/whatsapp",
        json={
            "mobile": "+201126667788",
            "sender_name": "عميل وسائط",
            "body": "نص الرسالة يصل رغم فشل الوسائط",
            "media_kind": "image",
            "media_id": "media-real-999",
        },
    )
    assert inbound.status_code == 200, inbound.text
    request_id = inbound.json()["request_id"]
    assert request_id

    async with login(client, MANAGER) as auth:
        detail = await client.get(f"/api/v1/requests/{request_id}", headers=auth)
    bodies = [m["body"] for m in detail.json()["messages"]]
    assert "نص الرسالة يصل رغم فشل الوسائط" in bodies

    async with get_sessionmaker()() as session:
        events = (await session.execute(select(WebhookEvent).where(WebhookEvent.event_type == "media_fetch_failed"))).scalars().all()
    assert len(events) == 1
    assert events[0].status == "error"
