import json
import os
from datetime import datetime

from config import APPROVAL_FILE, REVIEW_FILE


def save_ai_review(start, end, status, signature, review_text=None):
    data = {
        "start": start,
        "end": end,
        "status": status,
        "signature": signature,
        "reviewed_at": datetime.now().isoformat(),
    }
    if review_text is not None:
        data["review_text"] = review_text

    with open(REVIEW_FILE, "w") as f:
        json.dump(data, f, indent=2)

    return data


def load_ai_review(start, end, signature):
    if not os.path.exists(REVIEW_FILE):
        return None

    with open(REVIEW_FILE, "r") as f:
        data = json.load(f)

    if data.get("start") != start or data.get("end") != end:
        return None

    if data.get("signature") != signature:
        return None

    return data


def save_approval(start, end, ai_status, signature):
    approval = {
        "status": "APPROVED",
        "start": start,
        "end": end,
        "ai_status": ai_status,
        "approved_at": datetime.now().isoformat(),
        "signature": signature,
    }

    with open(APPROVAL_FILE, "w") as f:
        json.dump(approval, f, indent=2)

    return approval


def save_rejection(start, end):
    rejection = {
        "status": "REJECTED",
        "start": start,
        "end": end,
        "rejected_at": datetime.now().isoformat(),
    }

    with open(APPROVAL_FILE, "w") as f:
        json.dump(rejection, f, indent=2)

    return rejection


def resolve_ai_review(start, end, signature, resolution_note):
    review = load_ai_review(start, end, signature)
    if not review:
        return None

    review["resolution_status"] = "RESOLVED"
    review["resolution_note"] = resolution_note.strip()
    review["resolved_at"] = datetime.now().isoformat()

    with open(REVIEW_FILE, "w") as f:
        json.dump(review, f, indent=2)

    return review
