import json
import sqlite3
from datetime import datetime

from config import DATABASE_FILE


def _now():
    return datetime.now().isoformat(timespec="seconds")


def get_connection():
    connection = sqlite3.connect(DATABASE_FILE)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    return connection


def _table_exists(connection, table_name):
    row = connection.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name = ?",
        (table_name,),
    ).fetchone()
    return row is not None


def _column_names(connection, table_name):
    return {
        row["name"]
        for row in connection.execute(f"PRAGMA table_info({table_name})").fetchall()
    }


def _create_bas_records_table(connection, table_name="bas_records"):
    connection.execute(
        f"""
        CREATE TABLE IF NOT EXISTS {table_name} (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            client_id INTEGER,
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
            lodged_at TEXT,
            lodgement_reference TEXT,

            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,

            FOREIGN KEY (client_id) REFERENCES clients(id) ON DELETE CASCADE,
            UNIQUE(client_id, start_date, end_date, signature)
        )
        """
    )


def _migrate_bas_records(connection):
    if not _table_exists(connection, "bas_records"):
        _create_bas_records_table(connection)
        return

    columns = _column_names(connection, "bas_records")
    required = {
        "client_id",
        "lodged_at",
        "lodgement_reference",
    }

    if required.issubset(columns):
        return

    _create_bas_records_table(connection, "bas_records_new")

    old_columns = _column_names(connection, "bas_records")
    target_columns = [
        "id",
        "client_id",
        "start_date",
        "end_date",
        "signature",
        "g1",
        "gst_sales",
        "gst_purchases",
        "w1",
        "w2",
        "gst_position",
        "payable",
        "review_status",
        "review_text",
        "reviewed_at",
        "resolution_status",
        "resolution_note",
        "resolved_at",
        "approval_status",
        "approved_at",
        "rejected_at",
        "lodged_at",
        "lodgement_reference",
        "created_at",
        "updated_at",
    ]

    select_parts = []
    for column in target_columns:
        if column in old_columns:
            select_parts.append(column)
        else:
            select_parts.append(f"NULL AS {column}")

    connection.execute(
        f"""
        INSERT INTO bas_records_new ({", ".join(target_columns)})
        SELECT {", ".join(select_parts)}
        FROM bas_records
        """
    )
    connection.execute("DROP TABLE bas_records")
    connection.execute("ALTER TABLE bas_records_new RENAME TO bas_records")


def init_db():
    with get_connection() as connection:
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                firm_id INTEGER,
                first_name TEXT NOT NULL,
                last_name TEXT NOT NULL,
                email TEXT NOT NULL UNIQUE COLLATE NOCASE,
                password_hash TEXT NOT NULL,
                is_active INTEGER NOT NULL DEFAULT 1,
                email_verified_at TEXT,
                email_verification_token_hash TEXT,
                email_verification_expires_at TEXT,
                email_verification_sent_at TEXT,
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
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS accounting_firms (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                firm_name TEXT NOT NULL,
                director_name TEXT NOT NULL,
                abn TEXT,
                acn TEXT,
                address TEXT,
                email TEXT,
                phone TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )

        if "firm_id" not in _column_names(connection, "users"):
            connection.execute(
                "ALTER TABLE users ADD COLUMN firm_id INTEGER"
            )

        connection.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_users_firm
            ON users(firm_id)
            """
        )

        user_columns = _column_names(connection, "users")

        if "email_verified_at" not in user_columns:
            connection.execute(
                "ALTER TABLE users ADD COLUMN email_verified_at TEXT"
            )
            connection.execute(
                """
                UPDATE users
                SET email_verified_at = COALESCE(created_at, ?)
                WHERE email_verified_at IS NULL
                """,
                (_now(),),
            )

        if "email_verification_token_hash" not in user_columns:
            connection.execute(
                "ALTER TABLE users ADD COLUMN email_verification_token_hash TEXT"
            )

        if "email_verification_expires_at" not in user_columns:
            connection.execute(
                "ALTER TABLE users ADD COLUMN email_verification_expires_at TEXT"
            )

        if "email_verification_sent_at" not in user_columns:
            connection.execute(
                "ALTER TABLE users ADD COLUMN email_verification_sent_at TEXT"
            )

        connection.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_users_verification_token
            ON users(email_verification_token_hash)
            """
        )


        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS clients (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                owner_user_id INTEGER NOT NULL,
                company_name TEXT NOT NULL,
                entity_type TEXT NOT NULL DEFAULT 'UNSPECIFIED',
                legal_name TEXT,
                abn TEXT,
                acn TEXT,
                address TEXT,
                email TEXT,
                phone TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                FOREIGN KEY (owner_user_id) REFERENCES users(id) ON DELETE CASCADE
            )
            """
        )
        connection.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_clients_owner
            ON clients(owner_user_id)
            """
        )

        if "entity_type" not in _column_names(connection, "clients"):
            connection.execute(
                "ALTER TABLE clients ADD COLUMN entity_type TEXT NOT NULL DEFAULT 'UNSPECIFIED'"
            )

        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS tax_returns (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                client_id INTEGER NOT NULL,
                financial_year TEXT NOT NULL,
                start_date TEXT NOT NULL,
                end_date TEXT NOT NULL,
                entity_type TEXT NOT NULL,
                accounting_profit REAL,
                tax_rate REAL,
                taxable_income REAL,
                estimated_tax REAL,
                review_status TEXT,
                review_text TEXT,
                reviewed_at TEXT,
                approval_status TEXT,
                approved_at TEXT,
                lodged_at TEXT,
                lodgement_reference TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                FOREIGN KEY (client_id) REFERENCES clients(id) ON DELETE CASCADE,
                UNIQUE(client_id, financial_year, entity_type)
            )
            """
        )
        if "lodged_at" not in _column_names(connection, "tax_returns"):
            connection.execute(
                "ALTER TABLE tax_returns ADD COLUMN lodged_at TEXT"
            )

        if "lodgement_reference" not in _column_names(connection, "tax_returns"):
            connection.execute(
                "ALTER TABLE tax_returns ADD COLUMN lodgement_reference TEXT"
            )

        connection.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_tax_returns_client_year
            ON tax_returns(client_id, financial_year)
            """
        )
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS tax_return_adjustments (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                tax_return_id INTEGER NOT NULL,
                adjustment_type TEXT NOT NULL,
                category TEXT NOT NULL,
                description TEXT NOT NULL,
                amount REAL NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                FOREIGN KEY (tax_return_id) REFERENCES tax_returns(id) ON DELETE CASCADE
            )
            """
        )
        connection.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_tax_adjustments_return
            ON tax_return_adjustments(tax_return_id, id)
            """
        )

        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS qbo_connections (
                client_id INTEGER PRIMARY KEY,
                realm_id TEXT NOT NULL,
                token_json TEXT NOT NULL,
                connected_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                FOREIGN KEY (client_id) REFERENCES clients(id) ON DELETE CASCADE
            )
            """
        )

        _migrate_bas_records(connection)

        connection.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_bas_records_client_period
            ON bas_records(client_id, start_date, end_date)
            """
        )
        connection.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_bas_records_client_updated
            ON bas_records(client_id, updated_at)
            """
        )


def create_user(
    first_name,
    last_name,
    email,
    password_hash,
    firm_name,
    director_name,
    firm_abn=None,
    firm_acn=None,
    firm_address=None,
    firm_email=None,
    firm_phone=None,
):
    now = _now()

    try:
        with get_connection() as connection:
            firm_cursor = connection.execute(
                """
                INSERT INTO accounting_firms (
                    firm_name,
                    director_name,
                    abn,
                    acn,
                    address,
                    email,
                    phone,
                    created_at,
                    updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    firm_name.strip(),
                    director_name.strip(),
                    (firm_abn or "").strip() or None,
                    (firm_acn or "").strip() or None,
                    (firm_address or "").strip() or None,
                    (firm_email or "").strip().lower() or None,
                    (firm_phone or "").strip() or None,
                    now,
                    now,
                ),
            )
            firm_id = firm_cursor.lastrowid

            cursor = connection.execute(
                """
                INSERT INTO users (
                    firm_id,
                    first_name,
                    last_name,
                    email,
                    password_hash,
                    created_at
                )
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    firm_id,
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


def set_email_verification(
    user_id,
    token_hash,
    expires_at,
):
    now = _now()

    with get_connection() as connection:
        connection.execute(
            """
            UPDATE users
            SET email_verification_token_hash = ?,
                email_verification_expires_at = ?,
                email_verification_sent_at = ?
            WHERE id = ?
              AND email_verified_at IS NULL
            """,
            (
                token_hash,
                expires_at,
                now,
                user_id,
            ),
        )

    return get_user_by_id(user_id)


def get_user_by_verification_token_hash(token_hash):
    with get_connection() as connection:
        row = connection.execute(
            """
            SELECT *
            FROM users
            WHERE email_verification_token_hash = ?
            LIMIT 1
            """,
            (token_hash,),
        ).fetchone()

    return dict(row) if row else None


def mark_email_verified(user_id):
    now = _now()

    with get_connection() as connection:
        connection.execute(
            """
            UPDATE users
            SET email_verified_at = ?,
                email_verification_token_hash = NULL,
                email_verification_expires_at = NULL,
                email_verification_sent_at = NULL
            WHERE id = ?
            """,
            (now, user_id),
        )

    return get_user_by_id(user_id)


def update_unverified_user_email(user_id, email):
    normalized_email = email.strip().lower()

    try:
        with get_connection() as connection:
            user = connection.execute(
                """
                SELECT id, firm_id
                FROM users
                WHERE id = ?
                  AND email_verified_at IS NULL
                LIMIT 1
                """,
                (user_id,),
            ).fetchone()

            if not user:
                return None

            connection.execute(
                """
                UPDATE users
                SET email = ?,
                    email_verification_token_hash = NULL,
                    email_verification_expires_at = NULL,
                    email_verification_sent_at = NULL
                WHERE id = ?
                """,
                (normalized_email, user_id),
            )

            if user["firm_id"]:
                connection.execute(
                    """
                    UPDATE accounting_firms
                    SET email = ?,
                        updated_at = ?
                    WHERE id = ?
                    """,
                    (normalized_email, _now(), user["firm_id"]),
                )
    except sqlite3.IntegrityError:
        return None

    return get_user_by_id(user_id)


def get_user_by_email(email):
    with get_connection() as connection:
        row = connection.execute(
            """
            SELECT
                u.*,
                f.firm_name,
                f.director_name,
                f.abn AS firm_abn,
                f.acn AS firm_acn,
                f.address AS firm_address,
                f.email AS firm_email,
                f.phone AS firm_phone
            FROM users u
            LEFT JOIN accounting_firms f ON f.id = u.firm_id
            WHERE u.email = ?
            LIMIT 1
            """,
            (email.strip().lower(),),
        ).fetchone()

    return dict(row) if row else None


def get_user_by_id(user_id):
    if not user_id:
        return None

    with get_connection() as connection:
        row = connection.execute(
            """
            SELECT
                u.*,
                f.firm_name,
                f.director_name,
                f.abn AS firm_abn,
                f.acn AS firm_acn,
                f.address AS firm_address,
                f.email AS firm_email,
                f.phone AS firm_phone
            FROM users u
            LEFT JOIN accounting_firms f ON f.id = u.firm_id
            WHERE u.id = ?
            LIMIT 1
            """,
            (user_id,),
        ).fetchone()

    return dict(row) if row else None


def get_firm_for_user(user_id):
    user = get_user_by_id(user_id)
    if not user or not user.get("firm_id"):
        return None

    return {
        "id": user["firm_id"],
        "firm_name": user.get("firm_name"),
        "director_name": user.get("director_name"),
        "abn": user.get("firm_abn"),
        "acn": user.get("firm_acn"),
        "address": user.get("firm_address"),
        "email": user.get("firm_email"),
        "phone": user.get("firm_phone"),
    }


def update_firm_for_user(
    user_id,
    firm_name,
    director_name,
    abn=None,
    acn=None,
    address=None,
    email=None,
    phone=None,
):
    now = _now()
    user = get_user_by_id(user_id)

    with get_connection() as connection:
        if user and user.get("firm_id"):
            connection.execute(
                """
                UPDATE accounting_firms
                SET firm_name = ?,
                    director_name = ?,
                    abn = ?,
                    acn = ?,
                    address = ?,
                    email = ?,
                    phone = ?,
                    updated_at = ?
                WHERE id = ?
                """,
                (
                    firm_name.strip(),
                    director_name.strip(),
                    (abn or "").strip() or None,
                    (acn or "").strip() or None,
                    (address or "").strip() or None,
                    (email or "").strip().lower() or None,
                    (phone or "").strip() or None,
                    now,
                    user["firm_id"],
                ),
            )
        else:
            cursor = connection.execute(
                """
                INSERT INTO accounting_firms (
                    firm_name,
                    director_name,
                    abn,
                    acn,
                    address,
                    email,
                    phone,
                    created_at,
                    updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    firm_name.strip(),
                    director_name.strip(),
                    (abn or "").strip() or None,
                    (acn or "").strip() or None,
                    (address or "").strip() or None,
                    (email or "").strip().lower() or None,
                    (phone or "").strip() or None,
                    now,
                    now,
                ),
            )
            connection.execute(
                "UPDATE users SET firm_id = ? WHERE id = ?",
                (cursor.lastrowid, user_id),
            )

    return get_firm_for_user(user_id)


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


def create_client(owner_user_id, company_name, entity_type="UNSPECIFIED", legal_name=None,
                  abn=None, acn=None, address=None, email=None, phone=None):
    now = _now()

    with get_connection() as connection:
        cursor = connection.execute(
            """
            INSERT INTO clients (
                owner_user_id,
                company_name,
                entity_type,
                legal_name,
                abn,
                acn,
                address,
                email,
                phone,
                created_at,
                updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                owner_user_id,
                company_name.strip(),
                (entity_type or "UNSPECIFIED").strip().upper(),
                (legal_name or "").strip() or None,
                (abn or "").strip() or None,
                (acn or "").strip() or None,
                (address or "").strip() or None,
                (email or "").strip() or None,
                (phone or "").strip() or None,
                now,
                now,
            ),
        )
        client_id = cursor.lastrowid

    return get_client_for_user(client_id, owner_user_id)


def update_client(client_id, owner_user_id, **fields):
    allowed = {
        "company_name",
        "entity_type",
        "legal_name",
        "abn",
        "acn",
        "address",
        "email",
        "phone",
    }
    updates = []
    values = []

    for key, value in fields.items():
        if key not in allowed:
            continue
        updates.append(f"{key} = ?")
        values.append(value.strip() if isinstance(value, str) and value.strip() else None)

    if not updates:
        return get_client_for_user(client_id, owner_user_id)

    updates.append("updated_at = ?")
    values.append(_now())
    values.extend([client_id, owner_user_id])

    with get_connection() as connection:
        connection.execute(
            f"""
            UPDATE clients
            SET {", ".join(updates)}
            WHERE id = ?
              AND owner_user_id = ?
            """,
            values,
        )

    return get_client_for_user(client_id, owner_user_id)


def get_clients_for_user(owner_user_id):
    with get_connection() as connection:
        rows = connection.execute(
            """
            SELECT c.*,
                   CASE WHEN q.client_id IS NULL THEN 0 ELSE 1 END AS qbo_connected
            FROM clients c
            LEFT JOIN qbo_connections q ON q.client_id = c.id
            WHERE c.owner_user_id = ?
            ORDER BY c.company_name COLLATE NOCASE
            """,
            (owner_user_id,),
        ).fetchall()

    return [dict(row) for row in rows]


def get_client_for_user(client_id, owner_user_id):
    if not client_id or not owner_user_id:
        return None

    with get_connection() as connection:
        row = connection.execute(
            """
            SELECT c.*,
                   CASE WHEN q.client_id IS NULL THEN 0 ELSE 1 END AS qbo_connected,
                   q.realm_id
            FROM clients c
            LEFT JOIN qbo_connections q ON q.client_id = c.id
            WHERE c.id = ?
              AND c.owner_user_id = ?
            LIMIT 1
            """,
            (client_id, owner_user_id),
        ).fetchone()

    return dict(row) if row else None


def get_client_by_id(client_id):
    with get_connection() as connection:
        row = connection.execute(
            "SELECT * FROM clients WHERE id = ? LIMIT 1",
            (client_id,),
        ).fetchone()

    return dict(row) if row else None


def save_qbo_connection(client_id, realm_id, token_data):
    now = _now()
    payload = dict(token_data)
    payload["realmId"] = realm_id

    with get_connection() as connection:
        connection.execute(
            """
            INSERT INTO qbo_connections (
                client_id,
                realm_id,
                token_json,
                connected_at,
                updated_at
            )
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(client_id)
            DO UPDATE SET
                realm_id = excluded.realm_id,
                token_json = excluded.token_json,
                updated_at = excluded.updated_at
            """,
            (
                client_id,
                realm_id,
                json.dumps(payload),
                now,
                now,
            ),
        )


def get_qbo_connection(client_id):
    with get_connection() as connection:
        row = connection.execute(
            """
            SELECT *
            FROM qbo_connections
            WHERE client_id = ?
            LIMIT 1
            """,
            (client_id,),
        ).fetchone()

    if not row:
        return None

    result = dict(row)
    result["tokens"] = json.loads(result["token_json"])
    return result


def claim_legacy_bas_records(client_id):
    with get_connection() as connection:
        connection.execute(
            """
            UPDATE bas_records
            SET client_id = ?
            WHERE client_id IS NULL
            """,
            (client_id,),
        )


def save_bas_snapshot(client_id, bas, signature):
    now = _now()

    with get_connection() as connection:
        connection.execute(
            """
            INSERT INTO bas_records (
                client_id,
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
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(client_id, start_date, end_date, signature)
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
                client_id,
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

    return get_bas_record(client_id, bas["start"], bas["end"], signature)


def get_bas_record(client_id, start, end, signature):
    with get_connection() as connection:
        row = connection.execute(
            """
            SELECT *
            FROM bas_records
            WHERE client_id = ?
              AND start_date = ?
              AND end_date = ?
              AND signature = ?
            LIMIT 1
            """,
            (client_id, start, end, signature),
        ).fetchone()

    return dict(row) if row else None


def update_review(client_id, start, end, signature, status, review_text):
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
            WHERE client_id = ?
              AND start_date = ?
              AND end_date = ?
              AND signature = ?
            """,
            (
                status,
                review_text,
                now,
                now,
                client_id,
                start,
                end,
                signature,
            ),
        )

    return get_bas_record(client_id, start, end, signature)


def resolve_review(client_id, start, end, signature, resolution_note):
    now = _now()

    with get_connection() as connection:
        connection.execute(
            """
            UPDATE bas_records
            SET resolution_status = 'RESOLVED',
                resolution_note = ?,
                resolved_at = ?,
                updated_at = ?
            WHERE client_id = ?
              AND start_date = ?
              AND end_date = ?
              AND signature = ?
            """,
            (
                resolution_note.strip(),
                now,
                now,
                client_id,
                start,
                end,
                signature,
            ),
        )

    return get_bas_record(client_id, start, end, signature)


def mark_approved(client_id, start, end, signature, ai_status):
    now = _now()

    with get_connection() as connection:
        connection.execute(
            """
            UPDATE bas_records
            SET approval_status = 'APPROVED',
                approved_at = ?,
                rejected_at = NULL,
                updated_at = ?
            WHERE client_id = ?
              AND start_date = ?
              AND end_date = ?
              AND signature = ?
            """,
            (now, now, client_id, start, end, signature),
        )

    record = get_bas_record(client_id, start, end, signature)
    if record is not None:
        record["ai_status_at_approval"] = ai_status
    return record


def mark_rejected(client_id, start, end, signature):
    now = _now()

    with get_connection() as connection:
        connection.execute(
            """
            UPDATE bas_records
            SET approval_status = 'REJECTED',
                rejected_at = ?,
                approved_at = NULL,
                updated_at = ?
            WHERE client_id = ?
              AND start_date = ?
              AND end_date = ?
              AND signature = ?
            """,
            (now, now, client_id, start, end, signature),
        )

    return get_bas_record(client_id, start, end, signature)


def reopen_bas(client_id, start, end, signature):
    now = _now()

    with get_connection() as connection:
        connection.execute(
            """
            UPDATE bas_records
            SET approval_status = NULL,
                approved_at = NULL,
                rejected_at = NULL,
                updated_at = ?
            WHERE client_id = ?
              AND start_date = ?
              AND end_date = ?
              AND signature = ?
              AND lodged_at IS NULL
              AND approval_status = 'APPROVED'
            """,
            (
                now,
                client_id,
                start,
                end,
                signature,
            ),
        )

    return get_bas_record(client_id, start, end, signature)


def mark_lodged(client_id, start, end, signature, lodgement_reference=None):
    now = _now()

    with get_connection() as connection:
        connection.execute(
            """
            UPDATE bas_records
            SET approval_status = 'LODGED',
                lodged_at = ?,
                lodgement_reference = ?,
                updated_at = ?
            WHERE client_id = ?
              AND start_date = ?
              AND end_date = ?
              AND signature = ?
            """,
            (
                now,
                lodgement_reference,
                now,
                client_id,
                start,
                end,
                signature,
            ),
        )

    return get_bas_record(client_id, start, end, signature)


def get_history(client_id, limit=50):
    with get_connection() as connection:
        rows = connection.execute(
            """
            SELECT *
            FROM (
                SELECT
                    b.*,
                    ROW_NUMBER() OVER (
                        PARTITION BY client_id, start_date, end_date
                        ORDER BY updated_at DESC, id DESC
                    ) AS period_rank
                FROM bas_records b
                WHERE client_id = ?
            )
            WHERE period_rank = 1
            ORDER BY end_date DESC, updated_at DESC, id DESC
            LIMIT ?
            """,
            (client_id, limit),
        ).fetchall()

    return [dict(row) for row in rows]


def get_record_by_id(client_id, record_id):
    with get_connection() as connection:
        row = connection.execute(
            """
            SELECT *
            FROM bas_records
            WHERE id = ?
              AND client_id = ?
            """,
            (record_id, client_id),
        ).fetchone()

    return dict(row) if row else None


def get_history_for_user(owner_user_id, limit=200):
    with get_connection() as connection:
        rows = connection.execute(
            """
            SELECT *
            FROM (
                SELECT
                    b.*,
                    c.company_name AS client_name,
                    c.abn AS client_abn,
                    ROW_NUMBER() OVER (
                        PARTITION BY b.client_id, b.start_date, b.end_date
                        ORDER BY b.updated_at DESC, b.id DESC
                    ) AS period_rank
                FROM bas_records b
                JOIN clients c ON c.id = b.client_id
                WHERE c.owner_user_id = ?
            )
            WHERE period_rank = 1
            ORDER BY end_date DESC, updated_at DESC, id DESC
            LIMIT ?
            """,
            (owner_user_id, limit),
        ).fetchall()

    return [dict(row) for row in rows]


def get_record_for_user(owner_user_id, record_id):
    with get_connection() as connection:
        row = connection.execute(
            """
            SELECT
                b.*,
                c.company_name AS client_name,
                c.abn AS client_abn
            FROM bas_records b
            JOIN clients c ON c.id = b.client_id
            WHERE b.id = ?
              AND c.owner_user_id = ?
            LIMIT 1
            """,
            (record_id, owner_user_id),
        ).fetchone()

    return dict(row) if row else None



def create_tax_return(client_id, financial_year, start_date, end_date, entity_type):
    now = _now()

    with get_connection() as connection:
        connection.execute(
            """
            INSERT INTO tax_returns (
                client_id,
                financial_year,
                start_date,
                end_date,
                entity_type,
                created_at,
                updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(client_id, financial_year, entity_type)
            DO NOTHING
            """,
            (
                client_id,
                financial_year,
                start_date,
                end_date,
                entity_type,
                now,
                now,
            ),
        )

    return get_tax_return_by_year(client_id, financial_year, entity_type)


def get_tax_return_by_year(client_id, financial_year, entity_type="COMPANY"):
    with get_connection() as connection:
        row = connection.execute(
            """
            SELECT *
            FROM tax_returns
            WHERE client_id = ?
              AND financial_year = ?
              AND entity_type = ?
            LIMIT 1
            """,
            (client_id, financial_year, entity_type),
        ).fetchone()

    return dict(row) if row else None


def get_tax_return(client_id, tax_return_id):
    with get_connection() as connection:
        row = connection.execute(
            """
            SELECT *
            FROM tax_returns
            WHERE id = ?
              AND client_id = ?
            LIMIT 1
            """,
            (tax_return_id, client_id),
        ).fetchone()

    return dict(row) if row else None


def get_tax_returns_for_client(client_id, limit=50):
    with get_connection() as connection:
        rows = connection.execute(
            """
            SELECT *
            FROM tax_returns
            WHERE client_id = ?
            ORDER BY end_date DESC, updated_at DESC, id DESC
            LIMIT ?
            """,
            (client_id, limit),
        ).fetchall()

    return [dict(row) for row in rows]


def get_tax_returns_for_user(owner_user_id, limit=250):
    with get_connection() as connection:
        rows = connection.execute(
            """
            SELECT
                t.*,
                c.company_name AS client_name,
                c.abn AS client_abn
            FROM tax_returns t
            JOIN clients c ON c.id = t.client_id
            WHERE c.owner_user_id = ?
            ORDER BY t.end_date DESC, t.updated_at DESC, t.id DESC
            LIMIT ?
            """,
            (owner_user_id, limit),
        ).fetchall()

    return [dict(row) for row in rows]


def update_tax_return(client_id, tax_return_id, **fields):
    allowed = {
        "accounting_profit",
        "tax_rate",
        "taxable_income",
        "estimated_tax",
        "review_status",
        "review_text",
        "reviewed_at",
        "approval_status",
        "approved_at",
        "lodged_at",
        "lodgement_reference",
    }
    updates = []
    values = []

    for key, value in fields.items():
        if key not in allowed:
            continue
        updates.append(f"{key} = ?")
        values.append(value)

    if not updates:
        return get_tax_return(client_id, tax_return_id)

    updates.append("updated_at = ?")
    values.append(_now())
    values.extend([tax_return_id, client_id])

    with get_connection() as connection:
        connection.execute(
            f"""
            UPDATE tax_returns
            SET {", ".join(updates)}
            WHERE id = ?
              AND client_id = ?
            """,
            values,
        )

    return get_tax_return(client_id, tax_return_id)


def mark_tax_return_lodged(
    client_id,
    tax_return_id,
    lodgement_reference=None,
):
    now = _now()

    with get_connection() as connection:
        connection.execute(
            """
            UPDATE tax_returns
            SET approval_status = 'LODGED',
                lodged_at = ?,
                lodgement_reference = ?,
                updated_at = ?
            WHERE id = ?
              AND client_id = ?
              AND approval_status = 'APPROVED'
            """,
            (
                now,
                lodgement_reference,
                now,
                tax_return_id,
                client_id,
            ),
        )

    return get_tax_return(client_id, tax_return_id)


def get_tax_adjustments(client_id, tax_return_id):
    with get_connection() as connection:
        rows = connection.execute(
            """
            SELECT a.*
            FROM tax_return_adjustments a
            JOIN tax_returns t ON t.id = a.tax_return_id
            WHERE a.tax_return_id = ?
              AND t.client_id = ?
            ORDER BY a.id
            """,
            (tax_return_id, client_id),
        ).fetchall()

    return [dict(row) for row in rows]


def add_tax_adjustment(
    client_id,
    tax_return_id,
    adjustment_type,
    category,
    description,
    amount,
):
    now = _now()

    with get_connection() as connection:
        parent = connection.execute(
            """
            SELECT id
            FROM tax_returns
            WHERE id = ?
              AND client_id = ?
            LIMIT 1
            """,
            (tax_return_id, client_id),
        ).fetchone()

        if not parent:
            return None

        cursor = connection.execute(
            """
            INSERT INTO tax_return_adjustments (
                tax_return_id,
                adjustment_type,
                category,
                description,
                amount,
                created_at,
                updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                tax_return_id,
                adjustment_type,
                category,
                description,
                amount,
                now,
                now,
            ),
        )
        adjustment_id = cursor.lastrowid

    return adjustment_id


def delete_tax_adjustment(client_id, tax_return_id, adjustment_id):
    with get_connection() as connection:
        cursor = connection.execute(
            """
            DELETE FROM tax_return_adjustments
            WHERE id = ?
              AND tax_return_id = ?
              AND tax_return_id IN (
                  SELECT id
                  FROM tax_returns
                  WHERE id = ?
                    AND client_id = ?
              )
            """,
            (
                adjustment_id,
                tax_return_id,
                tax_return_id,
                client_id,
            ),
        )

    return cursor.rowcount > 0
