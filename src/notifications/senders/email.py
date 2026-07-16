"""Direct SMTP email sender (stdlib only)."""

import logging
import smtplib
import ssl
from email.message import EmailMessage

from notifications.events import ErrorEvent
from notifications.senders.base import Notifier

logger = logging.getLogger(__name__)


class EmailNotifier(Notifier):
    """Send an ErrorEvent as a multipart (text + HTML) email over SMTP."""

    name = "email"

    def __init__(
        self,
        *,
        host: str,
        port: int,
        sender: str,
        recipients: tuple[str, ...],
        username: str = "",
        password: str = "",
        use_tls: bool = True,
        timeout: int = 30,
    ) -> None:
        self._host = host
        self._port = port
        self._sender = sender
        self._recipients = recipients
        self._username = username
        self._password = password
        self._use_tls = use_tls
        self._timeout = timeout

    def send(self, event: ErrorEvent) -> None:
        msg = EmailMessage()
        msg["Subject"] = event.subject()
        msg["From"] = self._sender
        msg["To"] = ", ".join(self._recipients)
        msg.set_content(event.as_text())
        msg.add_alternative(event.as_html(), subtype="html")

        with smtplib.SMTP(self._host, self._port, timeout=self._timeout) as smtp:
            if self._use_tls:
                smtp.starttls(context=ssl.create_default_context())
            if self._username:
                smtp.login(self._username, self._password)
            smtp.send_message(msg)

        logger.info("Sent error notification email to %s", msg["To"])
