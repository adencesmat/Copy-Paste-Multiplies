"""Optional email digest. Credentials come only from the environment."""

from __future__ import annotations

import logging
import os
import smtplib
from email.message import EmailMessage
from typing import Sequence

from .config import Config
from .models import Lead
from .report import render_html

log = logging.getLogger(__name__)


def maybe_email(config: Config, leads: Sequence[Lead]) -> bool:
    """Send the digest if email is enabled and SMTP creds are present.

    Returns True if an email was sent. Missing credentials are a no-op (not an
    error) so the pipeline still produces files in environments without SMTP.
    """
    cfg = config.get("email", {})
    if not cfg.get("enabled"):
        return False

    host = os.environ.get("SMTP_HOST")
    port = int(os.environ.get("SMTP_PORT", "587"))
    user = os.environ.get("SMTP_USER")
    password = os.environ.get("SMTP_PASSWORD")
    if not host:
        log.warning("email.enabled but SMTP_HOST not set; skipping email")
        return False

    msg = EmailMessage()
    prefix = cfg.get("subject_prefix", "[Castle Rock Leads]")
    from datetime import date

    msg["Subject"] = f"{prefix} {len(leads)} new lead(s) — {date.today()}"
    msg["From"] = cfg.get("from_addr", user or "leads@example.com")
    msg["To"] = ", ".join(cfg.get("to_addrs", []))
    msg.set_content("This digest requires an HTML-capable mail client.")
    msg.add_alternative(render_html(leads), subtype="html")

    with smtplib.SMTP(host, port) as server:
        server.starttls()
        if user and password:
            server.login(user, password)
        server.send_message(msg)
    log.info("Emailed digest to %s", msg["To"])
    return True
