from __future__ import annotations

import logging
import re
import smtplib
import ssl
from email.message import EmailMessage
from email.utils import make_msgid

from sql_assistant import AssistantError, read_config


LOGGER = logging.getLogger(__name__)


class DeliveryUncertain(AssistantError):
    pass


def _gmail_credentials() -> tuple[str, str]:
    config = read_config()
    username = config.get("SMTP_USERNAME", "").strip() or config.get("GMAIL_USERNAME", "").strip()
    password = config.get("SMTP_APP_PASSWORD", "").replace(" ", "") or config.get("GMAIL_APP_PASSWORD", "").replace(" ", "")
    return username, password


def email_ready() -> bool:
    username, password = _gmail_credentials()
    return bool(username and password)


def send_report(title: str, pdf: bytes) -> None:
    username, password = _gmail_credentials()
    if not re.fullmatch(r"[A-Za-z0-9.!#$%&'*+/=?^_`{|}~-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}", username) or not password:
        raise AssistantError("Gmail delivery is not configured. The owner must update the email settings.")
    message = EmailMessage()
    message["From"] = username
    message["To"] = username
    message["Subject"] = "Business report: " + title.replace("\r", " ").replace("\n", " ")[:140]
    message["Message-ID"] = make_msgid()
    message.set_content("Your reviewed business report is attached as a PDF.")
    message.add_attachment(pdf, maintype="application", subtype="pdf", filename="business-report.pdf")
    client = smtplib.SMTP(timeout=20)
    try:
        client.connect("smtp.gmail.com", 587)
        client.ehlo()
        client.starttls(context=ssl.create_default_context())
        client.ehlo()
        client.login(username, password)
        try:
            refused = client.send_message(message)
        except (smtplib.SMTPServerDisconnected, OSError) as error:
            LOGGER.error("Email delivery acknowledgement failed (%s)", type(error).__name__)
            raise DeliveryUncertain("Delivery could not be confirmed. Check Gmail before attempting another send.") from error
        if refused:
            raise smtplib.SMTPRecipientsRefused(refused)
    except DeliveryUncertain:
        raise
    except smtplib.SMTPAuthenticationError as error:
        LOGGER.error("Gmail authentication rejected")
        raise AssistantError("Gmail rejected the login. Use a Gmail app password, not your normal password.") from error
    except (smtplib.SMTPException, OSError) as error:
        LOGGER.error("Gmail request failed (%s)", type(error).__name__)
        raise AssistantError("Gmail could not accept the report. Check the email connection and try again.") from error
    finally:
        client.close()
