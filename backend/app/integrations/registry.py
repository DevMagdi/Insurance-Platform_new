"""Driver selection: `sim` (default, local/E2E) or `live` (env-configured providers)."""

from __future__ import annotations

import os
from typing import Any

from app.core.config import get_settings
from app.integrations.telephony import TelephonyGeneric, TelephonySim
from app.integrations.whatsapp import WhatsAppMeta, WhatsAppSim

_whatsapp: Any | None = None
_telephony: Any | None = None


def _driver() -> str:
    return get_settings().INTEGRATIONS_DRIVER


def whatsapp_provider() -> Any:
    global _whatsapp
    if _whatsapp is None:
        if _driver() == "live" and os.environ.get("WHATSAPP_TOKEN"):
            _whatsapp = WhatsAppMeta(token=os.environ["WHATSAPP_TOKEN"], phone_number_id=os.environ.get("WHATSAPP_PHONE_ID", ""))
        else:
            _whatsapp = WhatsAppSim()
    return _whatsapp


def telephony_provider() -> Any:
    global _telephony
    if _telephony is None:
        _telephony = TelephonyGeneric() if _driver() == "live" else TelephonySim()
    return _telephony


def reset_providers() -> None:
    global _whatsapp, _telephony
    _whatsapp = _telephony = None
