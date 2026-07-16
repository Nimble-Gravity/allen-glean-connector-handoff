"""Tests for the notifications factory (email + Slack composition)."""

from notifications.composite import CompositeNotifier, NullNotifier
from notifications.config import NotificationSettings
from notifications.events import ErrorEvent, ErrorType
from notifications.factory import build_notifier
from notifications.resolutions import resolution_for
from notifications.senders.slack import _format_message


def _settings(**overrides) -> NotificationSettings:
    base = dict(
        enabled=True,
        connector_name="Allen & Co Glean Connector",
        smtp_host="",
        smtp_port=587,
        smtp_user="",
        smtp_password="",
        smtp_use_tls=True,
        email_from="",
        email_to=(),
        slack_webhook_url="",
    )
    base.update(overrides)
    return NotificationSettings(**base)


def test_disabled_returns_null():
    assert isinstance(build_notifier(_settings(enabled=False)), NullNotifier)


def test_no_channel_configured_returns_null():
    assert isinstance(build_notifier(_settings()), NullNotifier)


def test_slack_only_builds_composite():
    notifier = build_notifier(_settings(slack_webhook_url="https://hooks.slack.com/x"))
    assert isinstance(notifier, CompositeNotifier)


def test_email_only_builds_composite():
    notifier = build_notifier(
        _settings(
            smtp_host="smtp.local", email_from="a@allenandco.com", email_to=("b@allenandco.com",)
        )
    )
    assert isinstance(notifier, CompositeNotifier)


def test_both_channels_build_composite():
    notifier = build_notifier(
        _settings(
            smtp_host="smtp.local",
            email_from="a@allenandco.com",
            email_to=("b@allenandco.com",),
            slack_webhook_url="https://hooks.slack.com/x",
        )
    )
    assert isinstance(notifier, CompositeNotifier)


def test_slack_message_contains_event_fields():
    event = ErrorEvent(
        connector_name="Allen & Co Glean Connector",
        error_type=ErrorType.DB_CONNECTION,
        message="connection refused",
        recommended_resolution=resolution_for(ErrorType.DB_CONNECTION),
    )
    msg = _format_message(event)
    assert "db_connection" in msg
    assert "connection refused" in msg
