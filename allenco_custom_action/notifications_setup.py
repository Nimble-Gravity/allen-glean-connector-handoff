"""Bridges the shared notifications package into the Custom Action API.

The notifications package lives under ``src/`` and is pure stdlib (no Glean SDK,
no project imports), so the API can reuse it directly. This module makes it
importable regardless of the working directory the API is launched from, and
exposes a small helper to build the API's notifier.
"""

import logging
import sys
import traceback
from pathlib import Path

logger = logging.getLogger(__name__)

# Ensure the repo's src/ is importable (the API is launched from
# smart_custom_action/, so src/ is not on sys.path unless installed).
_SRC = Path(__file__).resolve().parent.parent / "src"
if _SRC.is_dir() and str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from notifications.config import DEFAULT_CONNECTOR_NAME, NotificationSettings  # noqa: E402
from notifications.events import ErrorEvent, ErrorType  # noqa: E402
from notifications.factory import build_notifier  # noqa: E402
from notifications.resolutions import resolution_for  # noqa: E402
from notifications.senders.base import Notifier  # noqa: E402

__all__ = [
    "ErrorEvent",
    "ErrorType",
    "NotificationSettings",
    "Notifier",
    "build_notifier",
    "resolution_for",
    "build_api_notifier",
    "notify",
]

DEFAULT_API_CONNECTOR_NAME = "Allen & Co Custom Action API"


def build_api_notifier() -> Notifier:
    """Build the API's notifier from environment.

    Defaults the connector name to the API's name when one isn't set explicitly,
    so alerts are distinguishable from the indexer's.
    """
    settings = NotificationSettings.from_env()
    if settings.connector_name == DEFAULT_CONNECTOR_NAME:
        # The shared default — override so API alerts are labelled correctly.
        from dataclasses import replace

        settings = replace(settings, connector_name=DEFAULT_API_CONNECTOR_NAME)
    return build_notifier(settings)


def notify(
    notifier: Notifier,
    error_type: ErrorType,
    message: str,
    *,
    connector_name: str = DEFAULT_API_CONNECTOR_NAME,
    detail: str | None = None,
) -> None:
    """Send an error notification. Never raises (CompositeNotifier swallows)."""
    notifier.send(
        ErrorEvent(
            connector_name=connector_name,
            error_type=error_type,
            message=message,
            recommended_resolution=resolution_for(error_type),
            detail=detail,
        )
    )


def notify_db_error(notifier: Notifier, endpoint: str, exc: Exception) -> None:
    """Report a SQL Server failure encountered while serving an API request."""
    notify(
        notifier,
        ErrorType.API_REQUEST,
        f"{endpoint} failed: {exc}",
        detail=traceback.format_exc(),
    )
