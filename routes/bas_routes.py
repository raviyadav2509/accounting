import re
from datetime import datetime

import markdown
from flask import Blueprint, g, redirect, render_template, request, session, url_for

from config import DEFAULT_BAS_END, DEFAULT_BAS_START, ENABLE_MOCK_ATO_LODGEMENT
from services.ai_review_service import run_ai_review
from services.bas_service import (
    bas_signature,
    bas_summary_payload,
    calculate_bas,
    get_payroll_bas,
)
from services.financial_year_service import (
    current_financial_year,
    financial_year_for_date,
    financial_year_sort_key,
)
from services.database import (
    get_client_for_user,
    get_firm_for_user,
    get_history,
    get_history_for_user,
    get_record_for_user,
    get_tax_returns_for_user,
    mark_lodged,
    reopen_bas,
    save_bas_snapshot,
)
from services.review_store import (
    load_ai_review,
    resolve_ai_review,
    save_ai_review,
    save_approval,
    save_rejection,
)
from services.tax_return_service import tax_return_status

bas_bp = Blueprint("bas", __name__)


def _active_client():
    client_id = session.get("client_id")
    if not client_id:
        return None
    return get_client_for_user(client_id, g.user["id"])


def _require_client():
    client = _active_client()

    if not client:
        return None, redirect(url_for("clients.index"))

    if not client.get("qbo_connected"):
        return client, redirect(
            url_for("clients.quickbooks_client", client_id=client["id"])
        )

    return client, None


def _period_from_request():
    return (
        request.values.get("start", DEFAULT_BAS_START),
        request.values.get("end", DEFAULT_BAS_END),
    )


def _persist_bas(client_id, bas):
    signature = bas_signature(bas)
    record = save_bas_snapshot(client_id, bas, signature)
    return signature, record


def _amount_display_data(payable):
    if payable >= 0:
        return {
            "amount_heading": "Estimated amount payable to the ATO",
            "amount_note": (
                "This combines the GST position and employee tax "
                "withheld during this BAS period."
            ),
            "amount_display": f"${payable:,.2f}",
        }

    return {
        "amount_heading": "Estimated BAS credit / refund",
        "amount_note": (
            "Based on the current figures, the ATO position "
            "is in your favour for this BAS period."
        ),
        "amount_display": f"${abs(payable):,.2f}",
    }


def _record_status(record):
    approval_status = record.get("approval_status")
    review_status = record.get("review_status")
    resolution_status = record.get("resolution_status")

    if approval_status == "LODGED":
        return "Lodged", "lodged"

    if approval_status == "APPROVED":
        return "Approved - Ready to Lodge", "approved"

    if approval_status == "REJECTED":
        return "Rejected", "rejected"

    if review_status == "REVIEW REQUIRED":
        if resolution_status == "RESOLVED":
            return "Resolved - Ready to Approve", "resolved"
        return "Review Required", "review-required"

    if review_status == "WARNING":
        return "Warning", "warning"

    if review_status == "PASS":
        return "Ready to Approve", "pass"

    return "Not Reviewed", "not-reviewed"


def _format_date(value):
    if not value:
        return None

    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        try:
            parsed = datetime.strptime(value, "%Y-%m-%d")
        except ValueError:
            return value

    return f"{parsed.day} {parsed.strftime('%b %Y')}"


def _format_datetime(value):
    if not value:
        return None

    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return value

    hour = parsed.strftime("%I").lstrip("0") or "0"
    return f"{parsed.day} {parsed.strftime('%b %Y')}, {hour}:{parsed.strftime('%M %p')}"


def _format_period(start, end):
    try:
        start_date = datetime.strptime(start, "%Y-%m-%d")
        end_date = datetime.strptime(end, "%Y-%m-%d")
    except ValueError:
        return f"{start} to {end}"

    if start_date.year == end_date.year and start_date.month == end_date.month:
        return f"{start_date.day}–{end_date.day} {end_date.strftime('%B %Y')}"

    if start_date.year == end_date.year:
        return (
            f"{start_date.day} {start_date.strftime('%b')} – "
            f"{end_date.day} {end_date.strftime('%b %Y')}"
        )

    return (
        f"{start_date.day} {start_date.strftime('%b %Y')} – "
        f"{end_date.day} {end_date.strftime('%b %Y')}"
    )


def _decorate_record(record):
    item = dict(record)
    label, css_class = _record_status(item)
    item["display_status"] = label
    item["status_class"] = css_class

    payable = item.get("payable", 0) or 0
    if payable >= 0:
        item["amount_heading"] = "Estimated amount payable"
        item["amount_display"] = f"${payable:,.2f}"
    else:
        item["amount_heading"] = "Estimated credit / refund"
        item["amount_display"] = f"${abs(payable):,.2f}"

    item["is_lodged"] = (
        item.get("approval_status") == "LODGED"
        or bool(item.get("lodged_at"))
    )
    item["period_display"] = _format_period(
        item["start_date"],
        item["end_date"],
    )
    item["financial_year"] = financial_year_for_date(item["end_date"])

    for field in (
        "created_at",
        "updated_at",
        "reviewed_at",
        "resolved_at",
        "approved_at",
        "rejected_at",
        "lodged_at",
    ):
        item[f"{field}_display"] = _format_datetime(item.get(field))

    if item.get("lodged_at"):
        item["status_date_label"] = "Lodged"
        item["status_date"] = _format_date(item["lodged_at"])
    elif item.get("approved_at"):
        item["status_date_label"] = "Approved"
        item["status_date"] = _format_date(item["approved_at"])
    elif item.get("rejected_at"):
        item["status_date_label"] = "Rejected"
        item["status_date"] = _format_date(item["rejected_at"])
    elif item.get("resolved_at"):
        item["status_date_label"] = "Resolved"
        item["status_date"] = _format_date(item["resolved_at"])
    elif item.get("reviewed_at"):
        item["status_date_label"] = "Reviewed"
        item["status_date"] = _format_date(item["reviewed_at"])
    else:
        item["status_date_label"] = "Created"
        item["status_date"] = _format_date(item.get("created_at"))

    return item


def _record_for_period(client_id, start, end):
    return next(
        (
            _decorate_record(record)
            for record in get_history(client_id, limit=100)
            if record["start_date"] == start
            and record["end_date"] == end
        ),
        None,
    )


def _lodged_period_response(client, start, end):
    record = _record_for_period(client["id"], start, end)
    if record and record["is_lodged"]:
        return redirect(
            url_for(
                "bas.bas_history_detail",
                record_id=record["id"],
                client_context=1,
            )
        )
    return None


@bas_bp.route("/")
def dashboard():
    session.pop("client_id", None)
    g.client = None
    firm = get_firm_for_user(g.user["id"])

    clients = list(g.clients)
    current_fy = current_financial_year()

    qbo_connected_count = 0
    qbo_attention_count = 0

    bas_in_progress_count = 0
    bas_review_required_count = 0
    bas_ready_to_lodge_count = 0
    bas_lodged_this_fy_count = 0

    tax_in_progress_count = 0
    tax_review_required_count = 0
    tax_ready_to_lodge_count = 0
    tax_lodged_this_fy_count = 0

    attention_items = []

    for client in clients:
        if client.get("qbo_connected"):
            qbo_connected_count += 1
        else:
            qbo_attention_count += 1
            attention_items.append(
                {
                    "type": "client",
                    "type_label": "Client",
                    "client": client,
                    "title": "QuickBooks connection required",
                    "detail": "Accounting data is not connected for this client.",
                    "status": "Setup required",
                    "status_class": "warning",
                    "url": url_for(
                        "clients.quickbooks_client",
                        client_id=client["id"],
                    ),
                    "priority": 1,
                }
            )

        records = [
            _decorate_record(record)
            for record in get_history(client["id"], limit=200)
        ]

        in_progress_records = [
            record
            for record in records
            if not record["is_lodged"]
        ]
        bas_in_progress_count += len(in_progress_records)

        bas_lodged_this_fy_count += sum(
            1
            for record in records
            if record["is_lodged"]
            and record.get("lodged_at")
            and financial_year_for_date(record["lodged_at"]) == current_fy
        )

        for record in in_progress_records:
            if record.get("approval_status") == "APPROVED":
                bas_ready_to_lodge_count += 1
                attention_items.append(
                    {
                        "type": "bas",
                        "type_label": "BAS",
                        "client": client,
                        "title": "BAS ready to lodge",
                        "detail": record["period_display"],
                        "status": "Ready to lodge",
                        "status_class": "approved",
                        "url": url_for(
                            "bas.active_bas",
                            client_id=client["id"],
                        ),
                        "priority": 3,
                    }
                )
            elif (
                record.get("review_status") == "REVIEW REQUIRED"
                and record.get("resolution_status") != "RESOLVED"
            ):
                bas_review_required_count += 1
                attention_items.append(
                    {
                        "type": "bas",
                        "type_label": "BAS",
                        "client": client,
                        "title": "BAS review required",
                        "detail": record["period_display"],
                        "status": "Review required",
                        "status_class": "review-required",
                        "url": url_for(
                            "bas.bas_review",
                            start=record["start_date"],
                            end=record["end_date"],
                        ),
                        "priority": 2,
                    }
                )

    tax_returns = get_tax_returns_for_user(g.user["id"], limit=500)

    for tax_return in tax_returns:
        is_lodged = (
            tax_return.get("approval_status") == "LODGED"
            or bool(tax_return.get("lodged_at"))
        )

        if is_lodged:
            if (
                tax_return.get("lodged_at")
                and financial_year_for_date(tax_return["lodged_at"]) == current_fy
            ):
                tax_lodged_this_fy_count += 1
            continue

        tax_in_progress_count += 1

        client = next(
            (
                item
                for item in clients
                if item["id"] == tax_return["client_id"]
            ),
            None,
        )
        if not client:
            continue

        display_status, status_class = tax_return_status(tax_return)

        if tax_return.get("approval_status") == "APPROVED":
            tax_ready_to_lodge_count += 1
            attention_items.append(
                {
                    "type": "tax",
                    "type_label": "Tax Return",
                    "client": client,
                    "title": "Annual tax return ready to lodge",
                    "detail": f"FY {tax_return['financial_year']}",
                    "status": "Ready to lodge",
                    "status_class": status_class,
                    "url": url_for(
                        "tax.company_tax_return",
                        client_id=client["id"],
                        tax_return_id=tax_return["id"],
                    ),
                    "priority": 3,
                }
            )
        elif tax_return.get("review_status") == "REVIEW REQUIRED":
            tax_review_required_count += 1
            attention_items.append(
                {
                    "type": "tax",
                    "type_label": "Tax Return",
                    "client": client,
                    "title": "Annual tax return review required",
                    "detail": f"FY {tax_return['financial_year']}",
                    "status": display_status,
                    "status_class": status_class,
                    "url": url_for(
                        "tax.company_tax_return",
                        client_id=client["id"],
                        tax_return_id=tax_return["id"],
                    ),
                    "priority": 2,
                }
            )

    attention_items.sort(
        key=lambda item: (
            item["priority"],
            item["client"]["company_name"].lower(),
            item["type"],
        )
    )

    attention_counts = {
        "all": len(attention_items),
        "client": sum(
            1 for item in attention_items if item["type"] == "client"
        ),
        "bas": sum(
            1 for item in attention_items if item["type"] == "bas"
        ),
        "tax": sum(
            1 for item in attention_items if item["type"] == "tax"
        ),
    }

    return render_template(
        "dashboard.html",
        firm=firm,
        current_financial_year=current_fy,
        total_clients=len(clients),
        qbo_connected_count=qbo_connected_count,
        qbo_attention_count=qbo_attention_count,
        bas_in_progress_count=bas_in_progress_count,
        bas_review_required_count=bas_review_required_count,
        bas_ready_to_lodge_count=bas_ready_to_lodge_count,
        bas_lodged_this_fy_count=bas_lodged_this_fy_count,
        tax_in_progress_count=tax_in_progress_count,
        tax_review_required_count=tax_review_required_count,
        tax_ready_to_lodge_count=tax_ready_to_lodge_count,
        tax_lodged_this_fy_count=tax_lodged_this_fy_count,
        attention_items=attention_items[:25],
        attention_counts=attention_counts,
    )


@bas_bp.route("/clients/<int:client_id>/bas")
def client_dashboard(client_id):
    return redirect(url_for("clients.business_details", client_id=client_id))


@bas_bp.route("/clients/<int:client_id>/active-bas")
def active_bas(client_id):
    client = get_client_for_user(client_id, g.user["id"])

    if not client:
        return redirect(url_for("clients.index"))

    session["client_id"] = client_id
    g.client = client

    if not client.get("qbo_connected"):
        return redirect(
            url_for("clients.quickbooks_client", client_id=client_id)
        )

    records = [
        _decorate_record(record)
        for record in get_history(client_id, limit=100)
    ]
    current_records = [
        record
        for record in records
        if not record["is_lodged"]
    ]

    return render_template(
        "client_active_bas.html",
        client=client,
        current_records=current_records,
        mock_ato_lodgement_enabled=ENABLE_MOCK_ATO_LODGEMENT,
    )


@bas_bp.route("/clients/<int:client_id>/historical-bas")
def historical_bas(client_id):
    client = get_client_for_user(client_id, g.user["id"])

    if not client:
        return redirect(url_for("clients.index"))

    session["client_id"] = client_id
    g.client = client

    records = [
        _decorate_record(record)
        for record in get_history(client_id, limit=500)
    ]
    all_historical_records = [
        record
        for record in records
        if record["is_lodged"]
    ]

    financial_years = sorted(
        {record["financial_year"] for record in all_historical_records},
        key=financial_year_sort_key,
        reverse=True,
    )

    selected_year = request.args.get("year", "").strip()
    if selected_year not in financial_years:
        selected_year = financial_years[0] if financial_years else None

    historical_records = [
        record
        for record in all_historical_records
        if not selected_year or record["financial_year"] == selected_year
    ]

    year_counts = {
        financial_year: sum(
            1
            for record in all_historical_records
            if record["financial_year"] == financial_year
        )
        for financial_year in financial_years
    }

    return render_template(
        "client_historical_bas.html",
        client=client,
        historical_records=historical_records,
        financial_years=financial_years,
        selected_year=selected_year,
        year_counts=year_counts,
    )


@bas_bp.route("/calculate-bas", methods=["POST"])
def calculate_new_bas():
    client, response = _require_client()
    if response:
        return response

    client_id = client["id"]
    start = request.form.get("start", "").strip()
    end = request.form.get("end", "").strip()

    try:
        start_date = datetime.strptime(start, "%Y-%m-%d")
        end_date = datetime.strptime(end, "%Y-%m-%d")
    except ValueError:
        return render_template(
            "message.html",
            title="Invalid BAS dates",
            message="Enter a valid start date and end date.",
            back_url=url_for("bas.active_bas", client_id=client["id"]),
        ), 400

    if start_date > end_date:
        return render_template(
            "message.html",
            title="Invalid BAS period",
            message="The BAS start date must be before or the same as the end date.",
            back_url=url_for("bas.active_bas", client_id=client["id"]),
        ), 400

    matching_record = _record_for_period(client_id, start, end)

    if matching_record:
        if matching_record["is_lodged"]:
            return render_template(
                "message.html",
                title="BAS already lodged",
                message=(
                    "A BAS for this reporting period has already been lodged "
                    "and is available under BAS History."
                ),
                back_url=url_for("bas.active_bas", client_id=client["id"]),
            )

        return render_template(
            "message.html",
            title="BAS already calculated",
            message=(
                "A BAS for this reporting period has already been calculated "
                "and is listed under Active BAS."
            ),
            back_url=url_for("bas.active_bas", client_id=client["id"]),
        )

    return redirect(url_for("bas.bas_review", start=start, end=end))


@bas_bp.route("/bas-history")
def bas_history():
    session.pop("client_id", None)
    g.client = None

    records = [
        _decorate_record(record)
        for record in get_history_for_user(g.user["id"], limit=250)
    ]
    return render_template("bas_history.html", records=records)


@bas_bp.route("/bas-history/<int:record_id>")
def bas_history_detail(record_id):
    record = get_record_for_user(g.user["id"], record_id)

    if not record:
        return render_template(
            "message.html",
            title="BAS record not found",
            message="The requested BAS history record could not be found.",
            back_url=url_for("bas.bas_history"),
        ), 404

    client = get_client_for_user(record["client_id"], g.user["id"])
    if not client:
        return render_template(
            "message.html",
            title="Client not found",
            message="The client associated with this BAS record could not be found.",
            back_url=url_for("bas.bas_history"),
        ), 404

    if request.args.get("client_context") == "1":
        session["client_id"] = client["id"]
        g.client = client
    else:
        session.pop("client_id", None)
        g.client = None

    review_text = record.get("review_text") or ""
    cleaned_review = re.sub(
        r"REVIEW_STATUS:\s*(PASS|WARNING|REVIEW REQUIRED)",
        "",
        review_text,
    ).strip()

    review_html = (
        markdown.markdown(cleaned_review, extensions=["tables"])
        if cleaned_review
        else None
    )

    return render_template(
        "bas_history_detail.html",
        record=_decorate_record(record),
        review_html=review_html,
        client=client,
    )


@bas_bp.route("/bas-summary")
def bas_summary():
    client, response = _require_client()
    if response:
        return response

    start, end = _period_from_request()
    bas = calculate_bas(client["id"], start, end)
    _persist_bas(client["id"], bas)
    return bas_summary_payload(bas)


@bas_bp.route("/payroll-bas")
def payroll_bas():
    client, response = _require_client()
    if response:
        return response

    start, end = _period_from_request()
    return get_payroll_bas(client["id"], start, end)


@bas_bp.route("/bas-review")
def bas_review():
    client, response = _require_client()
    if response:
        return response

    client_id = client["id"]
    start, end = _period_from_request()

    lodged_response = _lodged_period_response(client, start, end)
    if lodged_response:
        return lodged_response

    bas = calculate_bas(client_id, start, end)
    signature, bas_record = _persist_bas(client_id, bas)

    ai_review = load_ai_review(client_id, start, end, signature)
    ai_status = ai_review["status"] if ai_review else "NOT REVIEWED"
    review_resolved = bool(
        ai_review and ai_review.get("resolution_status") == "RESOLVED"
    )

    return render_template(
        "bas_review.html",
        bas=bas,
        client=client,
        ai_status=ai_status,
        ai_review=ai_review,
        review_resolved=review_resolved,
        bas_record=bas_record,
        **_amount_display_data(bas["payable"]),
    )


@bas_bp.route("/ai-review")
def ai_review():
    client, response = _require_client()
    if response:
        return response

    client_id = client["id"]
    start, end = _period_from_request()

    lodged_response = _lodged_period_response(client, start, end)
    if lodged_response:
        return lodged_response

    bas = calculate_bas(client_id, start, end)
    signature, _ = _persist_bas(client_id, bas)

    result = run_ai_review(bas)

    save_ai_review(
        client_id,
        start,
        end,
        result["status"],
        signature,
        review_text=result["review_text"],
    )

    cleaned_review = re.sub(
        r"REVIEW_STATUS:\s*(PASS|WARNING|REVIEW REQUIRED)",
        "",
        result["review_text"],
    ).strip()

    review_html = markdown.markdown(cleaned_review, extensions=["tables"])

    return render_template(
        "ai_review.html",
        bas=bas,
        client=client,
        review_html=review_html,
        status=result["status"],
        status_title=result["title"],
        status_message=result["message"],
        status_class=result["css_class"],
    )


@bas_bp.route("/review-details")
def review_details():
    client, response = _require_client()
    if response:
        return response

    client_id = client["id"]
    start, end = _period_from_request()

    lodged_response = _lodged_period_response(client, start, end)
    if lodged_response:
        return lodged_response

    bas = calculate_bas(client_id, start, end)
    signature, _ = _persist_bas(client_id, bas)
    review = load_ai_review(client_id, start, end, signature)

    if not review:
        return redirect(url_for("bas.bas_review", start=start, end=end))

    cleaned_review = re.sub(
        r"REVIEW_STATUS:\s*(PASS|WARNING|REVIEW REQUIRED)",
        "",
        review.get("review_text", ""),
    ).strip()

    status = review.get("status", "WARNING")

    if status == "REVIEW REQUIRED":
        status_title = "These items need your decision"
        status_message = (
            "Review each flagged item below. Correct it in QuickBooks if it "
            "is wrong, or record why no change is needed."
        )
        status_class = "review"
    elif status == "WARNING":
        status_title = "A few things are worth checking"
        status_message = "Review these items before approving your BAS."
        status_class = "warning"
    else:
        status_title = "No significant problems found"
        status_message = "No material BAS issues were identified."
        status_class = "pass"

    return render_template(
        "ai_review.html",
        bas=bas,
        client=client,
        review_html=markdown.markdown(cleaned_review, extensions=["tables"]),
        status=status,
        status_title=status_title,
        status_message=status_message,
        status_class=status_class,
        saved_review=review,
    )


@bas_bp.route("/resolve-review", methods=["POST"])
def resolve_review():
    client, response = _require_client()
    if response:
        return response

    client_id = client["id"]
    start, end = _period_from_request()

    lodged_response = _lodged_period_response(client, start, end)
    if lodged_response:
        return lodged_response

    bas = calculate_bas(client_id, start, end)
    signature, _ = _persist_bas(client_id, bas)
    review = load_ai_review(client_id, start, end, signature)

    if not review or review.get("status") != "REVIEW REQUIRED":
        return redirect(url_for("bas.bas_review", start=start, end=end))

    if request.form.get("confirm_reviewed") != "yes":
        return render_template(
            "message.html",
            title="Confirmation required",
            message="Confirm that you reviewed the flagged items before continuing.",
            back_url=f"/bas-review?start={start}&end={end}",
        ), 400

    resolution_note = request.form.get("resolution_note", "").strip()

    if not resolution_note:
        return render_template(
            "message.html",
            title="Resolution note required",
            message="Briefly record why no BAS change is required.",
            back_url=f"/bas-review?start={start}&end={end}",
        ), 400

    resolve_ai_review(
        client_id,
        start,
        end,
        signature,
        resolution_note,
    )
    return redirect(url_for("bas.bas_review", start=start, end=end))


@bas_bp.route("/approve-bas", methods=["POST"])
def approve_bas():
    client, response = _require_client()
    if response:
        return response

    client_id = client["id"]
    start, end = _period_from_request()

    lodged_response = _lodged_period_response(client, start, end)
    if lodged_response:
        return lodged_response

    bas = calculate_bas(client_id, start, end)
    signature, _ = _persist_bas(client_id, bas)
    review = load_ai_review(client_id, start, end, signature)

    if not review:
        return render_template(
            "message.html",
            title="Approval blocked",
            message="You must run the AI review first.",
            back_url=f"/bas-review?start={start}&end={end}",
        ), 400

    status = review["status"]

    if (
        status == "REVIEW REQUIRED"
        and review.get("resolution_status") != "RESOLVED"
    ):
        return render_template(
            "message.html",
            title="Approval blocked",
            message="Review and resolve the flagged items before approving this BAS.",
            back_url=f"/bas-review?start={start}&end={end}",
        ), 400

    if status == "WARNING" and request.form.get("acknowledge_warning") != "yes":
        return render_template(
            "message.html",
            title="Approval blocked",
            message="Please acknowledge the AI warnings first.",
            back_url=f"/bas-review?start={start}&end={end}",
        ), 400

    approval_status = status
    if status == "REVIEW REQUIRED":
        approval_status = "REVIEW REQUIRED - HUMAN RESOLVED"

    save_approval(
        client_id,
        start,
        end,
        approval_status,
        signature,
    )

    return render_template(
        "message.html",
        title="BAS Approved",
        message=(
            "Your approval has been recorded. The BAS has not been "
            "lodged with the ATO yet. Status: Ready to Lodge."
        ),
        back_url=url_for("bas.active_bas", client_id=client["id"]),
    )


@bas_bp.route("/reopen-bas", methods=["POST"])
def reopen_approved_bas():
    client, response = _require_client()
    if response:
        return response

    start = request.form.get("start", "").strip()
    end = request.form.get("end", "").strip()
    signature = request.form.get("signature", "").strip()

    record = _record_for_period(client["id"], start, end)

    if not record or record.get("signature") != signature:
        return render_template(
            "message.html",
            title="BAS record not found",
            message="The BAS selected for editing could not be found.",
            back_url=url_for("bas.active_bas", client_id=client["id"]),
        ), 404

    if record["is_lodged"]:
        return redirect(
            url_for(
                "bas.bas_history_detail",
                record_id=record["id"],
                client_context=1,
            )
        )

    if record.get("approval_status") != "APPROVED":
        return redirect(
            url_for(
                "bas.bas_review",
                start=start,
                end=end,
            )
        )

    reopened = reopen_bas(
        client["id"],
        start,
        end,
        signature,
    )

    if not reopened or reopened.get("approval_status") == "APPROVED":
        return render_template(
            "message.html",
            title="BAS could not be reopened",
            message="The BAS approval could not be cleared for editing.",
            back_url=url_for("bas.active_bas", client_id=client["id"]),
        ), 400

    return redirect(
        url_for(
            "bas.bas_review",
            start=start,
            end=end,
        )
    )


@bas_bp.route("/mock-lodge-bas", methods=["POST"])
def mock_lodge_bas():
    if not ENABLE_MOCK_ATO_LODGEMENT:
        return render_template(
            "message.html",
            title="Mock lodgement disabled",
            message=(
                "Mock ATO lodgement is disabled. Set "
                "ENABLE_MOCK_ATO_LODGEMENT=true in the local environment to use it."
            ),
            back_url=url_for("bas.dashboard"),
        ), 404

    client, response = _require_client()
    if response:
        return response

    start = request.form.get("start", "").strip()
    end = request.form.get("end", "").strip()
    signature = request.form.get("signature", "").strip()

    record = _record_for_period(client["id"], start, end)

    if not record or record.get("signature") != signature:
        return render_template(
            "message.html",
            title="BAS record not found",
            message="The BAS selected for mock lodgement could not be found.",
            back_url=url_for("bas.active_bas", client_id=client["id"]),
        ), 404

    if record["is_lodged"]:
        return redirect(
            url_for(
                "bas.historical_bas",
                client_id=client["id"],
                year=record["financial_year"],
            )
        )

    if record.get("approval_status") != "APPROVED":
        return render_template(
            "message.html",
            title="BAS is not ready to lodge",
            message=(
                "Approve the BAS first. Mock lodgement is only available for "
                "BAS records with status Approved - Ready to Lodge."
            ),
            back_url=url_for("bas.active_bas", client_id=client["id"]),
        ), 400

    mock_reference = (
        f"MOCK-BAS-{client['id']}-"
        f"{datetime.now().strftime('%Y%m%d%H%M%S')}"
    )

    lodged = mark_lodged(
        client["id"],
        start,
        end,
        signature,
        lodgement_reference=mock_reference,
    )

    if not lodged or not lodged.get("lodged_at"):
        return render_template(
            "message.html",
            title="Mock lodgement failed",
            message="The BAS could not be marked as lodged.",
            back_url=url_for("bas.active_bas", client_id=client["id"]),
        ), 500

    return redirect(
        url_for(
            "bas.historical_bas",
            client_id=client["id"],
            year=financial_year_for_date(end),
        )
    )


@bas_bp.route("/reject-bas", methods=["POST"])
def reject_bas():
    client, response = _require_client()
    if response:
        return response

    client_id = client["id"]
    start, end = _period_from_request()

    lodged_response = _lodged_period_response(client, start, end)
    if lodged_response:
        return lodged_response

    bas = calculate_bas(client_id, start, end)
    signature, _ = _persist_bas(client_id, bas)

    save_rejection(client_id, start, end, signature)

    return render_template(
        "message.html",
        title="BAS Rejected",
        message="The BAS has been marked as rejected.",
        back_url=url_for("bas.active_bas", client_id=client["id"]),
    )
