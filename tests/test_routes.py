from datetime import datetime, timedelta

import pytest
from werkzeug.security import check_password_hash

from services import database
from services.email_verification_service import hash_verification_token


@pytest.mark.parametrize("path", ["/", "/clients/", "/bas-history", "/tax-returns"])
def test_anonymous_users_require_login(browser, path):
    response = browser.get(path)
    assert response.status_code == 302
    assert response.location.endswith("/login")


def test_login_page_renders(browser):
    assert browser.get("/login").status_code == 200


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
