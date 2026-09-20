import re
from datetime import datetime

from services.qbo_service import get_report


SUPPORTED_ENTITY_TYPE = "COMPANY"
SUPPORTED_TAX_RATES = {
    0.25: "Base rate entity — 25%",
    0.30: "Other company — 30%",
}


def financial_year_dates(financial_year):
    match = re.fullmatch(r"(\d{4})-(\d{2})", (financial_year or "").strip())
    if not match:
        raise ValueError("Use a financial year in the format 2025-26.")

    start_year = int(match.group(1))
    end_suffix = int(match.group(2))
    end_year = start_year + 1

    if end_year % 100 != end_suffix:
        raise ValueError("The financial year must span consecutive years.")

    return (
        f"{start_year:04d}-07-01",
        f"{end_year:04d}-06-30",
    )


def _number(value):
    if value is None:
        return None

    if isinstance(value, (int, float)):
        return float(value)

    text = str(value).strip()
    if not text:
        return None

    negative = text.startswith("(") and text.endswith(")")
    text = text.replace("$", "").replace(",", "").replace("(", "").replace(")", "")

    try:
        amount = float(text)
    except ValueError:
        return None

    return -amount if negative else amount


def _collect_report_values(node, values):
    if isinstance(node, list):
        for item in node:
            _collect_report_values(item, values)
        return

    if not isinstance(node, dict):
        return

    col_data = node.get("ColData")
    if isinstance(col_data, list) and col_data:
        label = str(col_data[0].get("value") or "").strip()
        if label:
            for column in reversed(col_data[1:]):
                amount = _number(column.get("value"))
                if amount is not None:
                    values[label.casefold()] = amount
                    break

    for value in node.values():
        _collect_report_values(value, values)


def extract_accounting_profit(report):
    values = {}
    _collect_report_values(report, values)

    for label in ("net income", "net profit"):
        if label in values:
            return values[label]

    net_operating_income = values.get("net operating income")
    net_other_income = values.get("net other income")
    if net_operating_income is not None and net_other_income is not None:
        return net_operating_income + net_other_income

    total_income = values.get("total income")
    total_expenses = (
        values.get("total expenses")
        or values.get("total expense")
    )
    total_other_income = values.get("total other income") or 0
    total_other_expenses = values.get("total other expenses") or 0

    if total_income is not None and total_expenses is not None:
        return (
            total_income
            - total_expenses
            + total_other_income
            - total_other_expenses
        )

    if net_operating_income is not None:
        return net_operating_income

    raise ValueError(
        "QuickBooks Profit & Loss did not contain a recognisable Net Income value."
    )


def import_accounting_profit(client_id, start_date, end_date):
    report = get_report(
        client_id,
        "ProfitAndLoss",
        start_date,
        end_date,
    )
    return extract_accounting_profit(report)


def calculate_company_return(tax_return, adjustments):
    accounting_profit = tax_return.get("accounting_profit")
    additions = sum(
        float(item.get("amount") or 0)
        for item in adjustments
        if item.get("adjustment_type") == "ADD"
    )
    deductions = sum(
        float(item.get("amount") or 0)
        for item in adjustments
        if item.get("adjustment_type") == "DEDUCT"
    )

    taxable_income = None
    estimated_tax = None

    if accounting_profit is not None:
        taxable_income = float(accounting_profit) + additions - deductions

        tax_rate = tax_return.get("tax_rate")
        if tax_rate is not None:
            estimated_tax = max(taxable_income, 0) * float(tax_rate)

    return {
        "accounting_profit": accounting_profit,
        "additions": additions,
        "deductions": deductions,
        "taxable_income": taxable_income,
        "tax_rate": tax_return.get("tax_rate"),
        "estimated_tax": estimated_tax,
    }


def review_company_return(tax_return, adjustments):
    calculation = calculate_company_return(tax_return, adjustments)
    issues = []
    checks = []

    if tax_return.get("entity_type") != SUPPORTED_ENTITY_TYPE:
        issues.append(
            "This prototype currently supports company tax returns only."
        )

    if calculation["accounting_profit"] is None:
        issues.append(
            "Accounting profit has not been imported or entered."
        )
    else:
        checks.append(
            "Accounting profit is present for the financial year."
        )

    if calculation["tax_rate"] not in SUPPORTED_TAX_RATES:
        issues.append(
            "Confirm whether the company uses the 25% base-rate-entity rate "
            "or the 30% company rate."
        )
    else:
        checks.append(
            "A company tax rate has been confirmed by the accountant."
        )

    if calculation["taxable_income"] is not None:
        if calculation["taxable_income"] < 0:
            issues.append(
                "The draft is in a tax-loss position. Loss utilisation, "
                "carry-forward rules and related tests are not modelled in this prototype."
            )
        else:
            checks.append(
                "The tax reconciliation produces a non-negative taxable income."
            )

    if adjustments:
        checks.append(
            f"{len(adjustments)} tax adjustment(s) are recorded in the reconciliation."
        )
    else:
        checks.append(
            "No tax adjustments are recorded. Confirm that accounting profit "
            "requires no add-backs or deductions before approval."
        )

    status = "REVIEW REQUIRED" if issues else "PASS"
    lines = []

    if issues:
        lines.append("Items requiring accountant review:")
        lines.extend(f"- {item}" for item in issues)

    if checks:
        if lines:
            lines.append("")
        lines.append("Checks completed:")
        lines.extend(f"- {item}" for item in checks)

    lines.extend(
        [
            "",
            "Important: this draft does not calculate tax offsets, credits, "
            "franking consequences, PAYG instalment credits, Division 7A, "
            "capital gains schedules, losses, R&D incentives or other specialist schedules.",
        ]
    )

    return {
        "status": status,
        "review_text": "\n".join(lines),
        "calculation": calculation,
    }


def tax_return_status(tax_return):
    if (
        tax_return.get("approval_status") == "LODGED"
        or bool(tax_return.get("lodged_at"))
    ):
        return "Lodged", "lodged"

    if tax_return.get("approval_status") == "APPROVED":
        return "Approved - Ready to Lodge", "approved"

    if tax_return.get("review_status") == "REVIEW REQUIRED":
        return "Review Required", "review-required"

    if tax_return.get("review_status") == "PASS":
        return "Ready to Approve", "pass"

    return "Draft", "not-reviewed"


def display_financial_year(financial_year):
    return f"FY {financial_year}"


def format_money(value):
    if value is None:
        return "Not calculated"

    amount = float(value)
    if amount < 0:
        return f"-${abs(amount):,.2f}"
    return f"${amount:,.2f}"


def current_completed_financial_year(now=None):
    now = now or datetime.now()
    if now.month >= 7:
        start_year = now.year - 1
    else:
        start_year = now.year - 2

    return f"{start_year:04d}-{(start_year + 1) % 100:02d}"
