import secrets

from flask import Blueprint, redirect, request, session

from config import DEFAULT_BAS_END, DEFAULT_BAS_START
from services.qbo_service import (
    build_authorization_url,
    exchange_authorization_code,
    get_accounts,
    get_company_info,
    get_report,
    get_tax_codes,
    query,
)

qbo_bp = Blueprint("qbo", __name__)


@qbo_bp.route("/connect")
def connect():
    state = secrets.token_urlsafe(32)
    session["qbo_oauth_state"] = state
    return redirect(build_authorization_url(state))


@qbo_bp.route("/callback")
def callback():
    returned_state = request.args.get("state")
    expected_state = session.pop("qbo_oauth_state", None)

    if not expected_state or returned_state != expected_state:
        return "Invalid OAuth state.", 400

    code = request.args.get("code")
    realm_id = request.args.get("realmId")
    exchange_authorization_code(code, realm_id)
    return f"QuickBooks connected successfully. Realm ID: {realm_id}"


@qbo_bp.route("/company")
def company():
    return get_company_info()


@qbo_bp.route("/pnl")
def pnl():
    return get_report("ProfitAndLoss", DEFAULT_BAS_START, DEFAULT_BAS_END)


@qbo_bp.route("/taxcodes")
def taxcodes():
    return get_tax_codes()


@qbo_bp.route("/transactions")
def transactions():
    start = request.args.get("start", DEFAULT_BAS_START)
    end = request.args.get("end", DEFAULT_BAS_END)
    return {
        "invoices": query("Invoice", start, end),
        "sales_receipts": query("SalesReceipt", start, end),
        "bills": query("Bill", start, end),
        "purchases": query("Purchase", start, end),
    }


@qbo_bp.route("/accounts")
def accounts():
    return get_accounts()


@qbo_bp.route("/journals")
def journals():
    return query("JournalEntry", "2026-07-01", "2026-09-30")


@qbo_bp.route("/payroll-accounts")
def payroll_accounts():
    data = get_accounts()
    keywords = ["wage", "salary", "payg", "payroll", "super", "employee"]
    accounts_data = data.get("QueryResponse", {}).get("Account", [])

    return [
        {
            "id": account.get("Id"),
            "name": account.get("Name"),
            "type": account.get("AccountType"),
        }
        for account in accounts_data
        if any(k in account.get("Name", "").lower() for k in keywords)
    ]


@qbo_bp.route("/payroll-ledger")
def payroll_ledger():
    return get_report("GeneralLedger", "2026-07-01", "2026-09-30")
