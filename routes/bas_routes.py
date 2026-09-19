import re

import markdown
from flask import Blueprint, render_template, request

from config import DEFAULT_BAS_END, DEFAULT_BAS_START
from services.ai_review_service import run_ai_review
from services.bas_service import (
    bas_signature,
    bas_summary_payload,
    calculate_bas,
    get_payroll_bas,
)
from services.review_store import (
    load_ai_review,
    save_ai_review,
    save_approval,
    save_rejection,
)

bas_bp = Blueprint("bas", __name__)


def _period_from_request():
    return (
        request.values.get("start", DEFAULT_BAS_START),
        request.values.get("end", DEFAULT_BAS_END),
    )


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


@bas_bp.route("/bas-summary")
def bas_summary():
    start, end = _period_from_request()
    return bas_summary_payload(calculate_bas(start, end))


@bas_bp.route("/payroll-bas")
def payroll_bas():
    start, end = _period_from_request()
    return get_payroll_bas(start, end)


@bas_bp.route("/bas-review")
def bas_review():
    start, end = _period_from_request()
    bas = calculate_bas(start, end)
    signature = bas_signature(bas)
    ai_review = load_ai_review(start, end, signature)
    ai_status = ai_review["status"] if ai_review else "NOT REVIEWED"

    return render_template(
        "bas_review.html",
        bas=bas,
        ai_status=ai_status,
        **_amount_display_data(bas["payable"]),
    )


@bas_bp.route("/ai-review")
def ai_review():
    start, end = _period_from_request()
    bas = calculate_bas(start, end)
    result = run_ai_review(bas)
    signature = bas_signature(bas)

    save_ai_review(
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
        review_html=review_html,
        status=result["status"],
        status_title=result["title"],
        status_message=result["message"],
        status_class=result["css_class"],
    )


@bas_bp.route("/approve-bas", methods=["POST"])
def approve_bas():
    start, end = _period_from_request()
    bas = calculate_bas(start, end)
    signature = bas_signature(bas)
    review = load_ai_review(start, end, signature)

    if not review:
        return render_template(
            "message.html",
            title="Approval blocked",
            message="You must run the AI review first.",
            back_url=f"/bas-review?start={start}&end={end}",
        ), 400

    status = review["status"]

    if status == "REVIEW REQUIRED":
        return render_template(
            "message.html",
            title="Approval blocked",
            message="Resolve the review items before approving this BAS.",
            back_url=f"/bas-review?start={start}&end={end}",
        ), 400

    if status == "WARNING" and request.form.get("acknowledge_warning") != "yes":
        return render_template(
            "message.html",
            title="Approval blocked",
            message="Please acknowledge the AI warnings first.",
            back_url=f"/bas-review?start={start}&end={end}",
        ), 400

    save_approval(start, end, status, signature)

    return render_template(
        "message.html",
        title="BAS Approved",
        message=(
            "Your approval has been recorded. The BAS has not been "
            "lodged with the ATO yet. Status: Ready to Lodge."
        ),
        back_url=f"/bas-review?start={start}&end={end}",
    )


@bas_bp.route("/reject-bas", methods=["POST"])
def reject_bas():
    start, end = _period_from_request()
    save_rejection(start, end)
    return render_template(
        "message.html",
        title="BAS Rejected",
        message="The BAS has been marked as rejected.",
        back_url=f"/bas-review?start={start}&end={end}",
    )
