import json

from openai import OpenAI

from config import OPENAI_API_KEY



def _build_prompt(bas):
    return f"""
You are reviewing Australian bookkeeping transactions before a BAS is approved.

The business owner is NOT an accountant.
Use very simple English.
Avoid accounting jargon unless you immediately explain what it means.

Period: {bas['start']} to {bas['end']}

These figures were calculated by the accounting engine and are authoritative:

G1 Total Sales: ${bas['g1']:.2f}
1A GST collected: ${bas['gst_sales']:.2f}
1B GST credits: ${bas['gst_purchases']:.2f}
W1 Gross wages: ${bas['w1']:.2f}
W2 PAYG withheld: ${bas['w2']:.2f}
Estimated BAS payable: ${bas['payable']:.2f}

Do NOT recalculate or replace these figures.

Review the underlying transactions for:
- incorrect GST coding
- possible duplicate transactions
- unusual transactions
- possible personal expenses
- inconsistent tax treatment
- missing or suspicious information
- anything that could make the BAS figures wrong

Write the review for a business owner, not an accountant.

Use these headings:

## What I found
Give a short plain-English summary.

## Things you should check
Use a table with:
| Transaction | What looks unusual | Why it matters | What you should do |

Only include genuine review items.

## What looks OK
Briefly explain the important things that appear correct.

## Before you approve
Give a short checklist of any actions the owner should take.

Do not invent facts.
If something cannot be determined from QuickBooks, say so.

At the very end output exactly one of:

REVIEW_STATUS: PASS
REVIEW_STATUS: WARNING
REVIEW_STATUS: REVIEW REQUIRED

Use REVIEW REQUIRED if an issue could materially change the BAS.
Use WARNING when something should be checked but does not currently show that the BAS is wrong.
Use PASS when there are no meaningful issues.

Transactions:
{json.dumps(bas['transactions'])}
"""


def _status_details(review_text):
    if "REVIEW_STATUS: REVIEW REQUIRED" in review_text:
        return {
            "status": "REVIEW REQUIRED",
            "title": "Check these items before approving",
            "message": (
                "AI found something that could affect your BAS. "
                "Review the items below before approving."
            ),
            "css_class": "review",
        }

    if "REVIEW_STATUS: WARNING" in review_text:
        return {
            "status": "WARNING",
            "title": "A few things are worth checking",
            "message": (
                "The BAS calculation looks usable, but there are "
                "some transactions you should review."
            ),
            "css_class": "warning",
        }

    return {
        "status": "PASS",
        "title": "No significant problems found",
        "message": (
            "The AI review did not identify anything that currently "
            "appears likely to change your BAS."
        ),
        "css_class": "pass",
    }


def run_ai_review(bas):
    if not OPENAI_API_KEY:
        raise RuntimeError("Configure OPENAI_API_KEY for connected-client AI reviews.")
    client = OpenAI(api_key=OPENAI_API_KEY)
    response = client.responses.create(
        model="gpt-5.6-terra",
        input=_build_prompt(bas),
    )

    review_text = response.output_text
    result = _status_details(review_text)
    result["review_text"] = review_text
    return result
