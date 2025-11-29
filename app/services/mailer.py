from __future__ import annotations

import logging
import smtplib
from email.message import EmailMessage
from email.utils import formataddr

from ..config import get_settings

logger = logging.getLogger(__name__)


def _send_email(recipient: str, subject: str, body: str) -> None:
    settings = get_settings()
    if not settings.smtp_host or not settings.smtp_from:
        logger.warning("SMTP not configured; printing email to log.")
        logger.info("Email to %s | %s\n%s", recipient, subject, body)
        return

    message = EmailMessage()
    message["Subject"] = subject
    message["From"] = formataddr(
        (settings.smtp_from_name or settings.app_name, settings.smtp_from)
    )
    message["To"] = recipient
    message.set_content(body)

    try:
        smtp_class = smtplib.SMTP_SSL if settings.smtp_use_ssl else smtplib.SMTP
        with smtp_class(settings.smtp_host, settings.smtp_port, timeout=15) as smtp:
            if settings.smtp_use_tls and not settings.smtp_use_ssl:
                smtp.starttls()
            if settings.smtp_username:
                smtp.login(settings.smtp_username, settings.smtp_password or "")
            smtp.send_message(message)
    except Exception as exc:  # pragma: no cover - network failures
        logger.error("Failed to send email to %s: %s", recipient, exc)
        raise


def send_invitation_email(recipient: str, login_url: str, temp_password: str) -> None:
    settings = get_settings()
    subject = f"{settings.app_name} invitation"
    body = (
        f"You've been invited to {settings.app_name}.\n\n"
        f"Login link: {login_url}\n"
        f"Username: {recipient}\n"
        f"Temporary password: {temp_password}\n\n"
        "You'll be asked to set your own password after signing in."
    )
    _send_email(recipient, subject, body)


def send_password_reset_email(recipient: str, login_url: str, temp_password: str) -> None:
    settings = get_settings()
    subject = f"{settings.app_name} password reset"
    body = (
        f"An administrator reset your access to {settings.app_name}.\n\n"
        f"Login link: {login_url}\n"
        f"Username: {recipient}\n"
        f"Temporary password: {temp_password}\n\n"
        "You'll be prompted to create a new password after logging in."
    )
    _send_email(recipient, subject, body)
