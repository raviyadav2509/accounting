import secrets

from flask import Blueprint, abort, g, redirect, render_template, request, session, url_for

from services.database import get_client_for_user
from services.demo_service import create_demo_client, reset_demo_client, is_demo, demo_periods, demo_query

demo_bp = Blueprint("demo", __name__, url_prefix="/demo")


def demo_csrf_token():
    if "demo_csrf_token" not in session:
        session["demo_csrf_token"] = secrets.token_urlsafe(32)
    return session["demo_csrf_token"]


@demo_bp.app_context_processor
def template_helpers():
    return {"demo_csrf_token": demo_csrf_token, "demo_periods": demo_periods}


@demo_bp.before_request
def protect_demo_actions():
    if request.method == "POST":
        supplied = request.form.get("csrf_token", "")
        expected = session.get("demo_csrf_token", "")
        if not expected or not secrets.compare_digest(supplied, expected):
            abort(400, "Invalid form token. Reload the page and try again.")


@demo_bp.route("/new", methods=["GET", "POST"])
def new_demo():
    error = None
    if request.method == "POST":
        try:
            client = create_demo_client(g.user["id"], request.form.get("scenario"))
        except ValueError as exc:
            error = str(exc)
        else:
            session["client_id"] = client["id"]
            return redirect(url_for("demo.demo_client", client_id=client["id"]))
    return render_template("demo_client.html", demo_client=None, error=error)


@demo_bp.route("/<int:client_id>", methods=["GET", "POST"])
def demo_client(client_id):
    client = get_client_for_user(client_id, g.user["id"])
    if not is_demo(client):
        abort(404)
    if request.method == "POST":
        if request.form.get("confirm_reset") != "RESET":
            abort(400, "Type RESET to confirm deletion of this client's demo progress.")
        try:
            reset_demo_client(client_id, g.user["id"], request.form.get("scenario"))
        except ValueError as exc:
            abort(400, str(exc))
        return redirect(url_for("demo.demo_client", client_id=client_id, reset="1"))
    session["client_id"] = client_id
    g.client = client
    period = demo_periods()
    transactions = []
    for entity in ("Invoice", "SalesReceipt", "Bill", "Purchase", "JournalEntry"):
        for item in demo_query(client_id, entity, period["start"], period["end"])["QueryResponse"][entity]:
            transactions.append({**item, "entity": entity})
    return render_template("demo_client.html", demo_client=client, transactions=transactions,
                           period=period, reset_done=request.args.get("reset") == "1")
