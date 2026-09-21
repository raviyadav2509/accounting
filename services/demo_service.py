"""Fictional, per-client transaction fixtures. Never calls external services."""
import json
from datetime import date
from decimal import Decimal

from config import PAYG_ACCOUNT_ID, WAGE_ACCOUNT_ID
from services.database import get_connection, get_client_by_id, get_client_for_user


def is_demo(client):
    return bool(client and client.get("data_source") == "DEMO")


def demo_periods(today=None):
    today = today or date.today()
    year = today.year if today.month >= 7 else today.year - 1
    return {"start": f"{year}-04-01", "end": f"{year}-06-30",
            "financial_year": f"{year - 1}-{year % 100:02d}"}


def _fixtures(scenario, today=None):
    year = int(demo_periods(today)["end"][:4])
    # Last completed and current Australian FY; all dates/transactions fictional.
    for offset in range(24):
        month_index = 6 + offset
        txn_date = f"{year - 1 + month_index // 12}-{month_index % 12 + 1:02d}-15"
        for entity, gross, gst, description in [
            ("Invoice", 11000, 1000, "Consulting services"),
            ("SalesReceipt", 5500, 500, "Training services"),
            ("Bill", 3300, 300, "Office rent"),
            ("Purchase", 1100, 100, "Office supplies"),
        ]:
            payload = {"Id": f"demo-{entity}-{offset}", "TxnDate": txn_date,
                       "TotalAmt": gross, "TxnTaxDetail": {"TotalTax": gst},
                       "PrivateNote": description}
            if entity == "Purchase" and scenario == "review":
                payload["PrivateNote"] = "Mixed-use equipment: confirm business purpose"
                payload["DemoReviewFlag"] = True
            yield entity, payload
        yield "JournalEntry", {
            "Id": f"demo-payroll-{offset}", "TxnDate": txn_date,
            "PrivateNote": "Monthly payroll", "Line": [
                {"Amount": 5000, "JournalEntryLineDetail": {
                    "PostingType": "Debit", "AccountRef": {"value": WAGE_ACCOUNT_ID}}},
                {"Amount": 1000, "JournalEntryLineDetail": {
                    "PostingType": "Credit", "AccountRef": {"value": PAYG_ACCOUNT_ID}}},
                {"Amount": 4000, "JournalEntryLineDetail": {
                    "PostingType": "Credit", "AccountRef": {"value": "demo-bank"}}},
            ],
        }


def _seed(connection, client_id, scenario):
    connection.executemany(
        "INSERT INTO demo_transactions VALUES (?, ?, ?, ?, ?)",
        [(client_id, entity, item["Id"], item["TxnDate"], json.dumps(item))
         for entity, item in _fixtures(scenario)],
    )


def create_demo_client(owner_user_id, scenario):
    if scenario not in {"clean", "review"}:
        raise ValueError("Choose a valid demo scenario.")
    from services.database import _now
    now = _now()
    with get_connection() as connection:
        # Limit accidental repeated creation without changing normal client limits.
        count = connection.execute(
            "SELECT COUNT(*) FROM clients WHERE owner_user_id=? AND data_source='DEMO'",
            (owner_user_id,),
        ).fetchone()[0]
        if count >= 5:
            raise ValueError("You already have five demo clients. Reset one to start again.")
        cursor = connection.execute(
            """INSERT INTO clients
            (owner_user_id, company_name, entity_type, data_source, created_at, updated_at)
            VALUES (?, ?, 'COMPANY', 'DEMO', ?, ?)""",
            (owner_user_id, "Demo - " + ("Clearwater Consulting" if scenario == "clean"
                                        else "Review Practice Company"), now, now),
        )
        client_id = cursor.lastrowid
        _seed(connection, client_id, scenario)
    return get_client_for_user(client_id, owner_user_id)


def reset_demo_client(client_id, owner_user_id, scenario):
    if scenario not in {"clean", "review"}:
        raise ValueError("Choose a valid demo scenario.")
    with get_connection() as connection:
        client = connection.execute(
            "SELECT id FROM clients WHERE id=? AND owner_user_id=? AND data_source='DEMO'",
            (client_id, owner_user_id),
        ).fetchone()
        if not client:
            raise ValueError("Demo client not found.")
        # One transaction; tax adjustments cascade. No other client is touched.
        connection.execute("DELETE FROM bas_records WHERE client_id=?", (client_id,))
        connection.execute("DELETE FROM tax_returns WHERE client_id=?", (client_id,))
        connection.execute("DELETE FROM demo_transactions WHERE client_id=?", (client_id,))
        _seed(connection, client_id, scenario)


def demo_query(client_id, entity, start=None, end=None):
    if not is_demo(get_client_by_id(client_id)):
        raise ValueError("Not a demo client.")
    for value in (start, end):
        if value:
            date.fromisoformat(value)
    if start and end and start > end:
        raise ValueError("Start date must be before end date.")
    with get_connection() as connection:
        rows = connection.execute(
            """SELECT payload FROM demo_transactions
            WHERE client_id=? AND entity=?
            AND (? IS NULL OR transaction_date>=?) AND (? IS NULL OR transaction_date<=?)
            ORDER BY transaction_date, transaction_id""",
            (client_id, entity, start, start, end, end),
        ).fetchall()
    return {"QueryResponse": {entity: [json.loads(row["payload"]) for row in rows]}}


def demo_profit_report(client_id, start, end):
    # Derive P&L from the same transactions as BAS, not a canned final profit.
    profit = Decimal("0")
    for entity in ("Invoice", "SalesReceipt", "Bill", "Purchase"):
        sign = 1 if entity in {"Invoice", "SalesReceipt"} else -1
        for item in demo_query(client_id, entity, start, end)["QueryResponse"][entity]:
            profit += sign * (Decimal(str(item["TotalAmt"]))
                              - Decimal(str(item["TxnTaxDetail"]["TotalTax"])))
    for journal in demo_query(client_id, "JournalEntry", start, end)["QueryResponse"]["JournalEntry"]:
        for line in journal["Line"]:
            detail = line["JournalEntryLineDetail"]
            if detail["AccountRef"]["value"] == WAGE_ACCOUNT_ID:
                profit += (-1 if detail["PostingType"] == "Debit" else 1) * Decimal(str(line["Amount"]))
    return {"Rows": {"Row": [{"ColData": [
        {"value": "Net Income"}, {"value": str(profit)},
    ]}]}}


def demo_review(bas):
    flagged = [item for items in bas["transactions"].values()
               for item in items if item.get("DemoReviewFlag")]
    if flagged:
        return {"status": "REVIEW REQUIRED", "css_class": "review",
                "title": "Simulated review: check business purpose",
                "message": "Resolve the fictional review items before approval.",
                "review_text": "## Simulated demo review (not AI)\n\n"
                "Confirm business use and GST eligibility for these fictional purchases:\n\n"
                + "\n".join(f"- {x['Id']} ({x['TxnDate']}): {x['PrivateNote']}" for x in flagged)
                + "\n\nFor this exercise, record why the expenses are business-related. "
                "No external AI service was called.\n\nREVIEW_STATUS: REVIEW REQUIRED"}
    return {"status": "PASS", "css_class": "pass", "title": "Simulated review complete",
            "message": "Demo scenario passed. Human approval is still required.",
            "review_text": "## Simulated demo review (not AI)\n\n"
            "No seeded review flags in this period. This is a deterministic training result, "
            "not an actual AI or accounting assessment. No external service was called.\n\n"
            "REVIEW_STATUS: PASS"}
