"""R12 — channels live: WhatsApp document/voice on the request, email intake, connection semantics (ADR-032)."""

from __future__ import annotations

import base64
import json
from uuid import UUID

import pytest
from app.core.db import get_sessionmaker
from app.models.requests import Attachment, AuditLog, RequestMessage
from sqlalchemy import func, select

from tests.helpers import login

MANAGER = "manager@brokerhub.test"
ADMIN = "admin@brokerhub.test"
REP = "rep_a@brokerhub.test"
pytestmark = pytest.mark.integration


def _wa(messages: list[dict], mobile: str = "010555000111") -> bytes:
    return json.dumps(
        {
            "object": "whatsapp_business_account",
            "entry": [
                {
                    "changes": [
                        {
                            "value": {
                                "contacts": [{"wa_id": mobile, "profile": {"name": "عميل"}}],
                                "messages": messages,
                            }
                        }
                    ]
                }
            ],
        }
    ).encode()


async def test_whatsapp_document_lands_on_thread_and_attachments(client, ids) -> None:
    raw = _wa(
        [
            {
                "id": "wamid.r12doc1",
                "from": "010555000111",
                "type": "document",
                "document": {
                    "id": "media-doc-1",
                    "filename": "policy-schedule.pdf",
                    "mime_type": "application/pdf",
                    "caption": "جدول الوثيقة",
                },
            },
            {"id": "wamid.r12voice1", "from": "010555000111", "type": "audio", "audio": {"id": "media-aud-1", "mime_type": "audio/ogg"}},
        ]
    )
    async with login(client, MANAGER) as mgr:
        delivered = await client.post("/api/v1/webhooks/whatsapp", content=raw, headers={"content-type": "application/json"})
        assert delivered.status_code == 200, delivered.text
        request_id = delivered.json()["results"][0]["request_id"]
        assert request_id

        detail = await client.get(f"/api/v1/requests/{request_id}", headers=mgr)
        assert detail.status_code == 200, detail.text
        body = detail.json()
        names = {a["filename"] for a in body["attachments"]}
        assert "policy-schedule.pdf" in names  # the customer's own filename, not our media id
        doc_message = next(m for m in body["messages"] if m["external_id"] == "wamid.r12doc1")
        assert [a["filename"] for a in doc_message["attachments"]] == ["policy-schedule.pdf"]
        assert doc_message["attachments"][0]["url"]  # signed staff URL issued with the detail

        listing = await client.get(f"/api/v1/requests/{request_id}/attachments", headers=mgr)
        assert listing.status_code == 200, listing.text
        doc = next(a for a in listing.json() if a["filename"] == "policy-schedule.pdf")

        issued = await client.get(f"/api/v1/requests/{request_id}/attachments/{doc['id']}/download-url", headers=mgr)
        assert issued.status_code == 200, issued.text
        assert issued.json()["url"].startswith("/api/v1/media/")
        async with get_sessionmaker()() as session:
            actions = (await session.execute(select(AuditLog.action).where(AuditLog.entity_id == UUID(doc["id"])))).scalars().all()
        assert "attachment.accessed" in actions

        # a rep with no request scope on this request cannot mint a URL for its files
        async with login(client, REP) as rep:
            refused = await client.get(f"/api/v1/requests/{request_id}/attachments/{doc['id']}/download-url", headers=rep)
            assert refused.status_code in (403, 404), refused.text


async def test_email_webhook_creates_threads_and_dedupes(client, ids) -> None:
    pdf = base64.b64encode(b"%PDF-fake").decode()
    payload = {
        "external_id": "mail-r12-1",
        "from": "Customer@Example.test",
        "from_name": "عميل بريد",
        "subject": "استفسار عن وثيقة",
        "body_text": "محتاج نسخة من الوثيقة",
        "attachments": [{"filename": "id.pdf", "mime": "application/pdf", "content_base64": pdf}],
    }
    first = await client.post("/api/v1/webhooks/email", json=payload)
    assert first.status_code == 200, first.text
    request_id = first.json()["request_id"]

    dupe = await client.post("/api/v1/webhooks/email", json=payload)
    assert dupe.status_code == 200 and dupe.json()["status"] == "duplicate"

    second = await client.post(
        "/api/v1/webhooks/email", json={**payload, "external_id": "mail-r12-2", "body_text": "متابعة", "attachments": []}
    )
    assert second.status_code == 200, second.text
    assert second.json()["request_id"] == request_id  # same sender → same thread, not a new ticket
    assert second.json()["status"] == "appended"

    async with get_sessionmaker()() as session:
        messages = (
            await session.execute(select(func.count()).select_from(RequestMessage).where(RequestMessage.request_id == UUID(request_id)))
        ).scalar_one()
        files = (
            await session.execute(select(func.count()).select_from(Attachment).where(Attachment.request_id == UUID(request_id)))
        ).scalar_one()
    assert messages == 2 and files == 1

    async with login(client, MANAGER) as mgr:
        detail = await client.get(f"/api/v1/requests/{request_id}", headers=mgr)
        assert detail.status_code == 200, detail.text
        assert detail.json()["channel"] == "email"
        assert detail.json()["attachments"][0]["filename"] == "id.pdf"

    bad = await client.post(
        "/api/v1/webhooks/email",
        json={
            "external_id": "mail-bad",
            "from": "a@b.test",
            "attachments": [{"filename": "x.exe", "mime": "application/x-msdownload", "content_base64": pdf}],
        },
    )
    assert bad.status_code == 422, bad.text


async def test_settings_report_connection_semantics(client, ids) -> None:
    async with login(client, ADMIN) as admin:
        rows = await client.get("/api/v1/settings/integrations", headers=admin)
        assert rows.status_code == 200, rows.text
        for row in rows.json():
            assert row["connection_status"] in {"connected", "not_connected", "error"}
            assert isinstance(row["missing_fields"], list)
            if row["missing_fields"]:
                assert row["connection_status"] != "connected"
        urls = await client.get("/api/v1/settings/integrations/webhook-urls", headers=admin)
        assert urls.status_code == 200, urls.text
        providers = {item["provider"] for item in urls.json()["items"]}
        assert {"whatsapp", "telephony", "email"} <= providers
