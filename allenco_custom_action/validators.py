"""Shared validation helpers for API routers.

Centralised here so that all three routers use the same identifier regex and
value coercion logic. Updating one definition is enough — no risk of the
copies drifting and introducing a silent injection gap.
"""

import datetime
import decimal
import re
from typing import Any

# Allows only alphanumeric characters and underscores.
# Used to validate every user-supplied SQL identifier (view names, column names)
# before interpolating them into query strings.
SAFE_IDENTIFIER = re.compile(r"^[a-zA-Z0-9_]+$")


def _coerce(value: Any) -> Any:
    """Convert pyodbc-returned values to JSON-serializable Python types."""
    if value is None:
        return None
    if isinstance(value, bytes):
        # Binary columns or varchar with non-UTF-8 encoding
        return value.decode("utf-8", errors="replace")
    if isinstance(value, (datetime.datetime, datetime.date, datetime.time)):
        return value.isoformat()
    if isinstance(value, decimal.Decimal):
        return float(value)
    return value
