"""INTAKE OUTCOME IN THE LEDGER (WhatsApp debugging round, item 4).

«200 but no new request» used to be indistinguishable from a lost message. The webhook now writes
the intake outcome (created / appended / lead_activity / duplicate) plus the match kind and the
request number into the `webhook_events` "message" row detail. Matching rules are unchanged.
"""

from __future__ import annotations

import json

from app.core.db import get_sessionmaker
from app.models.clients import Client, InsuredPerson
from app.models.integrations import WebhookEvent
from sqlalchemy import select


def _payload(wamid: str, wa_id: str, body: str = "مرحبا") -> bytes:
    return json.dumps(
        {
            "object": "whatsapp_business_account",
            "entry": [
                {
                    "changes": [
                        {
                            "value": {
                                "contacts": [{"wa_id": wa_id, "profile": {"name": "متصل"}}],
                                "messages": [{"id": wamid, "from": wa_id, "type": "text", "text": {"body": body}}],
                            }
                        }
                    ]
                }
            ],
        }
    ).encode()


async def _message_event(wamid: str) -> WebhookEvent:
    async with get_sessionmaker()() as session:
        rows = (
            (await session.execute(select(WebhookEvent).where(WebhookEvent.event_type == "message", WebhookEvent.external_id == wamid)))
            .scalars()
            .all()
        )
    assert len(rows) == 1
    return rows[0]


async def test_lead_match_records_lead_activity_outcome(client) -> None:
    # conftest lead_a owns +201000000001 — a Lead match adds an activity only, never a request
    response = await client.post(
        "/api/v1/webhooks/whatsapp",
        content=_payload("wamid.lead_outcome_1", "201000000001"),
        headers={"content-type": "application/json"},
    )
    assert response.status_code == 200, response.text
    assert response.json()["results"][0]["status"] == "lead_activity"
    event = await _message_event("wamid.lead_outcome_1")
    assert event.status == "ok"
    assert event.detail and "outcome=lead_activity" in event.detail and "matched=lead" in event.detail


async def test_insured_open_thread_append_records_appended_outcome(client) -> None:
    async with get_sessionmaker()() as session:
        owner = (await session.execute(select(Client).limit(1))).scalars().first()
        assert owner is not None
        session.add(InsuredPerson(client_id=owner.id, name="مؤمّن تجريبي", mobile="+201077777777"))
        await session.commit()

    first = await client.post(
        "/api/v1/webhooks/whatsapp",
        content=_payload("wamid.insured_1", "201077777777"),
        headers={"content-type": "application/json"},
    )
    assert first.json()["results"][0]["status"] == "created"
    request_number = first.json()["results"][0]["request_number"]

    second = await client.post(
        "/api/v1/webhooks/whatsapp",
        content=_payload("wamid.insured_2", "201077777777", body="متابعة"),
        headers={"content-type": "application/json"},
    )
    result = second.json()["results"][0]
    assert result["status"] == "appended"
    assert result["request_number"] == request_number
    event = await _message_event("wamid.insured_2")
    assert event.detail and "outcome=appended" in event.detail and f"request={request_number}" in event.detail
