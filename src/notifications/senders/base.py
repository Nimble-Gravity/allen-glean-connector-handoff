"""Notifier interface implemented by each delivery channel."""

from abc import ABC, abstractmethod

from notifications.events import ErrorEvent


class Notifier(ABC):
    """A single delivery channel for ErrorEvents.

    Concrete senders RAISE on transport failure. Failure isolation across
    multiple channels is the CompositeNotifier's responsibility, not the
    individual sender's.
    """

    #: Human-readable channel name, used in failure logs.
    name: str = "notifier"

    @abstractmethod
    def send(self, event: ErrorEvent) -> None:
        """Deliver the event over this channel, or raise on failure."""
        raise NotImplementedError
