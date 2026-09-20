import sqlite3
from datetime import datetime

from config import DATABASE_FILE


def _now():
    return datetime.now().isoformat(timespec="seconds")


def get_connection():
    connection = sqlite3.connect(DATABASE_FILE)
    connection.row_factory = sqlite3.Row
    return connection


def init_db():
    with get_connection() as connection:
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS bas_records (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                start_date TEXT NOT NULL,
                end_date TEXT NOT NULL,
                signature TEXT NOT NULL,
                g1 REAL NOT NULL,
                gst_sales REAL NOT NULL,
                gst_purchases REAL NOT NULL,
                w1 REAL NOT NULL,
                w2 REAL NOT NULL,
                gst_position REAL NOT NULL,
                payable REAL NOT NULL,

                review_status TEXT,
                review_text TEXT,
                reviewed_at TEXT,

                resolution_status TEXT,
                resolution_note TEXT,
                resolved_at TEXT,

                approval_status TEXT,
                approved_at TEXT,
                rejected_at TEXT,

                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,

                UNIQUE(start_date, end_date, signature)
            )
            """
        )
        connection.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_bas_records_period
            ON bas_records(start_date, end_date)
            """
        )
        connection.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_bas_records_updated
            ON bas_records(updated_at)
            """
        )
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                first_name TEXT NOT NULL,
                last_name TEXT NOT NULL,
                email TEXT NOT NULL UNIQUE COLLATE NOCASE,
                password_hash TEXT NOT NULL,
                is_active INTEGER NOT NULL DEFAULT 1,
                created_at TEXT NOT NULL,
                last_login_at TEXT
            )
            """
        )
        connection.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_users_email
            ON users(email)
            """
        )


def save_bas_snapshot(bas, signature):
    now = _now()

    with get_connection() as connection:
        connection.execute(
            """
            INSERT INTO bas_records (
                start_date,
                end_date,
                signature,
                g1,
                gst_sales,
                gst_purchases,
                w1,
                w2,
                gst_position,
                payable,
                created_at,
                updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(start_date, end_date, signature)
            DO UPDATE SET
                g1 = excluded.g1,
                gst_sales = excluded.gst_sales,
                gst_purchases = excluded.gst_purchases,
                w1 = excluded.w1,
                w2 = excluded.w2,
                gst_position = excluded.gst_position,
                payable = excluded.payable,
                updated_at = excluded.updated_at
            """,
            (
                bas["start"],
                bas["end"],
                signature,
                bas["g1"],
                bas["gst_sales"],
                bas["gst_purchases"],
                bas["w1"],
                bas["w2"],
                bas["gst_position"],
                bas["payable"],
                now,
                now,
            ),
        )

    return get_bas_record(bas["start"], bas["end"], signature)


def get_bas_record(start, end, signature):
    with get_connection() as connection:
        row = connection.execute(
            """
            SELECT *
            FROM bas_records
            WHERE start_date = ?
              AND end_date = ?
              AND signature = ?
            LIMIT 1
            """,
            (start, end, signature),
        ).fetchone()

    return dict(row) if row else None


def update_review(start, end, signature, status, review_text):
    now = _now()

    with get_connection() as connection:
        connection.execute(
            """
            UPDATE bas_records
            SET review_status = ?,
                review_text = ?,
                reviewed_at = ?,
                resolution_status = NULL,
                resolution_note = NULL,
                resolved_at = NULL,
                approval_status = NULL,
                approved_at = NULL,
                rejected_at = NULL,
                updated_at = ?
            WHERE start_date = ?
              AND end_date = ?
              AND signature = ?
            """,
            (
                status,
                review_text,
                now,
                now,
                start,
                end,
                signature,
            ),
        )

    return get_bas_record(start, end, signature)


def resolve_review(start, end, signature, resolution_note):
    now = _now()

    with get_connection() as connection:
        connection.execute(
            """
            UPDATE bas_records
            SET resolution_status = 'RESOLVED',
                resolution_note = ?,
                resolved_at = ?,
                updated_at = ?
            WHERE start_date = ?
              AND end_date = ?
              AND signature = ?
            """,
            (
                resolution_note.strip(),
                now,
                now,
                start,
                end,
                signature,
            ),
        )

    return get_bas_record(start, end, signature)


def mark_approved(start, end, signature, ai_status):
    now = _now()

    with get_connection() as connection:
        connection.execute(
            """
            UPDATE bas_records
            SET approval_status = 'APPROVED',
                approved_at = ?,
                rejected_at = NULL,
                updated_at = ?
            WHERE start_date = ?
              AND end_date = ?
              AND signature = ?
            """,
            (now, now, start, end, signature),
        )

    record = get_bas_record(start, end, signature)
    if record is not None:
        record["ai_status_at_approval"] = ai_status
    return record


def mark_rejected(start, end, signature):
    now = _now()

    with get_connection() as connection:
        connection.execute(
            """
            UPDATE bas_records
            SET approval_status = 'REJECTED',
                rejected_at = ?,
                approved_at = NULL,
                updated_at = ?
            WHERE start_date = ?
              AND end_date = ?
              AND signature = ?
            """,
            (now, now, start, end, signature),
        )

    return get_bas_record(start, end, signature)


def get_history(limit=50):
    with get_connection() as connection:
        rows = connection.execute(
            """
            SELECT *
            FROM (
                SELECT
                    b.*,
                    ROW_NUMBER() OVER (
                        PARTITION BY start_date, end_date
                        ORDER BY updated_at DESC, id DESC
                    ) AS period_rank
                FROM bas_records b
            )
            WHERE period_rank = 1
            ORDER BY end_date DESC, updated_at DESC, id DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()

    return [dict(row) for row in rows]


def get_record_by_id(record_id):
    with get_connection() as connection:
        row = connection.execute(
            "SELECT * FROM bas_records WHERE id = ?",
            (record_id,),
        ).fetchone()

    return dict(row) if row else None



def create_user(first_name, last_name, email, password_hash):
    now = _now()

    try:
        with get_connection() as connection:
            cursor = connection.execute(
                """
                INSERT INTO users (
                    first_name,
                    last_name,
                    email,
                    password_hash,
                    created_at
                )
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    first_name.strip(),
                    last_name.strip(),
                    email.strip().lower(),
                    password_hash,
                    now,
                ),
            )
            user_id = cursor.lastrowid
    except sqlite3.IntegrityError:
        return None

    return get_user_by_id(user_id)


def get_user_by_email(email):
    with get_connection() as connection:
        row = connection.execute(
            """
            SELECT *
            FROM users
            WHERE email = ?
            LIMIT 1
            """,
            (email.strip().lower(),),
        ).fetchone()

    return dict(row) if row else None


def get_user_by_id(user_id):
    with get_connection() as connection:
        row = connection.execute(
            """
            SELECT *
            FROM users
            WHERE id = ?
            LIMIT 1
            """,
            (user_id,),
        ).fetchone()

    return dict(row) if row else None


def update_last_login(user_id):
    now = _now()

    with get_connection() as connection:
        connection.execute(
            """
            UPDATE users
            SET last_login_at = ?
            WHERE id = ?
            """,
            (now, user_id),
        )
