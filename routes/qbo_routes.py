import secrets

from flask import Blueprint, g, redirect, request, session, url_for

from config import DEFAULT_BAS_END, DEFAULT_BAS_START
from services.database import get_client_for_user, update_client
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


def _active_client():
    client_id = session.get("client_id")
    client = get_client_for_user(client_id, g.user["id"]) if client_id else None
    return client


def _client_id_or_redirect():
    client = _active_client()
    if not client:
        return None, redirect(url_for("clients.index"))
    return client["id"], None


def _address_text(address):
    if not address:
        return None

    parts = [
        address.get("Line1"),
        address.get("Line2"),
        address.get("Line3"),
        address.get("City"),
        address.get("CountrySubDivisionCode"),
        address.get("PostalCode"),
        address.get("Country"),
    ]
    return ", ".join(str(part).strip() for part in parts if part)


@qbo_bp.route("/connect")
def connect():
    client_id, response = _client_id_or_redirect()
    if response:
        return response

    state = secrets.token_urlsafe(32)
    session["qbo_oauth_state"] = state
    session["qbo_oauth_client_id"] = client_id

    return redirect(build_authorization_url(state))


@qbo_bp.route("/callback")
def callback():
    returned_state = request.args.get("state")
    expected_state = session.pop("qbo_oauth_state", None)
    client_id = session.pop("qbo_oauth_client_id", None)

    if not expected_state or returned_state != expected_state:
        return "Invalid OAuth state.", 400

    if not client_id:
        return redirect(url_for("clients.index"))

    client = get_client_for_user(client_id, g.user["id"])
    if not client:
        return redirect(url_for("clients.index"))

    code = request.args.get("code")
    realm_id = request.args.get("realmId")
    exchange_authorization_code(code, realm_id, client_id)

    company_payload = get_company_info(client_id)
    company = company_payload.get("CompanyInfo", {})

    update_client(
        client_id,
        g.user["id"],
        company_name=company.get("CompanyName") or client["company_name"],
        legal_name=company.get("LegalName") or client.get("legal_name"),
        abn=company.get("TaxIdentifier") or client.get("abn"),
        address=_address_text(
            company.get("CompanyAddr")
            or company.get("LegalAddr")
            or company.get("CustomerCommunicationAddr")
        ) or client.get("address"),
        email=(
            (company.get("CompanyEmailAddr") or {}).get("Address")
            or (company.get("PrimaryEmailAddr") or {}).get("Address")
            or client.get("email")
        ),
        phone=(
            (company.get("PrimaryPhone") or {}).get("FreeFormNumber")
            or client.get("phone")
        ),
    )

    session["client_id"] = client_id
    return redirect(url_for("bas.dashboard"))


@qbo_bp.route("/company")
def company():
    client_id, response = _client_id_or_redirect()
    if response:
        return response
    return get_company_info(client_id)


@qbo_bp.route("/pnl")
def pnl():
    client_id, response = _client_id_or_redirect()
    if response:
        return response
    return get_report(client_id, "ProfitAndLoss", DEFAULT_BAS_START, DEFAULT_BAS_END)


@qbo_bp.route("/taxcodes")
def taxcodes():
    client_id, response = _client_id_or_redirect()
    if response:
        return response
    return get_tax_codes(client_id)


@qbo_bp.route("/transactions")
def transactions():
    client_id, response = _client_id_or_redirect()
    if response:
        return response

    start = request.args.get("start", DEFAULT_BAS_START)
    end = request.args.get("end", DEFAULT_BAS_END)

    return {
        "invoices": query(client_id, "Invoice", start, end),
        "sales_receipts": query(client_id, "SalesReceipt", start, end),
        "bills": query(client_id, "Bill", start, end),
        "purchases": query(client_id, "Purchase", start, end),
    }


@qbo_bp.route("/accounts")
def accounts():
    client_id, response = _client_id_or_redirect()
    if response:
        return response
    return get_accounts(client_id)


@qbo_bp.route("/journals")
def journals():
    client_id, response = _client_id_or_redirect()
    if response:
        return response
    return query(client_id, "JournalEntry", "2026-07-01", "2026-09-30")


@qbo_bp.route("/payroll-accounts")
def payroll_accounts():
    client_id, response = _client_id_or_redirect()
    if response:
        return response

    data = get_accounts(client_id)
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
    client_id, response = _client_id_or_redirect()
    if response:
        return response
    return get_report(client_id, "GeneralLedger", "2026-07-01", "2026-09-30")
