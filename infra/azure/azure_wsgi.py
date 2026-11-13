"""Azure entry point: create persistent data directory before app initialization."""
import os
from pathlib import Path

database = Path(os.environ.get("BAS_DATABASE_FILE", "/home/bas-data/bas_history.db"))
database.parent.mkdir(parents=True, exist_ok=True)

from app import app  # noqa: E402

app.config.update(
    SESSION_COOKIE_SECURE=True,
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
)
