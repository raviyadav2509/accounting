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
            SELECT b.*
            FROM bas_records b
            INNER JOIN (
                SELECT start_date, end_date, MAX(updated_at) AS latest_updated
                FROM bas_records
                GROUP BY start_date, end_date
            ) latest
              ON latest.start_date = b.start_date
             AND latest.end_date = b.end_date
             AND latest.latest_updated = b.updated_at
            ORDER BY b.end_date DESC, b.updated_at DESC
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
