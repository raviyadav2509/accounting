from datetime import datetime

import pytest

from services.tax_return_service import (
    calculate_company_return,
    current_completed_financial_year,
    extract_accounting_profit,
    financial_year_dates,
    format_money,
    recent_completed_financial_years,
    review_company_return,
    tax_return_status,
)


def test_financial_year_dates_validates_format_and_sequence():
    assert financial_year_dates("2025-26") == ("2025-07-01", "2026-06-30")

    with pytest.raises(ValueError, match="format"):
        financial_year_dates("FY2026")

    with pytest.raises(ValueError, match="consecutive"):
        financial_year_dates("2025-27")


def test_extract_accounting_profit_prefers_nested_net_income():
    report = {
        "Rows": {
            "Row": [
                {"ColData": [{"value": "Total Income"}, {"value": "125,000"}]},
                {"Rows": {"Row": [
                    {"ColData": [{"value": "Net Income"}, {"value": "$31,250.50"}]}
                ]}},
            ]
        }
    }

    assert extract_accounting_profit(report) == 31250.50


def test_extract_accounting_profit_supports_parenthesised_losses():
    report = {"ColData": [{"value": "Net Profit"}, {"value": "($2,500.25)"}]}
    assert extract_accounting_profit(report) == -2500.25


def test_extract_accounting_profit_falls_back_to_income_less_expenses():
    report = {
        "Rows": [
            {"ColData": [{"value": "Total Income"}, {"value": "100000"}]},
            {"ColData": [{"value": "Total Expenses"}, {"value": "65000"}]},
            {"ColData": [{"value": "Total Other Income"}, {"value": "2000"}]},
            {"ColData": [{"value": "Total Other Expenses"}, {"value": "500"}]},
        ]
    }
    assert extract_accounting_profit(report) == 36500


def test_company_return_calculation_and_review_pass():
    tax_return = {
        "entity_type": "COMPANY",
        "accounting_profit": 100000,
        "tax_rate": 0.25,
    }
    adjustments = [
        {"adjustment_type": "ADD", "amount": 10000},
        {"adjustment_type": "DEDUCT", "amount": 5000},
    ]

    calculation = calculate_company_return(tax_return, adjustments)
    assert calculation["taxable_income"] == 105000
    assert calculation["estimated_tax"] == 26250

    review = review_company_return(tax_return, adjustments)
    assert review["status"] == "PASS"
    assert "accountant" in review["review_text"]


def test_company_return_review_requires_human_decisions():
    review = review_company_return(
        {"entity_type": "COMPANY", "accounting_profit": None, "tax_rate": None},
        [],
    )
    assert review["status"] == "REVIEW REQUIRED"
    assert "Accounting profit has not been imported" in review["review_text"]
    assert "Confirm whether the company uses" in review["review_text"]


@pytest.mark.parametrize(
    ("tax_return", "expected"),
    [
        ({"approval_status": "LODGED"}, ("Lodged", "lodged")),
        ({"lodged_at": "2026-09-20"}, ("Lodged", "lodged")),
        ({"approval_status": "APPROVED"}, ("Approved - Ready to Lodge", "approved")),
        ({"review_status": "REVIEW REQUIRED"}, ("Review Required", "review-required")),
        ({"review_status": "PASS"}, ("Ready to Approve", "pass")),
        ({}, ("Draft", "not-reviewed")),
    ],
)
def test_tax_return_status(tax_return, expected):
    assert tax_return_status(tax_return) == expected


def test_completed_financial_year_helpers():
    now = datetime(2026, 9, 21)
    assert current_completed_financial_year(now) == "2025-26"
    assert recent_completed_financial_years(3, now) == [
        "2025-26",
        "2024-25",
        "2023-24",
    ]


def test_format_money():
    assert format_money(None) == "Not calculated"
    assert format_money(1234.5) == "$1,234.50"
    assert format_money(-12.5) == "-$12.50"

