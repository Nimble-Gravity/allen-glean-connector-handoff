"""Slack incoming-webhook sender (stdlib only).

Allen & Co's preferred alert channel. Posts a compact message to a Slack incoming
webhook. Like every Notifier, it RAISES on transport failure — the
CompositeNotifier is the layer that isolates a failing channel.

TODO Allen & Co: a Site24x7 sender can be added the same way (new senders/site24x7.py
+ a config check in factory.build_notifier).
"""

import json
import logging
import urllib.error
import urllib.request

from notifications.events import ErrorEvent
from notifications.senders.base import Notifier

logger = logging.getLogger(__name__)


class SlackNotifier(Notifier):
    """Send an ErrorEvent to a Slack incoming webhook as a formatted message."""

    name = "slack"

    def __init__(self, *, webhook_url: str, timeout: int = 15) -> None:
        self._webhook_url = webhook_url
        self._timeout = timeout

    def send(self, event: ErrorEvent) -> None:
        payload = {"text": _format_message(event)}
        data = json.dumps(payload).encode("utf-8")
        request = urllib.request.Request(
            self._webhook_url,
            data=data,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=self._timeout) as response:
                status = response.status
        except urllib.error.URLError as exc:
            raise RuntimeError(f"Slack webhook request failed: {exc}") from exc

        if status != 200:
            raise RuntimeError(f"Slack webhook returned HTTP {status}.")
        logger.info("Sent error notification to Slack.")


def _format_message(event: ErrorEvent) -> str:
    """Render an ErrorEvent as a Slack mrkdwn message."""
    lines = [
        f":rotating_light: *{event.subject()}*",
        f"*Error type:* {event.error_type.value}",
        f"*Message:* {event.message}",
        f"*Recommended resolution:* {event.recommended_resolution}",
    ]
    if event.run_id:
        lines.append(f"*Run ID:* {event.run_id}")
    return "\n".join(lines)
