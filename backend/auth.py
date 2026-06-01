from __future__ import annotations

import base64
import hashlib
import hmac
import os
import secrets
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

from backend.control import DATA_DIR, init_clients_db, load_clients


AUTH_DB_PATH = Path(os.environ.get("PROMOCASTER_CONTROL_AUTH_DB", DATA_DIR / "control.sqlite3")).resolve()
SESSION_COOKIE = "promocaster_session"
ROLE_LABELS = {"admin": "Administrator", "editor": "Editor", "viewer": "Viewer"}
VALID_ROLES = tuple(ROLE_LABELS)


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat()


def connect() -> sqlite3.Connection:
    AUTH_DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(AUTH_DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def hash_password(password: str, *, salt: bytes | None = None) -> str:
    salt = salt or secrets.token_bytes(16)
    rounds = 260_000
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, rounds)
    return "pbkdf2_sha256${}${}${}".format(
        rounds,
        base64.b64encode(salt).decode("ascii"),
        base64.b64encode(digest).decode("ascii"),
    )


def verify_password(password: str, encoded: str) -> bool:
    if encoded.startswith("$argon2"):
        try:
            from argon2 import PasswordHasher
            from argon2.exceptions import VerifyMismatchError, VerificationError
        except ImportError:
            return False
        try:
            return PasswordHasher().verify(encoded, password)
        except (VerifyMismatchError, VerificationError, ValueError, TypeError):
            return False
    try:
        scheme, rounds, salt, digest = encoded.split("$", 3)
        if scheme != "pbkdf2_sha256":
            return False
        expected = hashlib.pbkdf2_hmac(
            "sha256",
            password.encode("utf-8"),
            base64.b64decode(salt),
            int(rounds),
        )
        return hmac.compare_digest(base64.b64encode(expected).decode("ascii"), digest)
    except (ValueError, TypeError):
        return False


def normalize_role(role: str) -> str:
    role = (role or "viewer").strip().lower()
    return role if role in VALID_ROLES else "viewer"


def row_to_user(row: sqlite3.Row | None) -> dict | None:
    if row is None:
        return None
    user = dict(row)
    user["is_admin"] = bool(user.get("is_admin", 0)) or user.get("role") == "admin"
    user["role"] = "admin" if user["is_admin"] else normalize_role(user.get("role", "viewer"))
    user["active"] = bool(user.get("active", 1)) and not bool(user.get("is_disabled", 0))
    user["force_password_reset"] = bool(user.get("force_password_reset", 0))
    user["role_label"] = ROLE_LABELS.get(user["role"], user["role"].title())
    return user


def init_auth_db() -> None:
    with connect() as conn:
        reset_legacy_auth_schema(conn)
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                email TEXT NOT NULL UNIQUE COLLATE NOCASE,
                password_hash TEXT NOT NULL,
                role TEXT NOT NULL DEFAULT 'admin' CHECK (role IN ('admin', 'editor', 'viewer')),
                active INTEGER NOT NULL DEFAULT 1,
                status TEXT NOT NULL DEFAULT 'verified',
                is_admin INTEGER NOT NULL DEFAULT 0,
                is_disabled INTEGER NOT NULL DEFAULT 0,
                force_password_reset INTEGER NOT NULL DEFAULT 0,
                can_buy_restricted INTEGER NOT NULL DEFAULT 0,
                business_name TEXT NOT NULL DEFAULT '',
                license_number TEXT NOT NULL DEFAULT '',
                license_file_path TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                last_login_at TEXT,
                verified_at TEXT
            );

            CREATE TABLE IF NOT EXISTS user_clients (
                user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                client_id TEXT NOT NULL,
                PRIMARY KEY (user_id, client_id)
            );

            CREATE TABLE IF NOT EXISTS sessions (
                token TEXT PRIMARY KEY,
                user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                expires_at TEXT NOT NULL,
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS admin_login_tokens (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                token_hash TEXT NOT NULL UNIQUE,
                user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                expires_at TEXT NOT NULL,
                used_at TEXT,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );
            """
        )
        migrate_auth_columns(conn)
    init_clients_db()


def reset_legacy_auth_schema(conn: sqlite3.Connection) -> None:
    columns = {row["name"] for row in conn.execute("PRAGMA table_info(users)").fetchall()}
    if not columns or {"status", "is_admin", "is_disabled", "force_password_reset"}.issubset(columns):
        return
    conn.executescript(
        """
        DROP TABLE IF EXISTS sessions;
        DROP TABLE IF EXISTS user_clients;
        DROP TABLE IF EXISTS admin_login_tokens;
        DROP TABLE IF EXISTS users;
        """
    )


def migrate_email_only_users(conn: sqlite3.Connection) -> None:
    columns = [row["name"] for row in conn.execute("PRAGMA table_info(users)").fetchall()]
    if "username" not in columns and "display_name" not in columns:
        return
    conn.execute("PRAGMA foreign_keys = OFF")
    conn.executescript(
        """
        CREATE TABLE users_new (
            id INTEGER PRIMARY KEY,
            email TEXT NOT NULL UNIQUE COLLATE NOCASE,
            role TEXT NOT NULL CHECK (role IN ('admin', 'editor', 'viewer')),
            active INTEGER NOT NULL DEFAULT 1,
            password_hash TEXT NOT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            last_login_at TEXT
        );
        INSERT INTO users_new
            (id, email, role, active, password_hash, created_at, updated_at, last_login_at)
        SELECT id, email, role, active, password_hash, created_at, updated_at, last_login_at
        FROM users;
        DROP TABLE users;
        ALTER TABLE users_new RENAME TO users;
        """
    )
    conn.execute("PRAGMA foreign_keys = ON")


def migrate_auth_columns(conn: sqlite3.Connection) -> None:
    migrate_email_only_users(conn)
    columns = {row["name"] for row in conn.execute("PRAGMA table_info(users)").fetchall()}
    additions = {
        "role": "TEXT NOT NULL DEFAULT 'admin'",
        "active": "INTEGER NOT NULL DEFAULT 1",
        "status": "TEXT NOT NULL DEFAULT 'verified'",
        "is_admin": "INTEGER NOT NULL DEFAULT 0",
        "is_disabled": "INTEGER NOT NULL DEFAULT 0",
        "force_password_reset": "INTEGER NOT NULL DEFAULT 0",
        "can_buy_restricted": "INTEGER NOT NULL DEFAULT 0",
        "business_name": "TEXT NOT NULL DEFAULT ''",
        "license_number": "TEXT NOT NULL DEFAULT ''",
        "license_file_path": "TEXT NOT NULL DEFAULT ''",
        "updated_at": "TEXT NOT NULL DEFAULT ''",
        "last_login_at": "TEXT",
        "verified_at": "TEXT",
    }
    for column, definition in additions.items():
        if column not in columns:
            conn.execute(f"ALTER TABLE users ADD COLUMN {column} {definition}")
    conn.execute("UPDATE users SET is_admin = 1 WHERE role = 'admin'")
    conn.execute("UPDATE users SET is_disabled = 1 WHERE active = 0")
    conn.execute("UPDATE users SET role = 'admin' WHERE is_admin = 1")
    conn.execute("UPDATE users SET updated_at = created_at WHERE updated_at = ''")
    conn.execute("UPDATE users SET verified_at = COALESCE(verified_at, created_at)")


def users_exist() -> bool:
    with connect() as conn:
        return bool(conn.execute("SELECT 1 FROM users LIMIT 1").fetchone())


def consume_admin_login_token(token: str) -> int | None:
    token = token.strip()
    if not token:
        return None
    token_hash = hashlib.sha256(token.encode("utf-8")).hexdigest()
    now = iso(utc_now())
    with connect() as conn:
        row = conn.execute(
            """
            SELECT admin_login_tokens.id, admin_login_tokens.user_id
            FROM admin_login_tokens
            JOIN users ON users.id = admin_login_tokens.user_id
            WHERE admin_login_tokens.token_hash = ?
              AND admin_login_tokens.expires_at > ?
              AND admin_login_tokens.used_at IS NULL
              AND users.is_admin = 1
              AND users.is_disabled = 0
              AND users.status = 'verified'
            """,
            (token_hash, now),
        ).fetchone()
        if not row:
            return None
        conn.execute("UPDATE admin_login_tokens SET used_at = ? WHERE id = ?", (now, row["id"]))
        return int(row["user_id"])


def authenticate(email: str, password: str) -> dict | None:
    login = (email or "").strip()
    with connect() as conn:
        row = conn.execute(
            """
            SELECT * FROM users
            WHERE active = 1
              AND is_disabled = 0
              AND status = 'verified'
              AND email = ? COLLATE NOCASE
            """,
            (login,),
        ).fetchone()
        user = row_to_user(row)
        if not user or not verify_password(password, user["password_hash"]):
            return None
        now = iso(utc_now())
        conn.execute("UPDATE users SET last_login_at = ?, updated_at = ? WHERE id = ?", (now, now, user["id"]))
        user["last_login_at"] = now
        return user


def create_session(user_id: int, remember: bool = False) -> tuple[str, datetime]:
    token = secrets.token_urlsafe(32)
    expires = utc_now() + (timedelta(days=30) if remember else timedelta(hours=12))
    with connect() as conn:
        conn.execute(
            "INSERT INTO sessions (token, user_id, expires_at, created_at) VALUES (?, ?, ?, ?)",
            (token, user_id, iso(expires), iso(utc_now())),
        )
    return token, expires


def delete_session(token: str | None) -> None:
    if not token:
        return
    with connect() as conn:
        conn.execute("DELETE FROM sessions WHERE token = ?", (token,))


def user_for_session(token: str | None) -> dict | None:
    if not token:
        return None
    now = iso(utc_now())
    with connect() as conn:
        row = conn.execute(
            """
            SELECT users.*
            FROM sessions
            JOIN users ON users.id = sessions.user_id
            WHERE sessions.token = ? AND sessions.expires_at > ? AND users.active = 1
              AND users.is_disabled = 0
              AND users.status = 'verified'
            """,
            (token, now),
        ).fetchone()
        conn.execute("DELETE FROM sessions WHERE expires_at <= ?", (now,))
        return row_to_user(row)


def list_users() -> list[dict]:
    with connect() as conn:
        rows = conn.execute("SELECT * FROM users ORDER BY role = 'admin' DESC, email COLLATE NOCASE").fetchall()
    users = [row_to_user(row) for row in rows]
    for user in users:
        user["clients"] = user_client_ids(user["id"])
    return users


def get_user(user_id: int) -> dict | None:
    with connect() as conn:
        user = row_to_user(conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone())
    if user:
        user["clients"] = user_client_ids(user_id)
    return user


def user_client_ids(user_id: int) -> list[str]:
    with connect() as conn:
        rows = conn.execute("SELECT client_id FROM user_clients WHERE user_id = ? ORDER BY client_id", (user_id,)).fetchall()
    return [row["client_id"] for row in rows]


def set_user_clients(user_id: int, client_ids: list[str]) -> None:
    known = set(load_clients())
    selected = sorted({client_id for client_id in client_ids if client_id in known})
    with connect() as conn:
        conn.execute("DELETE FROM user_clients WHERE user_id = ?", (user_id,))
        conn.executemany(
            "INSERT INTO user_clients (user_id, client_id) VALUES (?, ?)",
            [(user_id, client_id) for client_id in selected],
        )


def allowed_client_ids(user: dict | None) -> set[str]:
    if not user:
        return set()
    all_clients = set(load_clients())
    if user["role"] == "admin":
        return all_clients
    return set(user_client_ids(user["id"])) & all_clients


def create_user(data: dict, client_ids: list[str]) -> int:
    now = iso(utc_now())
    role = normalize_role(data.get("role"))
    with connect() as conn:
        cursor = conn.execute(
            """
            INSERT INTO users
                (email, role, active, password_hash, status, is_admin, is_disabled, force_password_reset, verified_at, created_at, updated_at)
            VALUES (?, ?, ?, ?, 'verified', ?, ?, 0, ?, ?, ?)
            """,
            (
                data["email"].strip(),
                role,
                1 if data.get("active", True) else 0,
                hash_password(data["password"]),
                1 if role == "admin" else 0,
                0 if data.get("active", True) else 1,
                now,
                now,
                now,
            ),
        )
        user_id = int(cursor.lastrowid)
    if role != "admin":
        set_user_clients(user_id, client_ids)
    return user_id


def update_user(user_id: int, data: dict, client_ids: list[str]) -> None:
    now = iso(utc_now())
    role = normalize_role(data.get("role"))
    sql = """
        UPDATE users
        SET email = ?, role = ?, active = ?, is_admin = ?, is_disabled = ?, updated_at = ?
        WHERE id = ?
    """
    params: list = [
        data["email"].strip(),
        role,
        1 if data.get("active", True) else 0,
        1 if role == "admin" else 0,
        0 if data.get("active", True) else 1,
        now,
        user_id,
    ]
    if data.get("password"):
        sql = """
            UPDATE users
            SET email = ?, role = ?, active = ?, is_admin = ?, is_disabled = ?, updated_at = ?, password_hash = ?, force_password_reset = 0
            WHERE id = ?
        """
        params = params[:-1] + [hash_password(data["password"]), user_id]
    with connect() as conn:
        conn.execute(sql, tuple(params))
    set_user_clients(user_id, [] if role == "admin" else client_ids)


def set_user_password(user_id: int, password: str) -> None:
    now = iso(utc_now())
    with connect() as conn:
        conn.execute(
            "UPDATE users SET password_hash = ?, force_password_reset = 0, updated_at = ? WHERE id = ?",
            (hash_password(password), now, user_id),
        )
