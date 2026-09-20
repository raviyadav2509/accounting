from flask import Blueprint, g, redirect, render_template, request, session, url_for
from werkzeug.security import check_password_hash, generate_password_hash

from services.database import (
    create_user,
    get_client_for_user,
    get_user_by_email,
    get_user_by_id,
    update_last_login,
)

auth_bp = Blueprint("auth", __name__)


@auth_bp.before_app_request
def load_logged_in_user():
    user_id = session.get("user_id")
    g.user = get_user_by_id(user_id) if user_id else None
    g.client = None

    if g.user and session.get("client_id"):
        g.client = get_client_for_user(
            session.get("client_id"),
            g.user["id"],
        )

        if g.client is None:
            session.pop("client_id", None)


@auth_bp.before_app_request
def require_login():
    if request.endpoint is None:
        return None

    if request.endpoint == "static" or request.blueprint == "auth":
        return None

    if g.user is None:
        return redirect(url_for("auth.login"))

    return None


@auth_bp.route("/login", methods=["GET", "POST"])
def login():
    if g.user is not None:
        return redirect(url_for("clients.index"))

    error = None
    email = ""

    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")

        user = get_user_by_email(email)

        if not user or not user.get("is_active"):
            error = "The email or password is incorrect."
        elif not check_password_hash(user["password_hash"], password):
            error = "The email or password is incorrect."
        else:
            session.clear()
            session["user_id"] = user["id"]
            update_last_login(user["id"])
            return redirect(url_for("clients.index"))

    return render_template(
        "login.html",
        error=error,
        email=email,
    )


@auth_bp.route("/signup", methods=["GET", "POST"])
def signup():
    if g.user is not None:
        return redirect(url_for("clients.index"))

    error = None
    values = {
        "first_name": "",
        "last_name": "",
        "email": "",
    }

    if request.method == "POST":
        values = {
            "first_name": request.form.get("first_name", "").strip(),
            "last_name": request.form.get("last_name", "").strip(),
            "email": request.form.get("email", "").strip().lower(),
        }
        password = request.form.get("password", "")
        confirm_password = request.form.get("confirm_password", "")

        if not values["first_name"] or not values["last_name"]:
            error = "Enter your first and last name."
        elif not values["email"] or "@" not in values["email"]:
            error = "Enter a valid email address."
        elif len(password) < 8:
            error = "Password must be at least 8 characters."
        elif password != confirm_password:
            error = "The passwords do not match."
        elif get_user_by_email(values["email"]):
            error = "An account with this email already exists."
        else:
            user = create_user(
                values["first_name"],
                values["last_name"],
                values["email"],
                generate_password_hash(password),
            )

            if user is None:
                error = "An account with this email already exists."
            else:
                session.clear()
                session["user_id"] = user["id"]
                update_last_login(user["id"])
                return redirect(url_for("clients.index"))

    return render_template(
        "signup.html",
        error=error,
        values=values,
    )


@auth_bp.route("/logout", methods=["POST"])
def logout():
    session.clear()
    return redirect(url_for("auth.login"))
