import re
from datetime import datetime

import markdown
from flask import Blueprint, g, redirect, render_template, request, session, url_for

from config import DEFAULT_BAS_END, DEFAULT_BAS_START
from services.ai_review_service import run_ai_review
from services.bas_service import (
    bas_signature,
    bas_summary_payload,
    calculate_bas,
    get_payroll_bas,
)
from services.database import (
    get_client_for_user,
    get_firm_for_user,
    get_history,
    get_history_for_user,
    get_record_by_id,
    get_record_for_user,
    save_bas_snapshot,
)
from services.review_store import (
    load_ai_review,
    resolve_ai_review,
    save_ai_review,
    save_approval,
    save_rejection,
)

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
            url_for("clients.client_home", client_id=client["id"])
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
            url_for("bas.bas_history_detail", record_id=record["id"])
        )
    return None


@bas_bp.route("/")
def dashboard():
    session.pop("client_id", None)
    g.client = None
    firm = get_firm_for_user(g.user["id"])

    clients = list(g.clients)
    active_bas_count = 0
    review_required_count = 0
    ready_to_lodge_count = 0
    qbo_attention_count = 0
    attention_items = []

    for client in clients:
        if not client.get("qbo_connected"):
            qbo_attention_count += 1
            attention_items.append(
                {
                    "client": client,
                    "title": "Connect QuickBooks",
                    "detail": "Accounting data is not connected for this client.",
                    "status": "Connection required",
                    "status_class": "warning",
                    "url": url_for("clients.client_home", client_id=client["id"]),
                }
            )

        records = [
            _decorate_record(record)
            for record in get_history(client["id"], limit=100)
        ]
        active_records = [
            record
            for record in records
            if not record["is_lodged"]
        ]
        active_bas_count += len(active_records)

        for record in active_records:
            if record.get("approval_status") == "APPROVED":
                ready_to_lodge_count += 1
                attention_items.append(
                    {
                        "client": client,
                        "title": "BAS ready to lodge",
                        "detail": record["period_display"],
                        "status": "Ready to lodge",
                        "status_class": "approved",
                        "url": url_for(
                            "bas.client_dashboard",
                            client_id=client["id"],
                        ),
                    }
                )
            elif (
                record.get("review_status") == "REVIEW REQUIRED"
                and record.get("resolution_status") != "RESOLVED"
            ):
                review_required_count += 1
                attention_items.append(
                    {
                        "client": client,
                        "title": "BAS review required",
                        "detail": record["period_display"],
                        "status": "Review required",
                        "status_class": "review-required",
                        "url": url_for(
                            "bas.client_dashboard",
                            client_id=client["id"],
                        ),
                    }
                )

    return render_template(
        "dashboard.html",
        firm=firm,
        total_clients=len(clients),
        active_bas_count=active_bas_count,
        review_required_count=review_required_count,
        ready_to_lodge_count=ready_to_lodge_count,
        qbo_attention_count=qbo_attention_count,
        attention_items=attention_items[:8],
    )


@bas_bp.route("/clients/<int:client_id>/bas")
def client_dashboard(client_id):
    client = get_client_for_user(client_id, g.user["id"])

    if not client:
        return redirect(url_for("clients.index"))

    session["client_id"] = client_id

    if not client.get("qbo_connected"):
        return redirect(
            url_for("clients.client_home", client_id=client_id)
        )

    bas = calculate_bas(client_id, DEFAULT_BAS_START, DEFAULT_BAS_END)
    signature, current_record = _persist_bas(client_id, bas)

    ai_review = load_ai_review(
        client_id,
        bas["start"],
        bas["end"],
        signature,
    )
    ai_status = ai_review["status"] if ai_review else "NOT REVIEWED"
    review_resolved = bool(
        ai_review and ai_review.get("resolution_status") == "RESOLVED"
    )

    current_display = _decorate_record(current_record)
    records = [
        _decorate_record(record)
        for record in get_history(client_id, limit=100)
    ]

    current_records = [
        record
        for record in records
        if not record["is_lodged"]
    ]

    previous = [
        record
        for record in records
        if record["is_lodged"]
    ][:5]

    return render_template(
        "client_dashboard.html",
        bas=bas,
        current=current_display,
        current_records=current_records,
        client=client,
        ai_status=ai_status,
        review_resolved=review_resolved,
        previous=previous,
        **_amount_display_data(bas["payable"]),
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
            back_url=url_for("bas.client_dashboard", client_id=client["id"]),
        ), 400

    if start_date > end_date:
        return render_template(
            "message.html",
            title="Invalid BAS period",
            message="The BAS start date must be before or the same as the end date.",
            back_url=url_for("bas.client_dashboard", client_id=client["id"]),
        ), 400

    matching_record = _record_for_period(client_id, start, end)

    if matching_record:
        if matching_record["is_lodged"]:
            return render_template(
                "message.html",
                title="BAS already lodged",
                message=(
                    "A BAS for this reporting period has already been lodged "
                    "and is available under Previous BAS."
                ),
                back_url=url_for("bas.client_dashboard", client_id=client["id"]),
            )

        return render_template(
            "message.html",
            title="BAS already calculated",
            message=(
                "A BAS for this reporting period has already been calculated "
                "and is listed under Current BAS on the Dashboard."
            ),
            back_url=url_for("bas.client_dashboard", client_id=client["id"]),
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
    session.pop("client_id", None)
    g.client = None

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
    signature, _ = _persist_bas(client_id, bas)

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
        back_url=url_for("bas.client_dashboard", client_id=client["id"]),
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
        back_url=url_for("bas.client_dashboard", client_id=client["id"]),
    )
