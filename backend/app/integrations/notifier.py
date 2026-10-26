"""Email via SMTP/Mailpit + in-app notifications (spec §8)."""

from __future__ import annotations

import smtplib
from email.message import EmailMessage

from app.core.config import get_settings
from app.core.logging import get_logger

log = get_logger("notifier")


class SmtpNotifier:
    async def send_email(self, *, to: str, subject: str, body: str) -> bool:
        settings = get_settings()
        message = EmailMessage()
        message["From"] = settings.EMAIL_FROM
        message["To"] = to
        message["Subject"] = subject
        message.set_content(body)
        host = settings.SMTP_URL.replace("smtp://", "").split(":")[0] or "localhost"
        port = int(settings.SMTP_URL.rsplit(":", 1)[-1] or 1025)
        try:
            with smtplib.SMTP(host, port, timeout=10) as client:
                client.send_message(message)
            return True
        except Exception as exc:  # pragma: no cover - no SMTP in unit tests
            log.warning("email_failed", to=to, error=str(exc)[:200])
            return False


class ConsoleNotifier:
    async def send_email(self, *, to: str, subject: str, body: str) -> bool:
        log.info("email_console", to=to, subject=subject, chars=len(body))
        return True


def email_notifier() -> ConsoleNotifier | SmtpNotifier:
    settings = get_settings()
    if settings.ENV == "dev" and not settings.SMTP_URL:
        return ConsoleNotifier()
    return SmtpNotifier()
