"""Secrets must never reach a log line (item 1): httpx prints full URLs at INFO, and
`debug_token` carries both the user token and the App Secret as query params (Meta's contract
only accepts them there), so the logging pipeline itself has to mask them."""

from __future__ import annotations

import logging

from app.core.logging import RedactSecrets, setup_logging

USER_TOKEN = "EAAG-user-token-123"
APP_SECRET = "app-secret-xyz"


def test_redaction_processor_masks_url_params_and_bearer() -> None:
    url = f"https://graph.facebook.com/v25.0/debug_token?input_token={USER_TOKEN}&access_token=1031129959988895|{APP_SECRET}&other=visible"
    out = RedactSecrets()(None, "info", {"event": "probe", "url": url, "auth": f"Bearer {USER_TOKEN}", "plain": "عدد الطلبات 5"})
    assert USER_TOKEN not in out["url"]
    assert APP_SECRET not in out["url"]
    assert "other=visible" in out["url"]
    assert USER_TOKEN not in out["auth"]
    assert out["auth"] == "Bearer •••"
    assert out["plain"] == "عدد الطلبات 5"


def test_http_libraries_are_pinned_to_warning() -> None:
    setup_logging(json_logs=True)
    assert logging.getLogger("httpx").level == logging.WARNING
    assert logging.getLogger("httpcore").level == logging.WARNING
