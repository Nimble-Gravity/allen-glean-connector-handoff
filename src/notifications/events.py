"""Structured error event sent to the operations team when the connector fails.

An ErrorEvent carries the four SOW-required fields — connector name, error type,
timestamp, and a recommended resolution step — plus the raw message and optional
detail. The event renders to a plaintext/HTML email body (and a Slack message).
"""

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum


class ErrorType(StrEnum):
    """Category of connector failure.

    StrEnum makes the value serialize cleanly to JSON and matches the
    string-discriminator style used elsewhere.
    """

    DB_CONNECTION = "db_connection"
    GLEAN_PREREQS = "glean_prereqs"
    USER_INDEXING = "user_indexing"
    DOCUMENT_INDEXING = "document_indexing"
    API_STARTUP = "api_startup"
    API_REQUEST = "api_request"
    UNEXPECTED = "unexpected"


@dataclass(frozen=True)
class ErrorEvent:
    """An actionable connector failure to report to the operations team."""

    connector_name: str
    error_type: ErrorType
    message: str
    recommended_resolution: str
    timestamp: datetime = field(default_factory=lambda: datetime.now(tz=UTC))
    run_id: str | None = None
    detail: str | None = None  # optional traceback / exception repr

    def _timestamp_iso(self) -> str:
        return self.timestamp.isoformat()

    def subject(self) -> str:
        """One-line subject used for the email."""
        return f"[{self.connector_name}] {self.error_type.value} failure"

    def as_text(self) -> str:
        """Plaintext email body containing all required fields."""
        lines = [
            f"Connector:   {self.connector_name}",
            f"Error type:  {self.error_type.value}",
            f"Timestamp:   {self._timestamp_iso()}",
            f"Message:     {self.message}",
            "",
            f"Recommended resolution:\n  {self.recommended_resolution}",
        ]
        if self.run_id:
            lines.append(f"\nRun ID: {self.run_id}")
        if self.detail:
            lines.append(f"\nDetail:\n{self.detail}")
        return "\n".join(lines)

    def as_html(self) -> str:
        """Simple HTML email body (alternative part)."""
        rows = [
            ("Connector", self.connector_name),
            ("Error type", self.error_type.value),
            ("Timestamp", self._timestamp_iso()),
            ("Message", self.message),
            ("Recommended resolution", self.recommended_resolution),
        ]
        if self.run_id:
            rows.append(("Run ID", self.run_id))
        table_rows = "".join(
            f"<tr><td style='padding:4px 12px 4px 0;font-weight:bold;"
            f"vertical-align:top'>{_escape(label)}</td>"
            f"<td style='padding:4px 0'>{_escape(value)}</td></tr>"
            for label, value in rows
        )
        detail_block = (
            f"<pre style='background:#f4f4f4;padding:8px;overflow:auto'>"
            f"{_escape(self.detail)}</pre>"
            if self.detail
            else ""
        )
        return (
            f"<h3>{_escape(self.subject())}</h3>"
            f"<table style='border-collapse:collapse'>{table_rows}</table>"
            f"{detail_block}"
        )


def _escape(value: str) -> str:
    """Minimal HTML escaping for the email body."""
    return value.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
