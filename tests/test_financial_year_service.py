from datetime import date, datetime

import pytest

from services.financial_year_service import (
    current_financial_year,
    financial_year_for_date,
    financial_year_sort_key,
)


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (date(2026, 6, 30), "2025-26"),
        (date(2026, 7, 1), "2026-27"),
        (datetime(2027, 1, 15, 12, 30), "2026-27"),
        ("2027-06-30T23:59:59", "2026-27"),
    ],
)
def test_financial_year_for_date_handles_australian_boundaries(value, expected):
    assert financial_year_for_date(value) == expected


def test_current_financial_year_uses_supplied_time():
    assert current_financial_year(datetime(2026, 6, 30)) == "2025-26"
    assert current_financial_year(datetime(2026, 7, 1)) == "2026-27"


def test_financial_year_sort_key_is_safe_for_invalid_values():
    assert financial_year_sort_key("2026-27") == 2026
    assert financial_year_sort_key(None) == 0
    assert financial_year_sort_key("invalid") == 0


def test_financial_year_for_date_rejects_unsupported_values():
    with pytest.raises(ValueError, match="valid date"):
        financial_year_for_date(object())

