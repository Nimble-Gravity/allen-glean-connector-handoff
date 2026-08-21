"""Tests for validators.py — SAFE_IDENTIFIER regex and _coerce()."""

import datetime
import decimal

import pytest
from validators import SAFE_IDENTIFIER, _coerce, build_where, escape_like, parse_filters

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


# --- Filter parsing / WHERE building ---


def _where(raw):
    """Parse `raw` and build predicates + bound params; return (predicates, params)."""
    filters = parse_filters(raw)
    params: list = []
    predicates = build_where(filters, params)
    return predicates, params


def test_parse_filters_empty_returns_empty():
    assert parse_filters(None) == []
    assert parse_filters("") == []
    assert parse_filters("   ") == []


def test_filters_comparison_ops_bind_scalar():
    preds, params = _where('[{"column":"Age","op":"gte","value":21}]')
    assert preds == ["[Age] >= ?"]
    assert params == [21]


def test_filters_multiple_and_preserve_order():
    raw = (
        '[{"column":"CompanyName","op":"eq","value":"Acme"},'
        '{"column":"EventInstanceID","op":"gte","value":"3"}]'
    )
    preds, params = _where(raw)
    assert preds == ["[CompanyName] = ?", "[EventInstanceID] >= ?"]
    assert params == ["Acme", "3"]


def test_filters_between_binds_two():
    preds, params = _where(
        '[{"column":"UpdatedOn","op":"between","value":["2026-01-01","2026-01-31"]}]'
    )
    assert preds == ["[UpdatedOn] BETWEEN ? AND ?"]
    assert params == ["2026-01-01", "2026-01-31"]


def test_filters_in_binds_each_element():
    preds, params = _where('[{"column":"Code","op":"in","value":["A","B","C"]}]')
    assert preds == ["[Code] IN (?, ?, ?)"]
    assert params == ["A", "B", "C"]


def test_filters_is_null_and_is_not_null_bind_nothing():
    preds, params = _where('[{"column":"DeletedOn","op":"is_null"}]')
    assert preds == ["[DeletedOn] IS NULL"]
    assert params == []
    preds, params = _where('[{"column":"DeletedOn","op":"is_not_null"}]')
    assert preds == ["[DeletedOn] IS NOT NULL"]
    assert params == []


def test_filters_contains_wraps_and_escapes():
    preds, params = _where('[{"column":"CompanyName","op":"contains","value":"Cap"}]')
    assert preds == ["[CompanyName] LIKE ? ESCAPE '\\'"]
    assert params == ["%Cap%"]


def test_filters_startswith_endswith():
    _, start = _where('[{"column":"Name","op":"startswith","value":"Ab"}]')
    assert start == ["Ab%"]
    _, end = _where('[{"column":"Name","op":"endswith","value":"Ab"}]')
    assert end == ["%Ab"]


def test_filters_contains_escapes_user_wildcards():
    _, params = _where('[{"column":"C","op":"contains","value":"50%_x"}]')
    assert params == ["%50\\%\\_x%"]


def test_escape_like_neutralizes_metacharacters():
    assert escape_like("a%b_c[d\\e") == "a\\%b\\_c\\[d\\\\e"


@pytest.mark.parametrize(
    "raw",
    [
        "not json",
        '{"column":"a","op":"eq","value":1}',  # object, not an array
        '[{"op":"eq","value":1}]',  # missing column
        '[{"column":"bad col","op":"eq","value":1}]',  # unsafe column
        '[{"column":"a","op":"like","value":1}]',  # unknown op
        '[{"column":"a","op":"between","value":[1]}]',  # between arity 1
        '[{"column":"a","op":"between","value":[1,2,3]}]',  # between arity 3
        '[{"column":"a","op":"in","value":[]}]',  # empty in
        '[{"column":"a","op":"contains","value":5}]',  # non-string text op
        '[{"column":"a","op":"eq","value":[1,2]}]',  # scalar op given a list
        '[{"column":"a","op":"eq"}]',  # scalar op missing value
    ],
)
def test_parse_filters_rejects(raw):
    with pytest.raises(ValueError):
        parse_filters(raw)
