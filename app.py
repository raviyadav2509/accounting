from flask import Flask

from config import FLASK_SECRET_KEY
from routes.auth_routes import auth_bp
from routes.bas_routes import bas_bp
from routes.client_routes import clients_bp
from routes.qbo_routes import qbo_bp
from services.database import init_db


def client_initials(company_name):
    words = [word for word in (company_name or "").split() if word]

    if not words:
        return "?"

    return "".join(word[0] for word in words[:2]).upper()


def create_app():
    app = Flask(__name__)
    app.secret_key = FLASK_SECRET_KEY
    app.config.update(
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Lax",
    )
    init_db()

    app.jinja_env.filters["client_initials"] = client_initials

    app.register_blueprint(auth_bp)
    app.register_blueprint(clients_bp)
    app.register_blueprint(qbo_bp)
    app.register_blueprint(bas_bp)

    return app


app = create_app()


if __name__ == "__main__":
    app.run(port=8000)
