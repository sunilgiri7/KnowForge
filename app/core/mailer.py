from __future__ import annotations

import logging
import smtplib
from email.message import EmailMessage

from app.core.config import settings

logger = logging.getLogger("knowforge.mailer")


def send_verification_email(email: str, code: str) -> None:
    subject = "Verify your KnowForge account"
    body = (
        "Welcome to KnowForge.\n\n"
        f"Your verification code is: {code}\n\n"
        f"This code expires in {settings.verification_code_minutes} minutes."
    )
    if not settings.smtp_host:
        logger.warning("KnowForge verification code for %s: %s", email, code)
        return

    message = EmailMessage()
    message["From"] = settings.smtp_from_email
    message["To"] = email
    message["Subject"] = subject
    message.set_content(body)

    with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=15) as smtp:
        if settings.smtp_use_tls:
            smtp.starttls()
        if settings.smtp_user and settings.smtp_password:
            smtp.login(settings.smtp_user, settings.smtp_password)
        smtp.send_message(message)
