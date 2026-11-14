import os
import subprocess
import sys
from datetime import date

import pytest

from services import database, accounting_data_service, qbo_service
from services.bas_service import calculate_bas, bas_signature
from services.demo_service import (
    create_demo_client, reset_demo_client, demo_periods, demo_query, demo_review,
)
from services.tax_return_service import import_accounting_profit, financial_year_dates


@pytest.fixture
def demo(user):
    return create_demo_client(user["id"], "clean")


@pytest.fixture
def demo_browser(signed_in, demo):
    with signed_in.session_transaction() as session:
        session["client_id"] = demo["id"]
    return signed_in


def csrf(browser):
    browser.get("/demo/new")
    with browser.session_transaction() as session:
        return session["demo_csrf_token"]


def test_seeded_transactions_use_real_calculators(demo):
    period = demo_periods()
    result = calculate_bas(demo["id"], period["start"], period["end"])
    assert result["g1"] == 49500
    assert result["gst_sales"] == 4500
    assert result["gst_purchases"] == 1200
    assert result["w1"] == 15000
    assert result["w2"] == 3000
    assert result["payable"] == 6300
    assert database.get_qbo_connection(demo["id"]) is None
    start, end = financial_year_dates(period["financial_year"])
    assert import_accounting_profit(demo["id"], start, end) == 72000
    assert demo_review(result)["status"] == "PASS"


def test_demo_dates_and_filtering(demo):
    assert demo_periods(date(2026, 6, 30))["financial_year"] == "2024-25"
    assert demo_periods(date(2026, 7, 1))["financial_year"] == "2025-26"
    period = demo_periods()
    all_items = demo_query(demo["id"], "Invoice")["QueryResponse"]["Invoice"]
    assert len(all_items) == 24
    items = demo_query(demo["id"], "Invoice", period["start"], period["end"])["QueryResponse"]["Invoice"]
    assert len(items) == 3
    with pytest.raises(ValueError):
        demo_query(demo["id"], "Invoice", period["end"], period["start"])


def test_create_demo_through_ui(signed_in, user):
    token = csrf(signed_in)
    response = signed_in.post("/demo/new", data={"scenario": "review", "csrf_token": token}, follow_redirects=True)
    assert response.status_code == 200
    assert b"DEMO" in response.data
    assert b"Confirm" in response.data or b"confirm" in response.data
    clients = database.get_clients_for_user(user["id"])
    assert sum(c["data_source"] == "DEMO" for c in clients) == 1


@pytest.mark.parametrize("path", ["/demo/new", "/demo/1"])
def test_anonymous_demo_requires_login(browser, path):
    assert browser.get(path).location.endswith("/login")


def test_demo_creation_requires_csrf_and_valid_scenario(signed_in, user):
    before = len(database.get_clients_for_user(user["id"]))
    assert signed_in.post("/demo/new", data={"scenario": "clean"}).status_code == 400
    response = signed_in.post("/demo/new", data={"scenario": "bogus", "csrf_token": csrf(signed_in)})
    assert b"Choose a valid demo scenario" in response.data
    assert len(database.get_clients_for_user(user["id"])) == before


def test_bas_demo_review_approval_and_simulation(demo_browser, demo, user):
    reset_demo_client(demo["id"], user["id"], "review")
    period = demo_periods()
    assert demo_browser.get("/bas-review", query_string=period).status_code == 200
    assert demo_browser.post("/approve-bas", data=period).status_code == 400
    response = demo_browser.get("/ai-review", query_string=period)
    assert response.status_code == 200
    assert b"Simulated demo review (not AI)" in response.data
    assert demo_browser.post("/approve-bas", data=period).status_code == 400
    assert demo_browser.post("/resolve-review", data={**period, "confirm_reviewed": "yes",
        "resolution_note": "Demo exercise: confirm equipment is wholly business-use"}).status_code == 302
    assert demo_browser.post("/approve-bas", data=period).status_code == 200
    bas = calculate_bas(demo["id"], period["start"], period["end"])
    form = {**period, "signature": bas_signature(bas)}
    assert demo_browser.post("/mock-lodge-bas", data=form).status_code == 302
    record = database.get_bas_record(demo["id"], period["start"], period["end"], form["signature"])
    assert record["approval_status"] == "LODGED"
    assert record["lodgement_reference"].startswith("MOCK-BAS-")
    assert demo_browser.post("/reopen-bas", data=form).status_code == 302
    assert database.get_bas_record(demo["id"], period["start"], period["end"], form["signature"])["approval_status"] == "LODGED"


def test_demo_tax_end_to_end(demo_browser, demo):
    prefix = f'/clients/{demo["id"]}/tax-returns'
    response = demo_browser.post(prefix + "/new", data={"financial_year": demo_periods()["financial_year"]})
    base = response.location
    assert demo_browser.get(base).status_code == 200
    assert demo_browser.post(base + "/refresh-qbo").status_code == 302
    record = database.get_tax_returns_for_client(demo["id"])[0]
    assert record["accounting_profit"] == 72000
    assert demo_browser.post(base + "/approve").status_code == 400
    demo_browser.post(base + "/tax-rate", data={"tax_rate": "0.25"})
    demo_browser.post(base + "/review")
    assert demo_browser.post(base + "/mock-lodge").status_code == 400
    assert demo_browser.post(base + "/approve").status_code == 302
    assert demo_browser.post(base + "/mock-lodge").status_code == 302
    record = database.get_tax_return(demo["id"], record["id"])
    assert record["estimated_tax"] == 18000
    assert record["lodgement_reference"].startswith("MOCK-TAX-")


def test_reset_removes_only_selected_demo_progress(demo_browser, demo, client, user):
    other = create_demo_client(user["id"], "review")
    records = {}
    for c in [demo, client, other]:
        records[c["id"]] = database.create_tax_return(c["id"], "2025-26", "2025-07-01", "2026-06-30", "COMPANY")
        database.add_tax_adjustment(c["id"], records[c["id"]]["id"], "ADD", "Test", "Test", 100)
    p = demo_periods()
    bas = calculate_bas(demo["id"], p["start"], p["end"])
    database.save_bas_snapshot(demo["id"], bas, bas_signature(bas))
    url = f'/demo/{demo["id"]}'
    token = csrf(demo_browser)
    assert demo_browser.post(url, data={"csrf_token": token, "scenario": "clean"}).status_code == 400
    assert database.get_history(demo["id"])
    assert demo_browser.post(url, data={"csrf_token": token, "scenario": "clean", "confirm_reset": "RESET"}).status_code == 302
    assert database.get_tax_returns_for_client(demo["id"]) == []
    assert database.get_history(demo["id"]) == []
    with database.get_connection() as connection:
        assert connection.execute("SELECT COUNT(*) FROM tax_return_adjustments WHERE tax_return_id=?", (records[demo["id"]]["id"],)).fetchone()[0] == 0
    for c in [client, other]:
        assert database.get_tax_return(c["id"], records[c["id"]]["id"])
        assert database.get_tax_adjustments(c["id"], records[c["id"]]["id"])
    assert calculate_bas(demo["id"], p["start"], p["end"]) == bas
    assert demo_browser.post(f'/demo/{client["id"]}', data={"csrf_token": token, "scenario": "clean", "confirm_reset": "RESET"}).status_code == 404


def test_other_users_cannot_read_reset_or_lodge_demo(signed_in, demo, user):
    outsider = database.create_user("Other", "User", "outsider@example.com", "hash", "Firm", "Director")
    database.mark_email_verified(outsider["id"])
    with signed_in.session_transaction() as session:
        session.clear()
        session["user_id"] = outsider["id"]
        session["client_id"] = demo["id"]  # Forged/stale selected-client context.
    assert signed_in.get(f'/demo/{demo["id"]}').status_code == 404
    token = csrf(signed_in)
    assert signed_in.post(f'/demo/{demo["id"]}', data={"csrf_token": token, "scenario": "clean", "confirm_reset": "RESET"}).status_code == 404
    with pytest.raises(ValueError):
        reset_demo_client(demo["id"], outsider["id"], "clean")
    assert signed_in.post("/mock-lodge-bas").status_code == 404
    assert database.get_client_for_user(demo["id"], user["id"])


@pytest.mark.parametrize("path", ["/connect", "/company", "/pnl", "/transactions", "/accounts", "/taxcodes"])
def test_demo_never_enters_qbo_routes(demo_browser, path):
    assert demo_browser.get(path).status_code == 400


def test_demo_never_exchanges_oauth_credentials(demo):
    with pytest.raises(ValueError, match="disabled"):
        qbo_service.exchange_authorization_code("code", "realm", demo["id"])
    with pytest.raises(ValueError, match="disabled"):
        qbo_service.refresh_access_token(demo["id"])
    with pytest.raises(ValueError, match="disabled"):
        qbo_service._request(demo["id"], "GET", "https://example.invalid")


def test_normal_clients_still_use_qbo(client, monkeypatch):
    calls = []
    monkeypatch.setattr(qbo_service, "query", lambda *args: calls.append(args) or {"real": True})
    assert accounting_data_service.query(client["id"], "Invoice", "2025-07-01", "2026-06-30") == {"real": True}
    assert calls[0][0] == client["id"]
    monkeypatch.setattr(qbo_service, "get_report", lambda *args: {"qbo_report": True})
    assert accounting_data_service.get_report(client["id"], "ProfitAndLoss", "2025-07-01", "2026-06-30") == {"qbo_report": True}


def test_app_starts_without_external_credentials(tmp_path):
    env = dict(os.environ, BAS_DATABASE_FILE=str(tmp_path / "startup.db"), PYTHON_DOTENV_DISABLED="1")
    for key in ["OPENAI_API_KEY", "QBO_CLIENT_ID", "QBO_CLIENT_SECRET", "SMTP_PASSWORD"]:
        env.pop(key, None)
    result = subprocess.run([sys.executable, "-c", "from app import app; assert app.test_client().get('/login').status_code == 200"], env=env, capture_output=True, text=True, timeout=20)
    assert result.returncode == 0, result.stderr


def test_database_migration_preserves_existing_client(client):
    with database.get_connection() as connection:
        connection.execute("ALTER TABLE clients DROP COLUMN data_source")
    database.init_db()
    database.init_db()
    result = database.get_client_by_id(client["id"])
    assert result["company_name"] == client["company_name"]
    assert result["data_source"] == "QUICKBOOKS"


def test_demo_pages_render_and_qbo_screen_redirects(demo_browser, demo):
    for path in [f'/demo/{demo["id"]}', f'/clients/{demo["id"]}/details',
                 f'/clients/{demo["id"]}/active-bas', f'/clients/{demo["id"]}/historical-bas',
                 f'/clients/{demo["id"]}/tax-returns', '/clients/', '/', '/bas-history', '/tax-returns']:
        assert demo_browser.get(path).status_code == 200, path
    response = demo_browser.get(f'/clients/{demo["id"]}/quickbooks')
    assert response.location.endswith(f'/demo/{demo["id"]}')


def test_demo_limit_and_invalid_reset_preserve_fixtures(user, demo):
    for _ in range(4):
        create_demo_client(user["id"], "clean")
    with pytest.raises(ValueError, match="five"):
        create_demo_client(user["id"], "clean")
    before = demo_query(demo["id"], "Invoice")
    with pytest.raises(ValueError):
        reset_demo_client(demo["id"], user["id"], "invalid")
    assert demo_query(demo["id"], "Invoice") == before


def test_demo_is_not_a_request_toggle(client, demo, user):
    database.update_client(client["id"], user["id"], data_source="DEMO")
    database.update_client(demo["id"], user["id"], data_source="QUICKBOOKS")
    assert database.get_client_by_id(client["id"])["data_source"] == "QUICKBOOKS"
    assert database.get_client_by_id(demo["id"])["data_source"] == "DEMO"
    with pytest.raises(ValueError):
        demo_query(client["id"], "Invoice")
    with pytest.raises(ValueError, match="not supported"):
        accounting_data_service.get_report(demo["id"], "GeneralLedger", "2025-07-01", "2026-06-30")


def test_demo_callback_target_is_checked_even_with_other_selected_client(demo_browser, demo, client):
    with demo_browser.session_transaction() as session:
        session["client_id"] = client["id"]
        session["qbo_oauth_client_id"] = demo["id"]
        session["qbo_oauth_state"] = "test-state"
    response = demo_browser.get("/callback?state=test-state&code=fake&realmId=fake")
    assert response.status_code == 400
    assert database.get_qbo_connection(demo["id"]) is None


def test_reset_is_atomic_on_seed_failure(demo, user, monkeypatch):
    from services import demo_service
    record = database.create_tax_return(demo["id"], "2025-26", "2025-07-01", "2026-06-30", "COMPANY")
    before = demo_query(demo["id"], "Invoice")
    def fail(*args):
        raise RuntimeError("Simulated seed error")
    monkeypatch.setattr(demo_service, "_seed", fail)
    with pytest.raises(RuntimeError):
        reset_demo_client(demo["id"], user["id"], "clean")
    assert demo_query(demo["id"], "Invoice") == before
    assert database.get_tax_return(demo["id"], record["id"])
