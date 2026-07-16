"""Fan-out and no-op notifiers.

CompositeNotifier is the single never-raising layer: a notification failure can
never crash the connector run or flip its return code. NullNotifier is used when
notifications are disabled or no channel is configured.
"""

import logging
from collections.abc import Sequence

from notifications.events import ErrorEvent
from notifications.senders.base import Notifier

logger = logging.getLogger(__name__)


class CompositeNotifier(Notifier):
    """Dispatch an event to each child notifier, isolating per-channel failures."""

    name = "composite"

    def __init__(self, notifiers: Sequence[Notifier]) -> None:
        self._notifiers = list(notifiers)

    def send(self, event: ErrorEvent) -> None:
        for notifier in self._notifiers:
            try:
                notifier.send(event)
            except Exception:
                logger.exception("Notifier %s failed to deliver", notifier.name)
        # Intentionally never raises.


class NullNotifier(Notifier):
    """No-op notifier used when notifications are disabled."""

    name = "null"

    def send(self, event: ErrorEvent) -> None:
        logger.debug(
            "Notifications disabled; dropping %s event for %s.",
            event.error_type.value,
            event.connector_name,
        )
