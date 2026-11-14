import os
import socket
from unittest.mock import Mock

# Never load local credentials or make real network requests during tests.
os.environ["PYTHON_DOTENV_DISABLED"] = "1"
os.environ["OPENAI_API_KEY"] = "test-only-not-a-real-key"
os.environ["FLASK_SECRET_KEY"] = "test-only-session-key"
os.environ["ENABLE_MOCK_ATO_LODGEMENT"] = "false"

import pytest

from services import database


@pytest.fixture(autouse=True)
def block_network(monkeypatch):
    def blocked(*args, **kwargs):
        raise AssertionError("Tests must stub external services; network access blocked")

    monkeypatch.setattr(socket.socket, "connect", blocked)
    monkeypatch.setattr(socket.socket, "connect_ex", blocked)


@pytest.fixture
def web_app(database_file, monkeypatch):
    # Import only after the database fixture isolates the import-time app creation.
    import openai

    fake_ai = Mock()
    fake_ai.responses.create.side_effect = AssertionError("AI responses must be stubbed")
    monkeypatch.setattr(openai, "OpenAI", lambda **kwargs: fake_ai)
    from app import create_app

    app = create_app()
    app.config.update(TESTING=True)
    return app


@pytest.fixture
def browser(web_app):
    return web_app.test_client()


@pytest.fixture
def signed_in(browser, user, client):
    database.mark_email_verified(user["id"])
    with browser.session_transaction() as session:
        session["user_id"] = user["id"]
        session["client_id"] = client["id"]
    return browser


@pytest.fixture
def database_file(tmp_path, monkeypatch):
    path = tmp_path / "test.db"
    monkeypatch.setattr(database, "DATABASE_FILE", str(path))
    database.init_db()
    return path


@pytest.fixture
def user(database_file):
    return database.create_user(
        first_name="Ravi",
        last_name="Yadav",
        email="ravi@example.com",
        password_hash="test-password-hash",
        firm_name="Ledgerence Accounting",
        director_name="Ravi Yadav",
    )


@pytest.fixture
def client(user):
    return database.create_client(
        user["id"],
        "Example Pty Ltd",
        entity_type="COMPANY",
    )
