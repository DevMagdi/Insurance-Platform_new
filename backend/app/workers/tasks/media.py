from __future__ import annotations

import contextlib

from app.workers._runtime import run_async
from app.workers.celery_app import celery_app


@celery_app.task(name="broker_hub.purge_expired_recordings")
def purge_expired_recordings() -> dict[str, int]:
    """Retention policy (spec §6): drop recordings older than RECORDING_RETENTION_DAYS."""

    async def body() -> dict[str, int]:
        from datetime import UTC, datetime, timedelta

        import sqlalchemy as sa

        from app.core.config import get_settings
        from app.core.db import get_sessionmaker
        from app.integrations.storage import storage
        from app.models.requests import CallRecord

        cutoff = datetime.now(UTC) - timedelta(days=get_settings().RECORDING_RETENTION_DAYS)
        async with get_sessionmaker()() as session:
            rows = (
                (
                    await session.execute(
                        sa.select(CallRecord).where(CallRecord.recording_object_key.is_not(None), CallRecord.started_at < cutoff)
                    )
                )
                .scalars()
                .all()
            )
            for row in rows:
                with contextlib.suppress(Exception):  # pragma: no cover - storage may be unreachable
                    storage().delete_object(str(row.recording_object_key))
                row.recording_object_key = None
            await session.commit()
            return {"purged": len(rows)}

    return run_async(body)()


@celery_app.task(name="broker_hub.cleanup_tmp_files")
def cleanup_tmp_files() -> dict[str, int]:
    async def body() -> dict[str, int]:
        import shutil
        from pathlib import Path

        from app.core.config import get_settings

        tmp = Path(get_settings().STORAGE_DIR) / "tmp"
        removed = 0
        if tmp.exists():
            shutil.rmtree(tmp, ignore_errors=True)
            removed = 1
        return {"removed": removed}

    return run_async(body)()
