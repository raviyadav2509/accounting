from flask import Blueprint, g, redirect, render_template, request, session, url_for

from services.database import (
    claim_legacy_bas_records,
    create_client,
    get_client_for_user,
    get_clients_for_user,
    get_history,
    get_qbo_connection,
    get_tax_returns_for_client,
    update_client,
)
from services.financial_year_service import financial_year_for_date, financial_year_sort_key
from services.tax_return_service import tax_return_status

clients_bp = Blueprint("clients", __name__, url_prefix="/clients")

ENTITY_TYPES = {
    "COMPANY",
    "TRUST",
    "PARTNERSHIP",
    "INDIVIDUAL",
    "SMSF",
}


def _compliance_summary(client_id):
    years = {}

    for record in get_history(client_id, limit=500):
        financial_year = financial_year_for_date(record["end_date"])
        row = years.setdefault(
            financial_year,
            {
                "financial_year": financial_year,
                "bas_lodged": 0,
                "bas_active": 0,
                "tax_status": "Not started",
                "tax_status_class": "not-reviewed",
                "tax_return_id": None,
            },
        )

        is_lodged = (
            record.get("approval_status") == "LODGED"
            or bool(record.get("lodged_at"))
        )
        if is_lodged:
            row["bas_lodged"] += 1
        else:
            row["bas_active"] += 1

    tax_returns = get_tax_returns_for_client(client_id, limit=100)
    seen_tax_years = set()

    for tax_return in tax_returns:
        financial_year = tax_return["financial_year"]
        row = years.setdefault(
            financial_year,
            {
                "financial_year": financial_year,
                "bas_lodged": 0,
                "bas_active": 0,
                "tax_status": "Not started",
                "tax_status_class": "not-reviewed",
                "tax_return_id": None,
            },
        )

        if financial_year in seen_tax_years:
            continue

        status, status_class = tax_return_status(tax_return)
        row["tax_status"] = status
        row["tax_status_class"] = status_class
        row["tax_return_id"] = tax_return["id"]
        seen_tax_years.add(financial_year)

    return sorted(
        years.values(),
        key=lambda item: financial_year_sort_key(item["financial_year"]),
        reverse=True,
    )[:5]


@clients_bp.route("/")
def index():
    session.pop("client_id", None)
    g.client = None
    clients = get_clients_for_user(g.user["id"])
    active_client_id = None

    return render_template(
        "clients.html",
        clients=clients,
        active_client_id=active_client_id,
    )


@clients_bp.route("/new", methods=["GET", "POST"])
def new_client():
    if request.method == "GET":
        session.pop("client_id", None)
        g.client = None

    error = None
    values = {
        "company_name": "",
        "entity_type": "",
        "legal_name": "",
        "abn": "",
        "acn": "",
        "address": "",
        "email": "",
        "phone": "",
    }

    if request.method == "POST":
        values = {
            key: request.form.get(key, "").strip()
            for key in values
        }

        values["entity_type"] = values["entity_type"].upper()

        if not values["company_name"]:
            error = "Enter the client's company or business name."
        elif values["entity_type"] not in ENTITY_TYPES:
            error = "Select a valid client entity type."
        else:
            existing_clients = get_clients_for_user(g.user["id"])
            client = create_client(
                g.user["id"],
                values["company_name"],
                entity_type=values["entity_type"],
                legal_name=values["legal_name"],
                abn=values["abn"],
                acn=values["acn"],
                address=values["address"],
                email=values["email"],
                phone=values["phone"],
            )

            if not existing_clients:
                claim_legacy_bas_records(client["id"])

            session["client_id"] = client["id"]
            return redirect(url_for("clients.business_details", client_id=client["id"]))

    return render_template(
        "client_new.html",
        error=error,
        values=values,
    )


@clients_bp.route("/<int:client_id>/edit", methods=["GET", "POST"])
def edit_client(client_id):
    client = get_client_for_user(client_id, g.user["id"])
    if not client:
        return redirect(url_for("clients.index"))

    session["client_id"] = client_id
    g.client = client
    error = None
    values = {
        "company_name": client.get("company_name") or "",
        "entity_type": client.get("entity_type") or "UNSPECIFIED",
        "legal_name": client.get("legal_name") or "",
        "abn": client.get("abn") or "",
        "acn": client.get("acn") or "",
        "address": client.get("address") or "",
        "email": client.get("email") or "",
        "phone": client.get("phone") or "",
    }

    if request.method == "POST":
        values = {
            key: request.form.get(key, "").strip()
            for key in values
        }

        values["entity_type"] = values["entity_type"].upper()

        if not values["company_name"]:
            error = "Enter the client's company or business name."
        elif values["entity_type"] not in ENTITY_TYPES:
            error = "Select a valid client entity type."
        elif values["email"] and "@" not in values["email"]:
            error = "Enter a valid client email address."
        else:
            update_client(
                client_id,
                g.user["id"],
                company_name=values["company_name"],
                entity_type=values["entity_type"],
                legal_name=values["legal_name"],
                abn=values["abn"],
                acn=values["acn"],
                address=values["address"],
                email=values["email"],
                phone=values["phone"],
            )
            session["client_id"] = client_id
            return redirect(url_for("clients.business_details", client_id=client_id))

    return render_template(
        "client_edit.html",
        client=client,
        values=values,
        error=error,
    )


@clients_bp.route("/<int:client_id>")
def client_home(client_id):
    client = get_client_for_user(client_id, g.user["id"])
    if not client:
        return redirect(url_for("clients.index"))

    return redirect(url_for("clients.business_details", client_id=client_id))


@clients_bp.route("/<int:client_id>/details")
def business_details(client_id):
    client = get_client_for_user(client_id, g.user["id"])
    if not client:
        return redirect(url_for("clients.index"))

    session["client_id"] = client_id
    g.client = client

    return render_template(
        "client_business_details.html",
        client=client,
        compliance_summary=_compliance_summary(client_id),
    )


@clients_bp.route("/<int:client_id>/quickbooks")
def quickbooks_client(client_id):
    client = get_client_for_user(client_id, g.user["id"])
    if not client:
        return redirect(url_for("clients.index"))

    session["client_id"] = client_id
    g.client = client
    connection = get_qbo_connection(client_id)

    return render_template(
        "client_quickbooks.html",
        client=client,
        connection=connection,
    )


@clients_bp.route("/<int:client_id>/select", methods=["POST"])
def select_client(client_id):
    client = get_client_for_user(client_id, g.user["id"])
    if not client:
        return redirect(url_for("clients.index"))

    session["client_id"] = client_id
    return redirect(url_for("clients.business_details", client_id=client_id))
