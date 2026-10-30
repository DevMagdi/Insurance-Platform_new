"""REGRESSION (WhatsApp debugging round, item 6): `Client.account_owner` must never joined-load.

The SAWarning "Multiple rows returned with uselist=False for eagerly-loaded attribute
'Client.account_owner'" comes from a joined many-to-one eager load riding on statements that
join collections (contacts, policies, the `requests` backref): the row set multiplies and the
uselist=False loader cannot reconcile it. The relationship now loads with `selectin` — one
batched query, no row multiplication — and these tests pin both the strategy and the behaviour
on exactly the row-multiplying shapes that used to warn.
"""

from __future__ import annotations

import warnings

import pytest
from app.core.db import get_sessionmaker
from app.models.clients import Client, ClientContact
from app.models.phase2 import Policy
from sqlalchemy import select
from sqlalchemy.exc import SAWarning


def test_account_owner_is_not_joined_loaded() -> None:
    assert Client.account_owner.property.lazy == "selectin"


@pytest.mark.asyncio
async def test_owner_loads_cleanly_on_row_multiplying_queries(client) -> None:
    async with get_sessionmaker()() as session:
        owner_client = (await session.execute(select(Client).limit(1))).scalars().first()
        assert owner_client is not None and owner_client.account_owner_id is not None
        session.add_all(
            [
                ClientContact(client_id=owner_client.id, name="جهة أ", mobile="0101", is_primary=True),
                ClientContact(client_id=owner_client.id, name="جهة ب", mobile="0102", is_primary=False),
                Policy(client_id=owner_client.id, policy_no="P-OWN-1"),
                Policy(client_id=owner_client.id, policy_no="P-OWN-2"),
            ]
        )
        await session.commit()
        client_id = owner_client.id

    async with get_sessionmaker()() as session:
        with warnings.catch_warnings():
            warnings.simplefilter("error", SAWarning)
            # a statement that joins a collection (rows multiply per contact)
            joined = (await session.execute(select(Client).join(Client.contacts).where(Client.id == client_id))).scalars().unique().all()
            assert len(joined) == 1
            assert joined[0].account_owner is not None
            assert joined[0].account_owner.id == joined[0].account_owner_id
            # the policies path: the same client arrives once per policy row
            policies = (await session.execute(select(Policy).where(Policy.client_id == client_id))).scalars().all()
            assert len(policies) == 2
            assert all(p.client is not None and p.client.account_owner is not None for p in policies)
