from datetime import datetime

from flask import Blueprint, g, redirect, render_template, request, session, url_for

from config import ENABLE_MOCK_ATO_LODGEMENT
from services.demo_service import is_demo

from services.database import (
    add_tax_adjustment,
    create_tax_return,
    delete_tax_adjustment,
    get_client_for_user,
    get_tax_adjustments,
    get_tax_return,
    get_tax_return_by_year,
    get_tax_returns_for_client,
    get_tax_returns_for_user,
    mark_tax_return_lodged,
    update_tax_return,
)
from services.tax_return_service import (
    SUPPORTED_ENTITY_TYPE,
    SUPPORTED_TAX_RATES,
    calculate_company_return,
    current_completed_financial_year,
    financial_year_dates,
    recent_completed_financial_years,
    format_money,
    import_accounting_profit,
    review_company_return,
    tax_return_status,
)


tax_bp = Blueprint("tax", __name__)


def _client(client_id):
    client = get_client_for_user(client_id, g.user["id"])
    if client:
        session["client_id"] = client_id
        g.client = client
    return client


def _return_for_client(client, tax_return_id):
    if not client:
        return None
    return get_tax_return(client["id"], tax_return_id)


def _decorate_return(tax_return):
    item = dict(tax_return)
    status, css_class = tax_return_status(item)
    item["display_status"] = status
    item["status_class"] = css_class
    item["estimated_tax_display"] = format_money(item.get("estimated_tax"))
    item["taxable_income_display"] = format_money(item.get("taxable_income"))
    item["accounting_profit_display"] = format_money(item.get("accounting_profit"))
    item["tax_rate_display"] = (
        f"{float(item['tax_rate']) * 100:.0f}%"
        if item.get("tax_rate") is not None
        else "Not confirmed"
    )
    item["is_lodged"] = (
        item.get("approval_status") == "LODGED"
        or bool(item.get("lodged_at"))
    )
    item["lodged_at_display"] = (
        str(item.get("lodged_at") or "").replace("T", " ")
        if item.get("lodged_at")
        else None
    )
    return item


def _reset_review_and_approval(client_id, tax_return_id):
    return update_tax_return(
        client_id,
        tax_return_id,
        review_status=None,
        review_text=None,
        reviewed_at=None,
        approval_status=None,
        approved_at=None,
    )


def _recalculate(client_id, tax_return_id):
    tax_return = get_tax_return(client_id, tax_return_id)
    adjustments = get_tax_adjustments(client_id, tax_return_id)
    calculation = calculate_company_return(tax_return, adjustments)

    return update_tax_return(
        client_id,
        tax_return_id,
        taxable_income=calculation["taxable_income"],
        estimated_tax=calculation["estimated_tax"],
    )


def _populate_demo_profit(client, tax_return):
    """Initialise empty demo drafts; preserve manual figures and locked returns."""
    if (
        not is_demo(client)
        or tax_return.get("accounting_profit") is not None
        or tax_return.get("approval_status") in {"APPROVED", "LODGED"}
        or tax_return.get("lodged_at")
    ):
        return tax_return

    profit = import_accounting_profit(
        client["id"], tax_return["start_date"], tax_return["end_date"]
    )
    update_tax_return(client["id"], tax_return["id"], accounting_profit=profit)
    _reset_review_and_approval(client["id"], tax_return["id"])
    return _recalculate(client["id"], tax_return["id"])


def _approved_response(client, tax_return):
    status = tax_return.get("approval_status")
    if status not in {"APPROVED", "LODGED"}:
        return None

    if status == "LODGED":
        title = "Tax return already lodged"
        message = (
            "This annual tax return is recorded as lodged and is read-only."
        )
    else:
        title = "Tax return already approved"
        message = (
            "This draft has been approved and is read-only. "
            "Approval means ready to lodge; ATO lodgement is not connected."
        )

    return render_template(
        "message.html",
        title=title,
        message=message,
        back_url=url_for(
            "tax.company_tax_return",
            client_id=client["id"],
            tax_return_id=tax_return["id"],
        ),
    )


@tax_bp.route("/tax-returns")
def tax_returns():
    session.pop("client_id", None)
    g.client = None

    records = [
        _decorate_return(item)
        for item in get_tax_returns_for_user(g.user["id"], limit=250)
    ]

    return render_template(
        "tax_returns.html",
        records=records,
    )


@tax_bp.route("/clients/<int:client_id>/tax-returns")
def client_tax_returns(client_id):
    client = _client(client_id)
    if not client:
        return redirect(url_for("clients.index"))

    records = [
        _decorate_return(item)
        for item in get_tax_returns_for_client(client_id, limit=50)
    ]
    active_records = [
        item for item in records
        if not item["is_lodged"]
    ]
    historical_records = [
        item for item in records
        if item["is_lodged"]
    ]

    existing_years = {item["financial_year"] for item in records}
    financial_year_options = [
        year
        for year in recent_completed_financial_years(count=10)
        if year not in existing_years
    ]

    requested_year = request.args.get("year", "").strip()
    default_financial_year = (
        financial_year_options[0]
        if financial_year_options
        else current_completed_financial_year()
    )

    if requested_year in financial_year_options:
        default_financial_year = requested_year

    return render_template(
        "client_tax_returns.html",
        client=client,
        records=records,
        active_records=active_records,
        historical_records=historical_records,
        financial_year_options=financial_year_options,
        default_financial_year=default_financial_year,
        supported_entity_type=SUPPORTED_ENTITY_TYPE,
        mock_ato_lodgement_enabled=ENABLE_MOCK_ATO_LODGEMENT or is_demo(client),
    )


@tax_bp.route("/clients/<int:client_id>/tax-returns/new", methods=["POST"])
def new_tax_return(client_id):
    client = _client(client_id)
    if not client:
        return redirect(url_for("clients.index"))

    if client.get("entity_type") != SUPPORTED_ENTITY_TYPE:
        return render_template(
            "message.html",
            title="Return type not available yet",
            message=(
                "The current prototype supports company tax returns only. "
                "Update the client entity type if this business is a company."
            ),
            back_url=url_for("tax.client_tax_returns", client_id=client_id),
        ), 400

    financial_year = (
        request.form.get("financial_year")
        or current_completed_financial_year()
    ).strip()

    try:
        start_date, end_date = financial_year_dates(financial_year)
    except ValueError as exc:
        return render_template(
            "message.html",
            title="Invalid financial year",
            message=str(exc),
            back_url=url_for("tax.client_tax_returns", client_id=client_id),
        ), 400

    tax_return = create_tax_return(
        client_id,
        financial_year,
        start_date,
        end_date,
        client["entity_type"],
    )
    tax_return = _populate_demo_profit(client, tax_return)

    return redirect(
        url_for(
            "tax.company_tax_return",
            client_id=client_id,
            tax_return_id=tax_return["id"],
        )
    )


@tax_bp.route("/clients/<int:client_id>/tax-returns/<int:tax_return_id>")
def company_tax_return(client_id, tax_return_id):
    client = _client(client_id)
    if not client:
        return redirect(url_for("clients.index"))

    tax_return = _return_for_client(client, tax_return_id)
    if not tax_return:
        return render_template(
            "message.html",
            title="Tax return not found",
            message="The requested annual tax return could not be found.",
            back_url=url_for("tax.client_tax_returns", client_id=client_id),
        ), 404

    tax_return = _populate_demo_profit(client, tax_return)
    adjustments = get_tax_adjustments(client_id, tax_return_id)
    calculation = calculate_company_return(tax_return, adjustments)
    record = _decorate_return(tax_return)

    return render_template(
        "company_tax_return.html",
        client=client,
        tax_return=record,
        adjustments=adjustments,
        calculation=calculation,
        tax_rates=SUPPORTED_TAX_RATES,
        mock_ato_lodgement_enabled=ENABLE_MOCK_ATO_LODGEMENT or is_demo(client),
    )


@tax_bp.route(
    "/clients/<int:client_id>/tax-returns/<int:tax_return_id>/refresh-qbo",
    methods=["POST"],
)
def refresh_tax_return_from_qbo(client_id, tax_return_id):
    client = _client(client_id)
    tax_return = _return_for_client(client, tax_return_id)

    if not client or not tax_return:
        return redirect(url_for("clients.index"))

    approved = _approved_response(client, tax_return)
    if approved:
        return approved

    if not client.get("qbo_connected") and not is_demo(client):
        return redirect(url_for("clients.quickbooks_client", client_id=client_id))

    try:
        accounting_profit = import_accounting_profit(
            client_id,
            tax_return["start_date"],
            tax_return["end_date"],
        )
    except (RuntimeError, ValueError) as exc:
        return render_template(
            "message.html",
            title="QuickBooks import failed",
            message=str(exc),
            back_url=url_for(
                "tax.company_tax_return",
                client_id=client_id,
                tax_return_id=tax_return_id,
            ),
        ), 400

    update_tax_return(
        client_id,
        tax_return_id,
        accounting_profit=accounting_profit,
    )
    _reset_review_and_approval(client_id, tax_return_id)
    _recalculate(client_id, tax_return_id)

    return redirect(
        url_for(
            "tax.company_tax_return",
            client_id=client_id,
            tax_return_id=tax_return_id,
        )
    )


@tax_bp.route(
    "/clients/<int:client_id>/tax-returns/<int:tax_return_id>/accounting-profit",
    methods=["POST"],
)
def update_accounting_profit(client_id, tax_return_id):
    client = _client(client_id)
    tax_return = _return_for_client(client, tax_return_id)

    if not client or not tax_return:
        return redirect(url_for("clients.index"))

    approved = _approved_response(client, tax_return)
    if approved:
        return approved

    raw_value = request.form.get("accounting_profit", "").replace(",", "").strip()

    try:
        accounting_profit = float(raw_value)
    except ValueError:
        return render_template(
            "message.html",
            title="Invalid accounting profit",
            message="Enter a valid accounting profit or loss amount.",
            back_url=url_for(
                "tax.company_tax_return",
                client_id=client_id,
                tax_return_id=tax_return_id,
            ),
        ), 400

    update_tax_return(
        client_id,
        tax_return_id,
        accounting_profit=accounting_profit,
    )
    _reset_review_and_approval(client_id, tax_return_id)
    _recalculate(client_id, tax_return_id)

    return redirect(
        url_for(
            "tax.company_tax_return",
            client_id=client_id,
            tax_return_id=tax_return_id,
        )
    )


@tax_bp.route(
    "/clients/<int:client_id>/tax-returns/<int:tax_return_id>/tax-rate",
    methods=["POST"],
)
def update_tax_rate(client_id, tax_return_id):
    client = _client(client_id)
    tax_return = _return_for_client(client, tax_return_id)

    if not client or not tax_return:
        return redirect(url_for("clients.index"))

    approved = _approved_response(client, tax_return)
    if approved:
        return approved

    try:
        tax_rate = float(request.form.get("tax_rate", ""))
    except ValueError:
        tax_rate = None

    if tax_rate not in SUPPORTED_TAX_RATES:
        return render_template(
            "message.html",
            title="Confirm company tax rate",
            message="Select either the 25% base-rate-entity rate or the 30% company rate.",
            back_url=url_for(
                "tax.company_tax_return",
                client_id=client_id,
                tax_return_id=tax_return_id,
            ),
        ), 400

    update_tax_return(
        client_id,
        tax_return_id,
        tax_rate=tax_rate,
    )
    _reset_review_and_approval(client_id, tax_return_id)
    _recalculate(client_id, tax_return_id)

    return redirect(
        url_for(
            "tax.company_tax_return",
            client_id=client_id,
            tax_return_id=tax_return_id,
        )
    )


@tax_bp.route(
    "/clients/<int:client_id>/tax-returns/<int:tax_return_id>/adjustments",
    methods=["POST"],
)
def add_adjustment(client_id, tax_return_id):
    client = _client(client_id)
    tax_return = _return_for_client(client, tax_return_id)

    if not client or not tax_return:
        return redirect(url_for("clients.index"))

    approved = _approved_response(client, tax_return)
    if approved:
        return approved

    adjustment_type = request.form.get("adjustment_type", "").strip().upper()
    category = request.form.get("category", "").strip()
    description = request.form.get("description", "").strip()

    try:
        amount = float(
            request.form.get("amount", "").replace(",", "").strip()
        )
    except ValueError:
        amount = 0

    if (
        adjustment_type not in {"ADD", "DEDUCT"}
        or not category
        or not description
        or amount <= 0
    ):
        return render_template(
            "message.html",
            title="Adjustment details required",
            message=(
                "Choose add-back or deduction, enter a category and description, "
                "and use an amount greater than zero."
            ),
            back_url=url_for(
                "tax.company_tax_return",
                client_id=client_id,
                tax_return_id=tax_return_id,
            ),
        ), 400

    add_tax_adjustment(
        client_id,
        tax_return_id,
        adjustment_type,
        category,
        description,
        amount,
    )
    _reset_review_and_approval(client_id, tax_return_id)
    _recalculate(client_id, tax_return_id)

    return redirect(
        url_for(
            "tax.company_tax_return",
            client_id=client_id,
            tax_return_id=tax_return_id,
        )
    )


@tax_bp.route(
    "/clients/<int:client_id>/tax-returns/<int:tax_return_id>/adjustments/"
    "<int:adjustment_id>/delete",
    methods=["POST"],
)
def remove_adjustment(client_id, tax_return_id, adjustment_id):
    client = _client(client_id)
    tax_return = _return_for_client(client, tax_return_id)

    if not client or not tax_return:
        return redirect(url_for("clients.index"))

    approved = _approved_response(client, tax_return)
    if approved:
        return approved

    delete_tax_adjustment(
        client_id,
        tax_return_id,
        adjustment_id,
    )
    _reset_review_and_approval(client_id, tax_return_id)
    _recalculate(client_id, tax_return_id)

    return redirect(
        url_for(
            "tax.company_tax_return",
            client_id=client_id,
            tax_return_id=tax_return_id,
        )
    )


@tax_bp.route(
    "/clients/<int:client_id>/tax-returns/<int:tax_return_id>/review",
    methods=["POST"],
)
def review_tax_return(client_id, tax_return_id):
    client = _client(client_id)
    tax_return = _return_for_client(client, tax_return_id)

    if not client or not tax_return:
        return redirect(url_for("clients.index"))

    approved = _approved_response(client, tax_return)
    if approved:
        return approved

    adjustments = get_tax_adjustments(client_id, tax_return_id)
    result = review_company_return(tax_return, adjustments)
    calculation = result["calculation"]

    update_tax_return(
        client_id,
        tax_return_id,
        taxable_income=calculation["taxable_income"],
        estimated_tax=calculation["estimated_tax"],
        review_status=result["status"],
        review_text=result["review_text"],
        reviewed_at=datetime.now().isoformat(timespec="seconds"),
        approval_status=None,
        approved_at=None,
    )

    return redirect(
        url_for(
            "tax.company_tax_return",
            client_id=client_id,
            tax_return_id=tax_return_id,
        )
    )


@tax_bp.route(
    "/clients/<int:client_id>/tax-returns/<int:tax_return_id>/reopen",
    methods=["POST"],
)
def reopen_tax_return(client_id, tax_return_id):
    client = _client(client_id)
    tax_return = _return_for_client(client, tax_return_id)

    if not client or not tax_return:
        return redirect(url_for("clients.index"))

    if (
        tax_return.get("approval_status") == "LODGED"
        or tax_return.get("lodged_at")
    ):
        return render_template(
            "message.html",
            title="Tax return is lodged",
            message=(
                "A lodged annual tax return is read-only and cannot be reopened "
                "from this workflow."
            ),
            back_url=url_for(
                "tax.company_tax_return",
                client_id=client_id,
                tax_return_id=tax_return_id,
            ),
        ), 400

    if tax_return.get("approval_status") != "APPROVED":
        return redirect(
            url_for(
                "tax.company_tax_return",
                client_id=client_id,
                tax_return_id=tax_return_id,
            )
        )

    update_tax_return(
        client_id,
        tax_return_id,
        approval_status=None,
        approved_at=None,
    )

    return redirect(
        url_for(
            "tax.company_tax_return",
            client_id=client_id,
            tax_return_id=tax_return_id,
        )
    )


@tax_bp.route(
    "/clients/<int:client_id>/tax-returns/<int:tax_return_id>/mock-lodge",
    methods=["POST"],
)
def mock_lodge_tax_return(client_id, tax_return_id):
    if not ENABLE_MOCK_ATO_LODGEMENT and not is_demo(
        get_client_for_user(client_id, g.user["id"])
    ):
        return render_template(
            "message.html",
            title="Mock lodgement disabled",
            message=(
                "Mock ATO lodgement is disabled. Set "
                "ENABLE_MOCK_ATO_LODGEMENT=true in the local environment to use it."
            ),
            back_url=url_for(
                "tax.client_tax_returns",
                client_id=client_id,
            ),
        ), 404

    client = _client(client_id)
    tax_return = _return_for_client(client, tax_return_id)

    if not client or not tax_return:
        return redirect(url_for("clients.index"))

    if (
        tax_return.get("approval_status") == "LODGED"
        or tax_return.get("lodged_at")
    ):
        return redirect(
            url_for(
                "tax.client_tax_returns",
                client_id=client_id,
            )
        )

    if tax_return.get("approval_status") != "APPROVED":
        return render_template(
            "message.html",
            title="Tax return is not ready to lodge",
            message=(
                "Approve the annual tax return first. Mock lodgement is only "
                "available for returns with status Approved - Ready to Lodge."
            ),
            back_url=url_for(
                "tax.company_tax_return",
                client_id=client_id,
                tax_return_id=tax_return_id,
            ),
        ), 400

    mock_reference = (
        f"MOCK-TAX-{client_id}-"
        f"{datetime.now().strftime('%Y%m%d%H%M%S')}"
    )

    lodged = mark_tax_return_lodged(
        client_id,
        tax_return_id,
        lodgement_reference=mock_reference,
    )

    if not lodged or not lodged.get("lodged_at"):
        return render_template(
            "message.html",
            title="Mock lodgement failed",
            message="The annual tax return could not be marked as lodged.",
            back_url=url_for(
                "tax.company_tax_return",
                client_id=client_id,
                tax_return_id=tax_return_id,
            ),
        ), 500

    return redirect(
        url_for(
            "tax.client_tax_returns",
            client_id=client_id,
        )
    )


@tax_bp.route(
    "/clients/<int:client_id>/tax-returns/<int:tax_return_id>/approve",
    methods=["POST"],
)
def approve_tax_return(client_id, tax_return_id):
    client = _client(client_id)
    tax_return = _return_for_client(client, tax_return_id)

    if not client or not tax_return:
        return redirect(url_for("clients.index"))

    if tax_return.get("approval_status") in {"APPROVED", "LODGED"}:
        return redirect(
            url_for(
                "tax.company_tax_return",
                client_id=client_id,
                tax_return_id=tax_return_id,
            )
        )

    if tax_return.get("review_status") != "PASS":
        return render_template(
            "message.html",
            title="Review required before approval",
            message=(
                "Run the annual tax return review and resolve all required items "
                "before approving this draft."
            ),
            back_url=url_for(
                "tax.company_tax_return",
                client_id=client_id,
                tax_return_id=tax_return_id,
            ),
        ), 400

    update_tax_return(
        client_id,
        tax_return_id,
        approval_status="APPROVED",
        approved_at=datetime.now().isoformat(timespec="seconds"),
    )

    return redirect(
        url_for(
            "tax.company_tax_return",
            client_id=client_id,
            tax_return_id=tax_return_id,
        )
    )
