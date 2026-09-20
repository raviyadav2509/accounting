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


def save_ai_review(client_id, start, end, status, signature, review_text=None):
    record = update_review(
        client_id,
        start,
        end,
        signature,
        status,
        review_text or "",
    )
    return _review_from_record(record)


def load_ai_review(client_id, start, end, signature):
    record = get_bas_record(client_id, start, end, signature)
    review = _review_from_record(record)

    if review:
        return review

    # Legacy JSON compatibility is intentionally disabled for multi-client mode
    # because the old file was not client-scoped.
    return None


def save_approval(client_id, start, end, ai_status, signature):
    record = mark_approved(client_id, start, end, signature, ai_status)

    return {
        "status": "APPROVED",
        "start": start,
        "end": end,
        "ai_status": ai_status,
        "approved_at": record.get("approved_at") if record else None,
        "signature": signature,
    }


def save_rejection(client_id, start, end, signature):
    record = mark_rejected(client_id, start, end, signature)

    return {
        "status": "REJECTED",
        "start": start,
        "end": end,
        "rejected_at": record.get("rejected_at") if record else None,
        "signature": signature,
    }


def resolve_ai_review(client_id, start, end, signature, resolution_note):
    record = resolve_review(client_id, start, end, signature, resolution_note)
    return _review_from_record(record)
