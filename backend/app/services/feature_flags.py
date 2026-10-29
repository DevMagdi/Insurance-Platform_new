"""Feature flags live in the database, not in environment variables (ADR-008).

ADR-034: shipped modules are never flag-gated — RBAC is the only gate. The one remaining
flag is `ai.enabled`, an external-provider switch: it hides no screen, it only refuses the
summarise/transcribe actions themselves while the provider is off.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

AI_FLAG = "ai.enabled"


async def flag_enabled(session: AsyncSession, key: str) -> bool:
    from app.models.masters import FeatureFlag

    row = (await session.execute(select(FeatureFlag).where(FeatureFlag.key == key))).scalar_one_or_none()
    return bool(row and row.enabled)


async def ai_enabled(session: AsyncSession) -> bool:
    """Transcription/summarisation must be switchable mid-day without a deploy (ADR-012)."""
    return await flag_enabled(session, AI_FLAG)
