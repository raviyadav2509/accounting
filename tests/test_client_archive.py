import os
import subprocess
import sys
from datetime import datetime, timedelta, timezone

from database import store as database
from services.bas_service import bas_signature, calculate_bas
from services.demo_service import create_demo_client, demo_periods


def token(browser, client_id):
    assert browser.get(f"/clients/{client_id}/delete").status_code == 200
    with browser.session_transaction() as session:
        return session["client_archive_token"]


def archive(browser, client_id):
    csrf = token(browser, client_id)
    return browser.post(
        f"/clients/{client_id}/delete",
        data={"csrf_token": csrf, "confirm": "DELETE"},
    )


def test_archive_and_restore_real_client_with_all_data(signed_in, client, user, monkeypatch):
    from routes import client_routes

    monkeypatch.setattr(client_routes, "CLIENT_ARCHIVE_RETENTION_DAYS", 7)
    demo = create_demo_client(user["id"], "clean")
    period = demo_periods()
    bas = calculate_bas(demo["id"], period["start"], period["end"])
    snapshot = database.save_bas_snapshot(client["id"], bas, bas_signature(bas))
    tax = database.create_tax_return(client["id"], period["financial_year"], "2025-07-01", "2026-06-30", "COMPANY")
    database.add_tax_adjustment(client["id"], tax["id"], "ADD", "Test", "Test", 100)
    database.save_qbo_connection(client["id"], "test-realm", {"access_token": "test-token"})

    response = archive(signed_in, client["id"])
    assert response.status_code == 302
    assert response.location.endswith("/clients/archive")
    with signed_in.session_transaction() as session:
        assert "client_id" not in session
        csrf = session["client_archive_token"]
    saved = database.get_archived_clients_for_user(user["id"])[0]
    assert datetime.fromisoformat(saved["purge_at"]) - datetime.fromisoformat(saved["archived_at"]) == timedelta(days=7)
    assert client["company_name"].encode() in signed_in.get("/clients/archive").data
    for path in ["/clients/", "/", "/bas-history", "/tax-returns"]:
        assert client["company_name"].encode() not in signed_in.get(path).data
    assert signed_in.get(f'/bas-history/{snapshot["id"]}').status_code == 404
    response = signed_in.get(f'/clients/{client["id"]}/tax-returns')
    assert response.status_code == 302
    assert response.location.endswith("/clients/")
    assert database.get_client_for_user(client["id"], user["id"]) is None

    assert signed_in.post(f'/clients/{client["id"]}/restore', data={"csrf_token": csrf}).status_code == 302
    assert database.get_client_for_user(client["id"], user["id"])
    assert database.get_history(client["id"])[0]["id"] == snapshot["id"]
    assert database.get_tax_return(client["id"], tax["id"])
    assert database.get_tax_adjustments(client["id"], tax["id"])
    assert database.get_qbo_connection(client["id"])["realm_id"] == "test-realm"


def test_demo_archive_restore_preserves_progress(signed_in, user):
    demo = create_demo_client(user["id"], "clean")
    period = demo_periods()
    bas = calculate_bas(demo["id"], period["start"], period["end"])
    database.save_bas_snapshot(demo["id"], bas, bas_signature(bas))
    assert archive(signed_in, demo["id"]).status_code == 302
    assert demo["company_name"].encode() not in signed_in.get("/demo/").data
    assert signed_in.get(f'/demo/{demo["id"]}').status_code == 404
    with signed_in.session_transaction() as session:
        csrf = session["client_archive_token"]
    assert signed_in.post(f'/clients/{demo["id"]}/restore', data={"csrf_token": csrf}).status_code == 302
    assert demo["company_name"].encode() in signed_in.get("/demo/").data
    assert database.get_history(demo["id"])
    assert calculate_bas(demo["id"], period["start"], period["end"]) == bas


def test_demo_can_be_restored_when_active_creation_limit_is_reached(signed_in, user):
    demo = create_demo_client(user["id"], "clean")
    for _ in range(4):
        create_demo_client(user["id"], "review")
    assert archive(signed_in, demo["id"]).status_code == 302
    create_demo_client(user["id"], "clean")
    with signed_in.session_transaction() as session:
        csrf = session["client_archive_token"]
    assert signed_in.post(f'/clients/{demo["id"]}/restore', data={"csrf_token": csrf}).status_code == 302
    assert len([c for c in database.get_clients_for_user(user["id"]) if c["data_source"] == "DEMO"]) == 6


def test_archive_requires_confirmation_csrf_and_ownership(signed_in, client, user):
    other = database.create_user("Other", "User", "other@example.com", "hash", "Firm", "Director")
    other_client = database.create_client(other["id"], "Other Client")
    csrf = token(signed_in, client["id"])
    assert signed_in.post(f'/clients/{client["id"]}/delete', data={"confirm": "DELETE"}).status_code == 400
    assert signed_in.post(f'/clients/{client["id"]}/delete', data={"csrf_token": "é", "confirm": "DELETE"}).status_code == 400
    response = signed_in.post(f'/clients/{client["id"]}/delete', data={"csrf_token": csrf, "confirm": "delete"})
    assert b"Type DELETE to confirm" in response.data
    assert database.get_client_for_user(client["id"], user["id"])
    assert signed_in.get(f'/clients/{other_client["id"]}/delete').status_code == 404
    assert signed_in.post(f'/clients/{other_client["id"]}/delete', data={"csrf_token": csrf, "confirm": "DELETE"}).status_code == 404
    assert database.archive_client(other_client["id"], other["id"], 30)
    assert other_client["company_name"].encode() not in signed_in.get("/clients/archive").data
    assert signed_in.post(f'/clients/{other_client["id"]}/restore', data={"csrf_token": csrf}).status_code == 404
    assert signed_in.post(f'/clients/{client["id"]}/restore').status_code == 400


def test_expired_archives_purged_on_request_with_cascades(signed_in, user, client):
    demo = create_demo_client(user["id"], "clean")
    period = demo_periods()
    bas = calculate_bas(demo["id"], period["start"], period["end"])
    database.save_bas_snapshot(demo["id"], bas, bas_signature(bas))
    tax = database.create_tax_return(demo["id"], period["financial_year"], "2025-07-01", "2026-06-30", "COMPANY")
    database.add_tax_adjustment(demo["id"], tax["id"], "ADD", "Test", "Test", 100)
    database.save_qbo_connection(demo["id"], "test-realm", {"access_token": "test-token"})
    assert archive(signed_in, demo["id"]).status_code == 302
    with signed_in.session_transaction() as session:
        csrf = session["client_archive_token"]
    past = (datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat(timespec="seconds")
    with database.get_connection() as connection:
        connection.execute("UPDATE clients SET purge_at = ? WHERE id = ?", (past, demo["id"]))
    assert signed_in.post(f'/clients/{demo["id"]}/restore', data={"csrf_token": csrf}).status_code == 404
    with database.get_connection() as connection:
        for table in ["clients", "bas_records", "tax_returns", "qbo_connections", "demo_transactions"]:
            key = "id" if table == "clients" else "client_id"
            assert connection.execute(f"SELECT COUNT(*) FROM {table} WHERE {key} = ?", (demo["id"],)).fetchone()[0] == 0
        assert connection.execute("SELECT COUNT(*) FROM tax_return_adjustments WHERE tax_return_id = ?", (tax["id"],)).fetchone()[0] == 0
    assert database.get_client_for_user(client["id"], user["id"])


def test_archive_migration_preserves_existing_clients(user, client):
    with database.get_connection() as connection:
        connection.execute("DROP INDEX idx_clients_purge_at")
        connection.execute("ALTER TABLE clients DROP COLUMN archived_at")
        connection.execute("ALTER TABLE clients DROP COLUMN purge_at")
    database.init_db()
    database.init_db()
    assert database.get_client_for_user(client["id"], user["id"])["company_name"] == client["company_name"]
    assert database.archive_client(client["id"], user["id"], 30)
    assert database.get_archived_clients_for_user(user["id"])[0]["id"] == client["id"]


def test_retention_environment_setting():
    env = dict(os.environ, PYTHON_DOTENV_DISABLED="1", CLIENT_ARCHIVE_RETENTION_DAYS="7")
    result = subprocess.run(
        [sys.executable, "-c", "import config; assert config.CLIENT_ARCHIVE_RETENTION_DAYS == 7"],
        env=env, capture_output=True, text=True, timeout=20,
    )
    assert result.returncode == 0, result.stderr
    env["CLIENT_ARCHIVE_RETENTION_DAYS"] = "0"
    result = subprocess.run(
        [sys.executable, "-c", "import config"], env=env, capture_output=True, text=True, timeout=20,
    )
    assert result.returncode != 0
    assert "CLIENT_ARCHIVE_RETENTION_DAYS must be a positive" in result.stderr
