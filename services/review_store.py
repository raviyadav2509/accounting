import json
import os

from config import REVIEW_FILE
from services.database import (
    get_bas_record,
    mark_approved,
    mark_rejected,
    resolve_review,
    update_review,
)


def _review_from_record(record):
    if not record or not record.get("review_status"):
        return None

    return {
        "start": record["start_date"],
        "end": record["end_date"],
        "status": record["review_status"],
        "signature": record["signature"],
        "reviewed_at": record.get("reviewed_at"),
        "review_text": record.get("review_text"),
        "resolution_status": record.get("resolution_status"),
        "resolution_note": record.get("resolution_note"),
        "resolved_at": record.get("resolved_at"),
    }


def save_ai_review(start, end, status, signature, review_text=None):
    record = update_review(
        start,
        end,
        signature,
        status,
        review_text or "",
    )
    return _review_from_record(record)


def load_ai_review(start, end, signature):
    record = get_bas_record(start, end, signature)
    review = _review_from_record(record)

    if review:
        return review

    # One-time compatibility with the earlier JSON-based implementation.
    if not os.path.exists(REVIEW_FILE):
        return None

    with open(REVIEW_FILE, "r") as f:
        legacy = json.load(f)

    if legacy.get("start") != start or legacy.get("end") != end:
        return None

    if legacy.get("signature") != signature:
        return None

    record = update_review(
        start,
        end,
        signature,
        legacy.get("status", "WARNING"),
        legacy.get("review_text", ""),
    )

    if legacy.get("resolution_status") == "RESOLVED":
        record = resolve_review(
            start,
            end,
            signature,
            legacy.get("resolution_note", "Resolved in previous version."),
        )

    return _review_from_record(record)


def save_approval(start, end, ai_status, signature):
    record = mark_approved(start, end, signature, ai_status)

    return {
        "status": "APPROVED",
        "start": start,
        "end": end,
        "ai_status": ai_status,
        "approved_at": record.get("approved_at") if record else None,
        "signature": signature,
    }


def save_rejection(start, end, signature):
    record = mark_rejected(start, end, signature)

    return {
        "status": "REJECTED",
        "start": start,
        "end": end,
        "rejected_at": record.get("rejected_at") if record else None,
        "signature": signature,
    }


def resolve_ai_review(start, end, signature, resolution_note):
    record = resolve_review(start, end, signature, resolution_note)
    return _review_from_record(record)
