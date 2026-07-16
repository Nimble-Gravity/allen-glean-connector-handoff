"""Tests for validators.py — SAFE_IDENTIFIER regex and _coerce()."""

import datetime
import decimal

import pytest
from validators import SAFE_IDENTIFIER, _coerce

# --- SAFE_IDENTIFIER ---


@pytest.mark.parametrize(
    "value",
    [
        "vwDailyFinancialExtract",
        "column_name",
        "Col123",
        "A",
        "_underscore",
        "ALLCAPS",
    ],
)
def test_safe_identifier_accepts_valid(value):
    assert SAFE_IDENTIFIER.match(value)


@pytest.mark.parametrize(
    "value",
    [
        "bad name",
        "col; DROP TABLE users--",
        "col'injection",
        "col.dot",
        "col-dash",
        "col[bracket]",
        "",
        "col\ninjection",
        "col/**/",
    ],
)
def test_safe_identifier_rejects_invalid(value):
    assert not SAFE_IDENTIFIER.match(value)


# --- _coerce ---


def test_coerce_none():
    assert _coerce(None) is None


def test_coerce_bytes_utf8():
    assert _coerce(b"hello") == "hello"


def test_coerce_bytes_with_invalid_utf8():
    result = _coerce(b"\xff\xfe")
    assert isinstance(result, str)


def test_coerce_datetime():
    dt = datetime.datetime(2024, 3, 15, 10, 30, 0)
    result = _coerce(dt)
    assert result == "2024-03-15T10:30:00"


def test_coerce_date():
    d = datetime.date(2024, 3, 15)
    result = _coerce(d)
    assert result == "2024-03-15"


def test_coerce_time():
    t = datetime.time(10, 30, 0)
    result = _coerce(t)
    assert result == "10:30:00"


def test_coerce_decimal():
    result = _coerce(decimal.Decimal("3.14"))
    assert isinstance(result, float)
    assert result == pytest.approx(3.14)


def test_coerce_string_passthrough():
    assert _coerce("plain string") == "plain string"


def test_coerce_int_passthrough():
    assert _coerce(42) == 42


def test_coerce_float_passthrough():
    assert _coerce(1.5) == 1.5
