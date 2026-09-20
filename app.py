from flask import Flask

from config import FLASK_SECRET_KEY
from routes.auth_routes import auth_bp
from routes.bas_routes import bas_bp
from routes.qbo_routes import qbo_bp
from services.database import init_db


def create_app():
    app = Flask(__name__)
    app.secret_key = FLASK_SECRET_KEY
    init_db()

    app.register_blueprint(auth_bp)
    app.register_blueprint(qbo_bp)
    app.register_blueprint(bas_bp)

    return app


app = create_app()


if __name__ == "__main__":
    app.run(port=8000)
