"""Environment-backed settings for error notifications.

Follows the ConnectorSettings pattern in config/config.py: a frozen dataclass
loaded from the process environment via from_env() after load_dotenv().

This package is intentionally standalone (pure stdlib, no project imports) so it
can be shared by both the indexer (src/) and the API (allenco_custom_action/).
"""

import os
from dataclasses import dataclass

DEFAULT_CONNECTOR_NAME = "Allen & Co Glean Connector"


@dataclass(frozen=True)
class NotificationSettings:
    """Settings controlling how connector errors are reported (email and/or Slack)."""

    enabled: bool
    connector_name: str

    # SMTP email
    smtp_host: str
    smtp_port: int
    smtp_user: str
    smtp_password: str
    smtp_use_tls: bool
    email_from: str
    email_to: tuple[str, ...]

    # Slack incoming webhook (Allen & Co's preferred channel). Empty = disabled.
    slack_webhook_url: str

    @staticmethod
    def from_env() -> "NotificationSettings":
        """Read notification settings from the current process environment."""
        return NotificationSettings(
            enabled=_read_bool_env("NOTIFICATIONS_ENABLED", default=False),
            connector_name=_read_str_env(
                "NOTIFICATIONS_CONNECTOR_NAME", default=DEFAULT_CONNECTOR_NAME
            ),
            smtp_host=_read_str_env("SMTP_HOST"),
            smtp_port=int(_read_str_env("SMTP_PORT", default="587") or "587"),
            smtp_user=_read_str_env("SMTP_USER"),
            smtp_password=_read_str_env("SMTP_PASSWORD"),
            smtp_use_tls=_read_bool_env("SMTP_USE_TLS", default=True),
            email_from=_read_str_env("NOTIFY_EMAIL_FROM"),
            email_to=_parse_recipients(_read_str_env("NOTIFY_EMAIL_TO")),
            slack_webhook_url=_read_str_env("SLACK_WEBHOOK_URL"),
        )


def _parse_recipients(raw: str) -> tuple[str, ...]:
    """Split a comma-separated recipient list into a tuple, dropping blanks."""
    return tuple(addr.strip() for addr in raw.split(",") if addr.strip())


def _read_bool_env(key: str, *, default: bool) -> bool:
    raw = (os.environ.get(key) or "").strip().lower()
    if raw in ("1", "true", "yes"):
        return True
    if raw in ("0", "false", "no"):
        return False
    return default


def _read_str_env(key: str, *, default: str = "") -> str:
    return (os.environ.get(key) or default).strip()
