from flask import Blueprint, g, redirect, render_template, request, session, url_for
from werkzeug.security import check_password_hash, generate_password_hash

from services.database import (
    create_user,
    get_client_for_user,
    get_firm_for_user,
    get_user_by_email,
    get_user_by_id,
    update_firm_for_user,
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
        "firm_name": "",
        "director_name": "",
        "firm_abn": "",
        "firm_acn": "",
        "firm_address": "",
        "firm_phone": "",
        "first_name": "",
        "last_name": "",
        "email": "",
    }

    if request.method == "POST":
        values = {
            "firm_name": request.form.get("firm_name", "").strip(),
            "director_name": request.form.get("director_name", "").strip(),
            "firm_abn": request.form.get("firm_abn", "").strip(),
            "firm_acn": request.form.get("firm_acn", "").strip(),
            "firm_address": request.form.get("firm_address", "").strip(),
            "firm_phone": request.form.get("firm_phone", "").strip(),
            "first_name": request.form.get("first_name", "").strip(),
            "last_name": request.form.get("last_name", "").strip(),
            "email": request.form.get("email", "").strip().lower(),
        }
        password = request.form.get("password", "")
        confirm_password = request.form.get("confirm_password", "")

        if not values["firm_name"]:
            error = "Enter the accounting firm name."
        elif not values["director_name"]:
            error = "Enter the director or principal name."
        elif not values["first_name"] or not values["last_name"]:
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
                values["firm_name"],
                values["director_name"],
                firm_abn=values["firm_abn"],
                firm_acn=values["firm_acn"],
                firm_address=values["firm_address"],
                firm_email=values["email"],
                firm_phone=values["firm_phone"],
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


@auth_bp.route("/firm-profile", methods=["GET", "POST"])
def firm_profile():
    if g.user is None:
        return redirect(url_for("auth.login"))

    firm = get_firm_for_user(g.user["id"])
    values = {
        "firm_name": (firm or {}).get("firm_name") or "",
        "director_name": (firm or {}).get("director_name") or "",
        "abn": (firm or {}).get("abn") or "",
        "acn": (firm or {}).get("acn") or "",
        "address": (firm or {}).get("address") or "",
        "email": (firm or {}).get("email") or g.user.get("email", ""),
        "phone": (firm or {}).get("phone") or "",
    }
    error = None

    if request.method == "POST":
        values = {
            "firm_name": request.form.get("firm_name", "").strip(),
            "director_name": request.form.get("director_name", "").strip(),
            "abn": request.form.get("abn", "").strip(),
            "acn": request.form.get("acn", "").strip(),
            "address": request.form.get("address", "").strip(),
            "email": request.form.get("email", "").strip().lower(),
            "phone": request.form.get("phone", "").strip(),
        }

        if not values["firm_name"]:
            error = "Enter the accounting firm name."
        elif not values["director_name"]:
            error = "Enter the director or principal name."
        else:
            update_firm_for_user(
                g.user["id"],
                values["firm_name"],
                values["director_name"],
                abn=values["abn"],
                acn=values["acn"],
                address=values["address"],
                email=values["email"],
                phone=values["phone"],
            )
            return redirect(url_for("clients.index"))

    return render_template(
        "firm_profile.html",
        values=values,
        error=error,
    )


@auth_bp.route("/logout", methods=["POST"])
def logout():
    session.clear()
    return redirect(url_for("auth.login"))
