from datetime import datetime, timedelta

import pytest
from werkzeug.security import check_password_hash

from database import store as database
from services.email_verification_service import hash_verification_token


@pytest.mark.parametrize("path", ["/", "/clients/", "/bas-history", "/tax-returns"])
def test_anonymous_users_require_login(browser, path):
    response = browser.get(path)
    assert response.status_code == 302
    assert response.location.endswith("/login")


def test_login_page_renders(browser):
    assert browser.get("/login").status_code == 200


@pytest.mark.parametrize("enabled", [True, False])
def test_local_testing_option_follows_debug_setting(browser, monkeypatch, enabled):
    from routes import auth_routes

    monkeypatch.setattr(auth_routes, "EMAIL_VERIFICATION_DEBUG_LINKS", enabled)
    login = browser.get("/login")
    signup = browser.get("/signup")
    assert b'name="local_testing"' not in login.data
    assert (b'name="local_testing"' in signup.data) is enabled


@pytest.mark.parametrize("enabled,selected,expected", [
    (True, True, "dashboard"),
    (True, False, "verify-email"),
    (False, True, "rejected"),
])
def test_signup_local_testing_requires_enabled_and_selected(
    browser, monkeypatch, enabled, selected, expected,
):
    from routes import auth_routes

    monkeypatch.setattr(auth_routes, "EMAIL_VERIFICATION_DEBUG_LINKS", enabled)
    monkeypatch.setattr(auth_routes, "email_delivery_configured", lambda: False)
    if expected == "dashboard":
        def unexpected_verification(_user):
            pytest.fail("Local testing must not send a verification email")

        monkeypatch.setattr(auth_routes, "_issue_verification", unexpected_verification)
    form = {
        "firm_name": "Test Firm", "director_name": "Test Director",
        "first_name": "Test", "last_name": "User", "email": "new@example.com",
        "password": "test-password", "confirm_password": "test-password",
    }
    if selected:
        form["local_testing"] = "1"
    response = browser.post("/signup", data=form)
    user = database.get_user_by_email("new@example.com")

    if expected == "rejected":
        assert response.status_code == 400
        assert user is None
    elif expected == "dashboard":
        assert response.status_code == 302
        assert response.location.endswith("/")
        assert user["email_verified_at"]
        assert user["email_verification_token_hash"] is None
        with browser.session_transaction() as session:
            assert session["user_id"] == user["id"]
        assert browser.get("/").status_code == 200
    else:
        assert response.status_code == 302
        assert response.location.endswith("/verify-email")
        assert user["email_verified_at"] is None
        with browser.session_transaction() as session:
            assert "user_id" not in session
            assert session["pending_verification_user_id"] == user["id"]


def test_signup_validation_retains_local_testing_selection(browser, monkeypatch):
    from routes import auth_routes

    monkeypatch.setattr(auth_routes, "EMAIL_VERIFICATION_DEBUG_LINKS", True)
    response = browser.post("/signup", data={"local_testing": "1"})
    assert response.status_code == 200
    assert b'name="local_testing" value="1" checked' in response.data
    assert b"Enter the accounting firm name." in response.data


@pytest.mark.parametrize("enabled", [True, False])
def test_verification_url_is_visible_only_when_debug_enabled(browser, user, monkeypatch, enabled):
    from routes import auth_routes

    token = "test-verification-token"
    url = f"http://localhost/verify-email/{token}"
    database.set_email_verification(
        user["id"], hash_verification_token(token),
        (datetime.now() + timedelta(minutes=10)).isoformat(),
    )
    monkeypatch.setattr(auth_routes, "EMAIL_VERIFICATION_DEBUG_LINKS", enabled)
    with browser.session_transaction() as session:
        session["pending_verification_user_id"] = user["id"]
        session["debug_verification_url"] = url

    response = browser.get("/verify-email")
    assert response.status_code == 200
    assert (f'href="{url}">{url}</a>'.encode() in response.data) is enabled
    if enabled:
        assert browser.get(f"/verify-email/{token}").status_code == 302
        assert database.get_user_by_id(user["id"])["email_verified_at"]


def test_unverified_session_cannot_access_clients(browser, user):
    with browser.session_transaction() as session:
        session["user_id"] = user["id"]
    response = browser.get("/clients/")
    assert response.status_code == 302
    with browser.session_transaction() as session:
        assert "user_id" not in session
        assert session["pending_verification_user_id"] == user["id"]


def test_verified_dashboard_and_clients_render(signed_in):
    assert signed_in.get("/").status_code == 200
    assert signed_in.get("/clients/").status_code == 200


def test_password_reset_is_single_use(browser, user):
    token = "test-reset-token"
    database.set_password_reset(
        user["id"], hash_verification_token(token),
        (datetime.now() + timedelta(minutes=10)).isoformat(),
    )
    response = browser.post(f"/reset-password/{token}", data={
        "password": "NewTestPassword123!", "confirm_password": "NewTestPassword123!",
    })
    assert response.status_code == 302
    updated = database.get_user_by_id(user["id"])
    assert check_password_hash(updated["password_hash"], "NewTestPassword123!")
    assert updated["password_reset_token_hash"] is None
    assert browser.get(f"/reset-password/{token}").status_code == 400


def test_password_reset_debug_url_survives_repeat_request(browser, user, monkeypatch):
    from routes import auth_routes

    monkeypatch.setattr(auth_routes, "PASSWORD_RESET_DEBUG_LINKS", True)
    monkeypatch.setattr(auth_routes, "email_delivery_configured", lambda: False)
    response = browser.post("/forgot-password", data={"email": user["email"]})
    with browser.session_transaction() as session:
        url = session["debug_password_reset_url"]
    assert f'href="{url}">{url}</a>'.encode() in response.data
    response = browser.post("/forgot-password", data={"email": user["email"]})
    assert f'href="{url}">{url}</a>'.encode() in response.data
    response = browser.post("/forgot-password", data={"email": "unknown@example.com"})
    assert url.encode() not in response.data
    with browser.session_transaction() as session:
        assert "debug_password_reset_url" not in session


def test_password_reset_debug_link_not_displayed_when_disabled(browser, user, monkeypatch):
    from routes import auth_routes

    monkeypatch.setattr(auth_routes, "PASSWORD_RESET_DEBUG_LINKS", False)
    monkeypatch.setattr(auth_routes, "email_delivery_configured", lambda: False)
    with browser.session_transaction() as session:
        session["debug_password_reset_url"] = "http://localhost/reset-password/old-token"
    response = browser.post("/forgot-password", data={"email": user["email"]})
    assert b"Generated password reset link" not in response.data
    assert b"old-token" not in response.data


def test_password_reset_does_not_show_stale_link_during_cooldown(browser, user, monkeypatch):
    from routes import auth_routes

    monkeypatch.setattr(auth_routes, "PASSWORD_RESET_DEBUG_LINKS", True)
    monkeypatch.setattr(auth_routes, "email_delivery_configured", lambda: False)
    browser.post("/forgot-password", data={"email": user["email"]})
    with browser.session_transaction() as session:
        url = session["debug_password_reset_url"]
    database.set_password_reset(
        user["id"], hash_verification_token("new-token"),
        (datetime.now() + timedelta(minutes=10)).isoformat(),
    )
    response = browser.post("/forgot-password", data={"email": user["email"]})
    assert url.encode() not in response.data


@pytest.mark.parametrize("enabled,approved,expected", [
    (False, True, 404), (True, False, 400), (True, True, 302),
])
def test_tax_lodgement_requires_switch_and_explicit_approval(
    signed_in, client, monkeypatch, enabled, approved, expected,
):
    from routes import tax_routes

    monkeypatch.setattr(tax_routes, "ENABLE_MOCK_ATO_LODGEMENT", enabled)
    record = database.create_tax_return(
        client["id"], "2025-26", "2025-07-01", "2026-06-30", "COMPANY",
    )
    # A passing review alone must never authorise lodgement.
    database.update_tax_return(client["id"], record["id"], review_status="PASS")
    base = f'/clients/{client["id"]}/tax-returns/{record["id"]}'
    if approved:
        assert signed_in.post(base + "/approve").status_code == 302
    response = signed_in.post(base + "/mock-lodge")
    assert response.status_code == expected
    result = database.get_tax_return(client["id"], record["id"])
    assert bool(result["lodged_at"]) == (enabled and approved)
    if enabled and approved:
        reference = result["lodgement_reference"]
        assert reference.startswith("MOCK-TAX-")
        signed_in.post(base + "/mock-lodge")
        assert database.get_tax_return(client["id"], record["id"])["lodgement_reference"] == reference


def test_tax_approval_requires_review(signed_in, client):
    record = database.create_tax_return(
        client["id"], "2025-26", "2025-07-01", "2026-06-30", "COMPANY",
    )
    response = signed_in.post(f'/clients/{client["id"]}/tax-returns/{record["id"]}/approve')
    assert response.status_code == 400
    assert database.get_tax_return(client["id"], record["id"])["approval_status"] is None


@pytest.mark.parametrize("enabled,approved,expected", [
    (False, True, 404), (True, False, 400), (True, True, 302),
])
def test_bas_lodgement_requires_switch_and_approval(
    signed_in, client, monkeypatch, enabled, approved, expected,
):
    from routes import bas_routes

    monkeypatch.setattr(bas_routes, "ENABLE_MOCK_ATO_LODGEMENT", enabled)
    database.save_qbo_connection(client["id"], "test-realm", {"access_token": "fake"})
    bas = dict(start="2026-07-01", end="2026-09-30", g1=110, gst_sales=10,
               gst_purchases=5, w1=100, w2=20, gst_position=5, payable=25)
    database.save_bas_snapshot(client["id"], bas, "test-signature")
    args = (client["id"], bas["start"], bas["end"], "test-signature")
    database.update_review(*args, "PASS", "Test review")
    if approved:
        database.mark_approved(*args, "PASS")
    response = signed_in.post("/mock-lodge-bas", data={
        "start": bas["start"], "end": bas["end"], "signature": "test-signature",
    })
    assert response.status_code == expected
    assert bool(database.get_bas_record(*args)["lodged_at"]) == (enabled and approved)
