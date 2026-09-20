from flask import Blueprint, g, redirect, render_template, request, session, url_for

from services.database import (
    claim_legacy_bas_records,
    create_client,
    get_client_for_user,
    get_clients_for_user,
    get_qbo_connection,
    update_client,
)

clients_bp = Blueprint("clients", __name__, url_prefix="/clients")


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

        if not values["company_name"]:
            error = "Enter the client's company or business name."
        else:
            existing_clients = get_clients_for_user(g.user["id"])
            client = create_client(
                g.user["id"],
                values["company_name"],
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
            return redirect(url_for("clients.client_home", client_id=client["id"]))

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

        if not values["company_name"]:
            error = "Enter the client's company or business name."
        elif values["email"] and "@" not in values["email"]:
            error = "Enter a valid client email address."
        else:
            update_client(
                client_id,
                g.user["id"],
                company_name=values["company_name"],
                legal_name=values["legal_name"],
                abn=values["abn"],
                acn=values["acn"],
                address=values["address"],
                email=values["email"],
                phone=values["phone"],
            )
            session["client_id"] = client_id
            return redirect(url_for("clients.client_home", client_id=client_id))

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

    session["client_id"] = client_id
    g.client = client

    if not client.get("qbo_connected"):
        return render_template("client_setup.html", client=client)

    return redirect(url_for("bas.client_dashboard", client_id=client_id))


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
    return redirect(url_for("clients.client_home", client_id=client_id))
