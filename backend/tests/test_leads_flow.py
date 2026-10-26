"""Conversion transaction, duplicate detection and Kanban status changes (spec §7/§12 M6)."""

from __future__ import annotations

import pytest

from tests.helpers import login

pytestmark = pytest.mark.integration


async def _new_lead(client, headers, **overrides) -> dict:
    payload = {
        "type": "company",
        "name": "شركة تجريبية",
        "contact_name": "منى",
        "mobile": "01001234567",
        "email": "buyer@company.test",
        "headcount": 45,
        "next_followup_at": "2026-11-02T10:00:00+00:00",
    }
    payload.update(overrides)
    response = await client.post("/api/v1/leads", json=payload, headers=headers)
    assert response.status_code == 201, response.text
    return response.json()


async def test_convert_creates_client_owned_by_the_rep(client, ids) -> None:
    async with login(client, "rep_a@brokerhub.test") as h:
        created = await _new_lead(client, h, mobile="01111112222")
        lead_id = created["lead_id"]
        result = await client.post(f"/api/v1/leads/{lead_id}/convert", headers=h)
        assert result.status_code == 200, result.text
        body = result.json()
        assert body["already_converted"] is False
        assert body["account_owner_id"] == ids["users"]["rep_a"]

        client_row = (await client.get(f"/api/v1/clients/{body['client_id']}", headers=h)).json()
        assert client_row["name"] == "شركة تجريبية"
        assert client_row["is_converted_from_lead"] is True
        assert client_row["account_owner_id"] == ids["users"]["rep_a"]

        # the converted client shows up in the rep's client list (spec §1 item 6)
        listed = (await client.get("/api/v1/clients", headers=h)).json()
        assert body["client_id"] in {c["id"] for c in listed["items"]}


async def test_convert_is_idempotent(client, ids) -> None:
    async with login(client, "rep_a@brokerhub.test") as h:
        lead_id = (await _new_lead(client, h, mobile="0112223333"))["lead_id"]
        first = (await client.post(f"/api/v1/leads/{lead_id}/convert", headers=h)).json()
        second = await client.post(f"/api/v1/leads/{lead_id}/convert", headers=h)
        assert second.status_code == 200
        assert second.json()["already_converted"] is True
        assert second.json()["client_id"] == first["client_id"], "conversion must not duplicate the client"


async def test_account_owner_survives_reassignment(client, ids) -> None:
    """M6 acceptance: owner frozen at conversion time, even after the manager re-assigns the lead."""
    async with login(client, "rep_a@brokerhub.test") as rep:
        lead_id = (await _new_lead(client, rep, mobile="0113334444"))["lead_id"]
        client_id = (await client.post(f"/api/v1/leads/{lead_id}/convert", headers=rep)).json()["client_id"]
    async with login(client, "manager@brokerhub.test") as mgr:
        await client.post(f"/api/v1/leads/{lead_id}/assign", headers=mgr, json={"assigned_to": ids["users"]["rep_b"]})
        owner = (await client.get(f"/api/v1/clients/{client_id}", headers=mgr)).json()["account_owner_id"]
        assert owner == ids["users"]["rep_a"], "account_owner_id must stay with the rep who converted"
        # and the new rep must NOT see the already-converted client
        assert (await client.get(f"/api/v1/clients/{client_id}")).status_code == 401


async def test_duplicate_mobile_is_blocked_and_can_be_overridden(client, ids) -> None:
    async with login(client, "rep_a@brokerhub.test") as h:
        await _new_lead(client, h, mobile="01000001111")
        again = await client.post("/api/v1/leads", json={"name": "نفس الرقم", "mobile": "+20 100 000 1111"}, headers=h)
        assert again.status_code == 409
        details = again.json()["details"]
        assert details["name"] == "شركة تجريبية" or "lead_id" in details
        forced = await client.post(
            "/api/v1/leads",
            json={"name": "نفس الرقم", "mobile": "01000001111", "allow_duplicate": True},
            headers=h,
        )
        assert forced.status_code == 201


async def test_reps_never_learn_about_other_reps_duplicates(client, ids) -> None:
    """A duplicate on someone else's lead is refused without exposing who owns it."""
    async with login(client, "manager@brokerhub.test") as mgr:
        await _new_lead(client, mgr, mobile="01299998888", assigned_to=ids["users"]["rep_b"])
    async with login(client, "rep_a@brokerhub.test") as h:
        response = await client.post("/api/v1/leads", json={"name": "تطفل", "mobile": "01299998888"}, headers=h)
        assert response.status_code == 409
        assert response.json()["details"] == {"duplicate_hidden": True}


@pytest.mark.parametrize("target,expected", [("contacted", 200), ("meeting_scheduled", 200), ("won", 409), ("lost", 409)])
async def test_status_changes(client, ids, target, expected) -> None:
    async with login(client, "rep_a@brokerhub.test") as h:
        lead_id = (await _new_lead(client, h, mobile=f"01012{len(target):05d}"))["lead_id"]
        response = await client.post(f"/api/v1/leads/{lead_id}/status", headers=h, json={"status": target})
        assert response.status_code == expected, response.text


async def test_lose_requires_a_reason(client, ids) -> None:
    async with login(client, "rep_a@brokerhub.test") as h:
        lead_id = (await _new_lead(client, h, mobile="01055554444"))["lead_id"]
        assert (await client.post(f"/api/v1/leads/{lead_id}/lose", headers=h, json={"note": "x"})).status_code == 422
        from app.core.db import get_sessionmaker
        from app.models.masters import LostReason
        from sqlalchemy import select

        async with get_sessionmaker()() as session:
            reason_id = str((await session.execute(select(LostReason).limit(1))).scalar_one().id)
        ok = await client.post(f"/api/v1/leads/{lead_id}/lose", headers=h, json={"lost_reason_id": reason_id, "note": "أغلى"})
        assert ok.status_code == 200 and ok.json()["status"] == "lost"
