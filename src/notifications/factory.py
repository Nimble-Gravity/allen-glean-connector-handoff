"""Build the active notifier from NotificationSettings.

A misconfigured-but-enabled channel is warned-and-skipped: a notification-config
mistake must never block the actual sync. Channels compose — email and Slack can
run together, either alone, or neither (NullNotifier).
"""

import logging

from notifications.composite import CompositeNotifier, NullNotifier
from notifications.config import NotificationSettings
from notifications.senders.base import Notifier
from notifications.senders.email import EmailNotifier
from notifications.senders.slack import SlackNotifier

logger = logging.getLogger(__name__)


def build_notifier(settings: NotificationSettings) -> Notifier:
    """Return a composite of the configured channels, or a no-op when none apply."""
    if not settings.enabled:
        return NullNotifier()

    senders: list[Notifier] = []

    if settings.smtp_host and settings.email_from and settings.email_to:
        senders.append(
            EmailNotifier(
                host=settings.smtp_host,
                port=settings.smtp_port,
                sender=settings.email_from,
                recipients=settings.email_to,
                username=settings.smtp_user,
                password=settings.smtp_password,
                use_tls=settings.smtp_use_tls,
            )
        )
    elif settings.smtp_host or settings.email_from or settings.email_to:
        logger.warning(
            "Email notifications partially configured (need SMTP_HOST + "
            "NOTIFY_EMAIL_FROM + NOTIFY_EMAIL_TO); skipping the email channel."
        )

    if settings.slack_webhook_url:
        senders.append(SlackNotifier(webhook_url=settings.slack_webhook_url))

    if not senders:
        logger.warning(
            "Notifications enabled but no channel is fully configured "
            "(set SMTP_* and/or SLACK_WEBHOOK_URL); notifications disabled."
        )
        return NullNotifier()

    return CompositeNotifier(senders)
