"""Cloud-PBX / SIP event driver + simulated driver."""

from __future__ import annotations

import httpx

from app.core.config import get_settings
from app.core.security import verify_webhook_signature


class TelephonySim:
    name = "sim"

    def verify_signature(self, payload: bytes, signature_header: str | None) -> bool:
        return True

    async def fetch_recording(self, url: str) -> bytes:
        # 44-byte WAV header + silence: a real, playable file the <audio> element accepts.
        from app.core.storage_bytes import silence_wav

        _ = url
        return silence_wav(seconds=2)


class TelephonyGeneric:
    """HTTP-callback style central: `X-Call-Signature: sha256=<hmac>` over the raw body."""

    name = "generic"

    def verify_signature(self, payload: bytes, signature_header: str | None) -> bool:
        return verify_webhook_signature(payload, signature_header, get_settings().TELEPHONY_WEBHOOK_SECRET)

    async def fetch_recording(self, url: str) -> bytes:
        async with httpx.AsyncClient(timeout=60) as client:
            response = await client.get(url)
            response.raise_for_status()
            return response.content
