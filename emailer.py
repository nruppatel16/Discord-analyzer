"""
emailer.py — Sends the HTML report as an email body via Gmail SMTP.
Never crashes the pipeline; logs failures and continues.
"""

import logging
import os
import smtplib
from datetime import datetime, timezone
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

logger = logging.getLogger(__name__)

SMTP_HOST = "smtp.gmail.com"
SMTP_PORT = 587


def _get_edition(dt: datetime) -> str:
    h = dt.hour
    if 5 <= h < 12:
        return "Morning"
    elif 12 <= h < 17:
        return "Afternoon"
    elif 17 <= h < 22:
        return "Evening"
    else:
        return "Night"


def send_report(html: str, email_from: str, email_password: str, email_to: str) -> bool:
    """
    Send `html` as the body of an email.

    Returns True on success, False on failure.
    The caller should never crash on a False return — logging is handled here.
    """
    now = datetime.now(timezone.utc)
    edition = _get_edition(now)
    date_str = now.strftime("%b %-d, %Y")
    subject = f"Market Digest · {edition} · {date_str}"

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = email_from
    msg["To"] = email_to

    # Attach plain-text fallback then HTML
    plain = "Your email client does not support HTML. Please view the saved report at reports/latest.html"
    msg.attach(MIMEText(plain, "plain"))
    msg.attach(MIMEText(html, "html"))

    try:
        with smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=30) as server:
            server.ehlo()
            server.starttls()
            server.ehlo()
            server.login(email_from, email_password)
            server.sendmail(email_from, email_to, msg.as_string())

        logger.info("Report emailed to %s (subject: %s)", email_to, subject)
        return True

    except smtplib.SMTPAuthenticationError:
        logger.error(
            "Email authentication failed. "
            "Make sure EMAIL_PASSWORD is a Gmail App Password, not your login password. "
            "Enable 2FA and generate an app password at myaccount.google.com/apppasswords"
        )
        return False

    except smtplib.SMTPException as exc:
        logger.error("SMTP error sending email: %s", exc)
        return False

    except OSError as exc:
        logger.error("Network error sending email: %s", exc)
        return False
