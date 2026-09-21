from datetime import datetime

from flask import Blueprint, g, redirect, render_template, request, session, url_for
from werkzeug.security import check_password_hash, generate_password_hash

from config import (
    EMAIL_VERIFICATION_DEBUG_LINKS,
    EMAIL_VERIFICATION_EXPIRY_MINUTES,
)
from services.database import (
    create_user,
    get_client_for_user,
    get_clients_for_user,
    get_firm_for_user,
    get_user_by_email,
    get_user_by_id,
    get_user_by_verification_token_hash,
    mark_email_verified,
    set_email_verification,
    update_firm_for_user,
    update_last_login,
    update_unverified_user_email,
)
from services.email_verification_service import (
    create_verification_token,
    email_delivery_configured,
    hash_verification_token,
    send_verification_email,
    verification_expiry,
)

auth_bp = Blueprint("auth", __name__)

PENDING_VERIFICATION_KEY = "pending_verification_user_id"
DEBUG_VERIFICATION_URL_KEY = "debug_verification_url"
RESEND_COOLDOWN_SECONDS = 60


def _valid_email(email):
    if not email or "@" not in email:
        return False

    local, domain = email.rsplit("@", 1)
    return bool(local and "." in domain and not domain.startswith(".") and not domain.endswith("."))


def _pending_user():
    user_id = session.get(PENDING_VERIFICATION_KEY)
    return get_user_by_id(user_id) if user_id else None


def _set_pending_user(user_id):
    session.pop("user_id", None)
    session.pop("client_id", None)
    session[PENDING_VERIFICATION_KEY] = user_id


def _issue_verification(user):
    token = create_verification_token()
    token_hash = hash_verification_token(token)
    expires_at = verification_expiry()

    set_email_verification(
        user["id"],
        token_hash,
        expires_at,
    )

    verification_url = url_for(
        "auth.verify_email",
        token=token,
        _external=True,
    )

    if EMAIL_VERIFICATION_DEBUG_LINKS:
        session[DEBUG_VERIFICATION_URL_KEY] = verification_url
    else:
        session.pop(DEBUG_VERIFICATION_URL_KEY, None)

    if not email_delivery_configured():
        if EMAIL_VERIFICATION_DEBUG_LINKS:
            return True, None

        return False, (
            "Verification email delivery is not configured on this server. "
            "Ask the administrator to configure SMTP, then resend the email."
        )

    try:
        send_verification_email(
            user["email"],
            user.get("first_name"),
            verification_url,
        )
    except Exception:
        if EMAIL_VERIFICATION_DEBUG_LINKS:
            return True, (
                "Email delivery failed, but a local verification link is "
                "available because debug links are enabled."
            )

        return False, (
            "We could not send the verification email. "
            "Please try again shortly."
        )

    return True, None


def _recently_sent(user):
    sent_at = user.get("email_verification_sent_at")
    if not sent_at:
        return False, 0

    try:
        sent_time = datetime.fromisoformat(sent_at)
    except ValueError:
        return False, 0

    elapsed = (datetime.now() - sent_time).total_seconds()
    remaining = int(RESEND_COOLDOWN_SECONDS - elapsed)

    return remaining > 0, max(remaining, 0)


@auth_bp.before_app_request
def load_logged_in_user():
    user_id = session.get("user_id")
    g.user = get_user_by_id(user_id) if user_id else None
    g.client = None
    g.clients = get_clients_for_user(g.user["id"]) if g.user else []

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

    if not g.user.get("email_verified_at"):
        user_id = g.user["id"]
        session.clear()
        session[PENDING_VERIFICATION_KEY] = user_id
        g.user = None
        g.client = None
        g.clients = []
        return redirect(url_for("auth.verify_email_pending"))

    return None


@auth_bp.route("/login", methods=["GET", "POST"])
def login():
    if g.user is not None and g.user.get("email_verified_at"):
        return redirect(url_for("bas.dashboard"))

    error = None
    notice = None
    email = request.args.get("email", "").strip().lower()

    if request.args.get("verified") == "1":
        notice = "Email verified successfully. Sign in to continue."

    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")

        user = get_user_by_email(email)

        if not user or not user.get("is_active"):
            error = "The email or password is incorrect."
        elif not check_password_hash(user["password_hash"], password):
            error = "The email or password is incorrect."
        elif not user.get("email_verified_at"):
            session.clear()
            session[PENDING_VERIFICATION_KEY] = user["id"]
            return redirect(url_for("auth.verify_email_pending"))
        else:
            session.clear()
            session["user_id"] = user["id"]
            update_last_login(user["id"])
            return redirect(url_for("bas.dashboard"))

    return render_template(
        "login.html",
        error=error,
        notice=notice,
        email=email,
    )


@auth_bp.route("/signup", methods=["GET", "POST"])
def signup():
    if g.user is not None and g.user.get("email_verified_at"):
        return redirect(url_for("bas.dashboard"))

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
        elif not _valid_email(values["email"]):
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
                session[PENDING_VERIFICATION_KEY] = user["id"]
                sent, delivery_error = _issue_verification(user)

                if sent:
                    session["verification_notice"] = (
                        f"We sent a verification link to {user['email']}."
                    )

                if delivery_error:
                    session["verification_error"] = delivery_error

                return redirect(url_for("auth.verify_email_pending"))

    return render_template(
        "signup.html",
        error=error,
        values=values,
    )


@auth_bp.route("/verify-email")
def verify_email_pending():
    if g.user is not None and g.user.get("email_verified_at"):
        return redirect(url_for("bas.dashboard"))

    user = _pending_user()
    if not user:
        return redirect(url_for("auth.login"))

    if user.get("email_verified_at"):
        session.pop(PENDING_VERIFICATION_KEY, None)
        return redirect(
            url_for(
                "auth.login",
                verified=1,
                email=user["email"],
            )
        )

    return render_template(
        "verify_email_pending.html",
        user=user,
        notice=session.pop("verification_notice", None),
        error=session.pop("verification_error", None),
        debug_verification_url=(
            session.get(DEBUG_VERIFICATION_URL_KEY)
            if EMAIL_VERIFICATION_DEBUG_LINKS
            else None
        ),
        expiry_minutes=EMAIL_VERIFICATION_EXPIRY_MINUTES,
    )


@auth_bp.route("/verify-email/<token>")
def verify_email(token):
    token_hash = hash_verification_token(token)
    user = get_user_by_verification_token_hash(token_hash)

    if not user:
        return render_template(
            "verify_email_result.html",
            success=False,
            title="Verification link is invalid",
            message=(
                "This verification link is invalid or has already been used. "
                "Sign in to request another verification email."
            ),
        ), 400

    expires_at = user.get("email_verification_expires_at")

    try:
        expired = (
            not expires_at
            or datetime.now() > datetime.fromisoformat(expires_at)
        )
    except ValueError:
        expired = True

    if expired:
        session.clear()
        session[PENDING_VERIFICATION_KEY] = user["id"]
        session["verification_error"] = (
            "That verification link has expired. Request a new verification email."
        )
        return redirect(url_for("auth.verify_email_pending"))

    verified_user = mark_email_verified(user["id"])

    session.clear()

    return redirect(
        url_for(
            "auth.login",
            verified=1,
            email=verified_user["email"],
        )
    )


@auth_bp.route("/verify-email/resend", methods=["POST"])
def resend_verification_email():
    user = _pending_user()
    if not user:
        return redirect(url_for("auth.login"))

    if user.get("email_verified_at"):
        return redirect(
            url_for(
                "auth.login",
                verified=1,
                email=user["email"],
            )
        )

    recently_sent, remaining = _recently_sent(user)
    if recently_sent:
        session["verification_error"] = (
            f"Please wait {remaining} seconds before sending another verification email."
        )
        return redirect(url_for("auth.verify_email_pending"))

    sent, delivery_error = _issue_verification(user)

    if sent:
        session["verification_notice"] = (
            f"A new verification link was sent to {user['email']}."
        )

    if delivery_error:
        session["verification_error"] = delivery_error

    return redirect(url_for("auth.verify_email_pending"))


@auth_bp.route("/verify-email/change", methods=["GET", "POST"])
def change_verification_email():
    user = _pending_user()
    if not user:
        return redirect(url_for("auth.login"))

    if user.get("email_verified_at"):
        return redirect(
            url_for(
                "auth.login",
                verified=1,
                email=user["email"],
            )
        )

    error = None
    email = user["email"]

    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()

        if not _valid_email(email):
            error = "Enter a valid email address."
        else:
            existing = get_user_by_email(email)

            if existing and existing["id"] != user["id"]:
                error = "An account with this email already exists."
            elif email == user["email"]:
                return redirect(url_for("auth.verify_email_pending"))
            else:
                updated_user = update_unverified_user_email(
                    user["id"],
                    email,
                )

                if not updated_user:
                    error = "That email address cannot be used."
                else:
                    session.pop(DEBUG_VERIFICATION_URL_KEY, None)
                    sent, delivery_error = _issue_verification(updated_user)

                    if sent:
                        session["verification_notice"] = (
                            f"We sent a verification link to {updated_user['email']}."
                        )

                    if delivery_error:
                        session["verification_error"] = delivery_error

                    return redirect(url_for("auth.verify_email_pending"))

    return render_template(
        "change_verification_email.html",
        email=email,
        error=error,
    )


@auth_bp.route("/firm-profile", methods=["GET", "POST"])
@auth_bp.route("/settings", methods=["GET", "POST"])
def firm_profile():
    if g.user is None:
        return redirect(url_for("auth.login"))

    session.pop("client_id", None)
    g.client = None
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
            return redirect(url_for("bas.dashboard"))

    return render_template(
        "firm_profile.html",
        values=values,
        error=error,
    )


@auth_bp.route("/logout", methods=["POST"])
def logout():
    session.clear()
    return redirect(url_for("auth.login"))
