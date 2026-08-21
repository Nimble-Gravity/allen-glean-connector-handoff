"""Shared validation helpers for API routers.

Centralised here so that all three routers use the same identifier regex and
value coercion logic. Updating one definition is enough — no risk of the
copies drifting and introducing a silent injection gap.

The filter helpers (FILTER_OPS / parse_filters / build_where) extend /query and
/aggregate with multi-condition WHERE clauses while preserving the two-layer
SQL-injection defence: identifiers are validated against SAFE_IDENTIFIER and
bracket-quoted, operators are looked up by key in an allow-list (the SQL text
never comes from the request), and every value is bound as a `?` parameter.
"""

import datetime
import decimal
import json
import re
from dataclasses import dataclass
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


# ---------------------------------------------------------------------------
# Filter operators (allow-list) — used by /query and /aggregate
# ---------------------------------------------------------------------------

# The KEY is what the request supplies; the SQL fragment is built from the code's
# maps below — the operator text is NEVER taken from user input. The value maps an
# op to its "value arity", which governs how many bound params it consumes:
#   "one"  → a single scalar bound as one ?          (eq/ne/gt/gte/lt/lte)
#   "two"  → a 2-element list bound as two ?          (between)
#   "many" → a non-empty list, one ? per element      (in)
#   "none" → no value, no bind                         (is_null/is_not_null)
#   "text" → a single string wrapped with wildcards    (contains/startswith/endswith)
FILTER_OPS: dict[str, str] = {
    "eq": "one",
    "ne": "one",
    "gt": "one",
    "gte": "one",
    "lt": "one",
    "lte": "one",
    "between": "two",
    "in": "many",
    "is_null": "none",
    "is_not_null": "none",
    "contains": "text",
    "startswith": "text",
    "endswith": "text",
}

# op → SQL comparator (scalar ops only). Kept separate from FILTER_OPS so the
# comparator string is a code constant, never a request value.
_SQL_COMPARATORS: dict[str, str] = {
    "eq": "=",
    "ne": "<>",
    "gt": ">",
    "gte": ">=",
    "lt": "<",
    "lte": "<=",
}

# Escape character used in LIKE predicates so a user-supplied % or _ is treated
# literally (see escape_like). A single backslash.
LIKE_ESCAPE_CHAR = "\\"


@dataclass(frozen=True)
class Filter:
    """A single validated WHERE condition: [column] <op> value."""

    column: str
    op: str
    value: Any = None


def escape_like(value: str) -> str:
    """Neutralise LIKE metacharacters in user input; pair with ``ESCAPE '\\'``.

    The user's own %, _, [ become literals; only the wildcards the code wraps
    around the value stay active. The value is still passed as a bound `?`, so
    this guards wildcard semantics, not injection (injection is already
    impossible because the value is parameterised).
    """
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_").replace("[", "\\[")


def _validate_value_arity(index: int, op: str, arity: str, value: Any) -> None:
    if arity == "none":
        return  # value ignored (is_null / is_not_null)
    if arity == "one":
        if value is None or isinstance(value, (list, dict)):
            raise ValueError(f"filters[{index}].op '{op}' requires a single scalar value.")
        return
    if arity == "text":
        if not isinstance(value, str):
            raise ValueError(f"filters[{index}].op '{op}' requires a string value.")
        return
    if arity == "two":
        if not (isinstance(value, list) and len(value) == 2):
            raise ValueError(
                f"filters[{index}].op 'between' requires a list of exactly two values [low, high]."
            )
        return
    if arity == "many":
        if not (isinstance(value, list) and len(value) >= 1):
            raise ValueError(f"filters[{index}].op 'in' requires a non-empty list of values.")
        return


def parse_filters(raw: str | None) -> list[Filter]:
    """Parse the ``filters`` query param (a JSON array) into validated Filters.

    Shape: ``[{"column": "...", "op": "...", "value": ...}, ...]`` — combined with
    AND. Raises ``ValueError`` (routers map it to HTTP 400) on malformed JSON, an
    unknown op, an unsafe column, or a value whose shape does not match the op.
    Returns ``[]`` for an absent/empty param.
    """
    if raw is None or raw.strip() == "":
        return []
    try:
        data = json.loads(raw)
    except (json.JSONDecodeError, TypeError) as exc:
        raise ValueError("filters must be a valid JSON array of filter objects.") from exc
    if not isinstance(data, list):
        raise ValueError("filters must be a JSON array of filter objects.")

    filters: list[Filter] = []
    for i, item in enumerate(data):
        if not isinstance(item, dict):
            raise ValueError(f"filters[{i}] must be an object with 'column' and 'op'.")
        column = item.get("column")
        op = item.get("op")
        value = item.get("value")
        if not isinstance(column, str) or not SAFE_IDENTIFIER.match(column):
            raise ValueError(
                f"filters[{i}].column must contain only letters, digits, and underscores."
            )
        if not isinstance(op, str) or op not in FILTER_OPS:
            raise ValueError(f"filters[{i}].op must be one of: {', '.join(sorted(FILTER_OPS))}.")
        _validate_value_arity(i, op, FILTER_OPS[op], value)
        filters.append(Filter(column=column, op=op, value=value))
    return filters


def build_where(filters: list[Filter], params: list[Any]) -> list[str]:
    """Return SQL predicate strings for ``filters``, appending binds to ``params``.

    Each column is bracket-quoted; each operator's SQL comes from the code's maps,
    never from the request; every value (including BETWEEN bounds, IN elements and
    the wildcard-wrapped LIKE argument) is appended to ``params`` as a bound `?`,
    in the same order the predicates are emitted.
    """
    predicates: list[str] = []
    for f in filters:
        col = f"[{f.column}]"
        op = f.op
        if op in _SQL_COMPARATORS:
            predicates.append(f"{col} {_SQL_COMPARATORS[op]} ?")
            params.append(f.value)
        elif op == "between":
            predicates.append(f"{col} BETWEEN ? AND ?")
            params.append(f.value[0])
            params.append(f.value[1])
        elif op == "in":
            placeholders = ", ".join("?" for _ in f.value)
            predicates.append(f"{col} IN ({placeholders})")
            params.extend(f.value)
        elif op == "is_null":
            predicates.append(f"{col} IS NULL")
        elif op == "is_not_null":
            predicates.append(f"{col} IS NOT NULL")
        elif op == "contains":
            predicates.append(f"{col} LIKE ? ESCAPE '{LIKE_ESCAPE_CHAR}'")
            params.append(f"%{escape_like(f.value)}%")
        elif op == "startswith":
            predicates.append(f"{col} LIKE ? ESCAPE '{LIKE_ESCAPE_CHAR}'")
            params.append(f"{escape_like(f.value)}%")
        elif op == "endswith":
            predicates.append(f"{col} LIKE ? ESCAPE '{LIKE_ESCAPE_CHAR}'")
            params.append(f"%{escape_like(f.value)}")
    return predicates
