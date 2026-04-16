#!/usr/bin/env python3
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import urlparse, parse_qs
from pathlib import Path
from datetime import datetime, timezone
from http import cookies
import json
import os
import hashlib
import hmac
import secrets

import psycopg
from psycopg.rows import dict_row

from store_scrapers import fetch_product_snapshot


def load_env_file():
    env_path = Path(__file__).with_name(".env")
    if not env_path.exists():
        return

    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue

        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip("\"'")
        os.environ.setdefault(key, value)


load_env_file()

DB_HOST = os.getenv("DB_HOST", "localhost")
DB_PORT = int(os.getenv("DB_PORT", "5432"))
DB_NAME = os.getenv("DB_NAME", "pricecompare")
DB_USER = os.getenv("DB_USER", "postgres")
DB_PASSWORD = os.getenv("DB_PASSWORD", "")
APP_HOST = os.getenv("APP_HOST", "127.0.0.1")
APP_PORT = int(os.getenv("APP_PORT", "8080"))
SESSION_COOKIE_NAME = "pricewatch_session"
SESSION_TTL_SECONDS = 60 * 60 * 24 * 30


def utc_now():
    return datetime.now(timezone.utc).replace(microsecond=0)


def get_conn():
    return psycopg.connect(
        host=DB_HOST,
        port=DB_PORT,
        dbname=DB_NAME,
        user=DB_USER,
        password=DB_PASSWORD,
        row_factory=dict_row,
    )


def init_db():
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                CREATE TABLE IF NOT EXISTS users (
                    id SERIAL PRIMARY KEY,
                    username TEXT NOT NULL UNIQUE,
                    email TEXT UNIQUE,
                    first_name TEXT,
                    last_name TEXT,
                    password_hash TEXT NOT NULL,
                    created_at TIMESTAMPTZ NOT NULL
                );
            """)

            cur.execute("""
                CREATE TABLE IF NOT EXISTS user_sessions (
                    id SERIAL PRIMARY KEY,
                    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                    token_hash TEXT NOT NULL UNIQUE,
                    created_at TIMESTAMPTZ NOT NULL,
                    expires_at TIMESTAMPTZ NOT NULL
                );
            """)

            cur.execute("""
                CREATE TABLE IF NOT EXISTS watched_products (
                    id SERIAL PRIMARY KEY,
                    product_id TEXT NOT NULL,
                    product_url TEXT NOT NULL,
                    name TEXT,
                    brand TEXT,
                    current_price DOUBLE PRECISION,
                    previous_price DOUBLE PRECISION,
                    was_price DOUBLE PRECISION,
                    cup_price TEXT,
                    in_stock BOOLEAN,
                    image_url TEXT,
                    last_checked_at TIMESTAMPTZ,
                    has_drop BOOLEAN DEFAULT FALSE,
                    created_at TIMESTAMPTZ NOT NULL
                );
            """)

            cur.execute("""
                CREATE TABLE IF NOT EXISTS price_history (
                    id SERIAL PRIMARY KEY,
                    user_id INTEGER REFERENCES users(id) ON DELETE CASCADE,
                    product_id TEXT NOT NULL,
                    price DOUBLE PRECISION,
                    recorded_at TIMESTAMPTZ NOT NULL
                );
            """)

            cur.execute("""
                ALTER TABLE watched_products
                ADD COLUMN IF NOT EXISTS user_id INTEGER REFERENCES users(id) ON DELETE CASCADE
            """)

            cur.execute("""
                ALTER TABLE price_history
                ADD COLUMN IF NOT EXISTS user_id INTEGER REFERENCES users(id) ON DELETE CASCADE
            """)

            cur.execute("""
                DO $$
                BEGIN
                    IF EXISTS (
                        SELECT 1
                        FROM pg_constraint
                        WHERE conname = 'price_history_product_id_fkey'
                    ) THEN
                        ALTER TABLE price_history DROP CONSTRAINT price_history_product_id_fkey;
                    END IF;
                END
                $$;
            """)

            cur.execute("""
                DO $$
                BEGIN
                    IF EXISTS (
                        SELECT 1
                        FROM pg_constraint
                        WHERE conname = 'watched_products_product_id_key'
                    ) THEN
                        ALTER TABLE watched_products DROP CONSTRAINT watched_products_product_id_key;
                    END IF;
                END
                $$;
            """)

            cur.execute("""
                ALTER TABLE price_history
                ALTER COLUMN product_id SET NOT NULL
            """)

            cur.execute("""
                CREATE UNIQUE INDEX IF NOT EXISTS watched_products_scope_product_id_idx
                ON watched_products ((COALESCE(user_id, 0)), product_id)
            """)

            cur.execute("""
                CREATE INDEX IF NOT EXISTS price_history_scope_product_id_idx
                ON price_history ((COALESCE(user_id, 0)), product_id, recorded_at)
            """)
        conn.commit()


def normalise_username(value):
    value = (value or "").strip().lower()
    return value or None


def normalise_email(value):
    value = (value or "").strip().lower()
    return value or None


def hash_password(password, *, salt=None):
    if not password:
        raise ValueError("Password is required.")
    salt = salt or secrets.token_bytes(16)
    derived = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, 200_000)
    return f"{salt.hex()}${derived.hex()}"


def verify_password(password, stored_hash):
    try:
        salt_hex, digest_hex = stored_hash.split("$", 1)
    except ValueError:
        return False
    expected = bytes.fromhex(digest_hex)
    actual = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        bytes.fromhex(salt_hex),
        200_000,
    )
    return hmac.compare_digest(actual, expected)


def sanitise_user_row(row):
    if not row:
        return None
    return {
        "id": row["id"],
        "username": row["username"],
        "email": row["email"],
        "first_name": row["first_name"],
        "last_name": row["last_name"],
        "created_at": row["created_at"],
    }


def create_user(*, username, email, first_name, last_name, password):
    username = normalise_username(username)
    email = normalise_email(email)
    first_name = (first_name or "").strip() or None
    last_name = (last_name or "").strip() or None

    if not username:
        raise ValueError("Username is required.")
    if len(password or "") < 6:
        raise ValueError("Password must be at least 6 characters.")

    password_hash = hash_password(password)
    now = utc_now()

    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO users (username, email, first_name, last_name, password_hash, created_at)
                VALUES (%s, %s, %s, %s, %s, %s)
                RETURNING id, username, email, first_name, last_name, created_at
                """,
                (username, email, first_name, last_name, password_hash, now),
            )
            user = cur.fetchone()
        conn.commit()
    return user


def authenticate_user(*, identifier, password):
    identifier = (identifier or "").strip().lower()
    if not identifier or not password:
        raise ValueError("Username/email and password are required.")

    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT id, username, email, first_name, last_name, password_hash, created_at
                FROM users
                WHERE username = %s OR email = %s
                LIMIT 1
                """,
                (identifier, identifier),
            )
            user = cur.fetchone()

    if not user or not verify_password(password, user["password_hash"]):
        raise ValueError("Invalid username/email or password.")
    return user


def create_session(user_id):
    raw_token = secrets.token_urlsafe(32)
    token_hash = hashlib.sha256(raw_token.encode("utf-8")).hexdigest()
    now = utc_now()
    expires_at = datetime.fromtimestamp(
        now.timestamp() + SESSION_TTL_SECONDS,
        tz=timezone.utc,
    ).replace(microsecond=0)

    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO user_sessions (user_id, token_hash, created_at, expires_at)
                VALUES (%s, %s, %s, %s)
                """,
                (user_id, token_hash, now, expires_at),
            )
        conn.commit()

    return raw_token, expires_at


def get_user_by_session_token(raw_token):
    if not raw_token:
        return None

    token_hash = hashlib.sha256(raw_token.encode("utf-8")).hexdigest()
    now = utc_now()
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT u.id, u.username, u.email, u.first_name, u.last_name, u.created_at
                FROM user_sessions s
                JOIN users u ON u.id = s.user_id
                WHERE s.token_hash = %s AND s.expires_at > %s
                LIMIT 1
                """,
                (token_hash, now),
            )
            return cur.fetchone()


def revoke_session(raw_token):
    if not raw_token:
        return
    token_hash = hashlib.sha256(raw_token.encode("utf-8")).hexdigest()
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "DELETE FROM user_sessions WHERE token_hash = %s",
                (token_hash,),
            )
        conn.commit()


def save_product(snapshot, *, user_id=None, record_history_always=False):
    now = utc_now()

    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT id, current_price
                FROM watched_products
                WHERE product_id = %s
                  AND user_id IS NOT DISTINCT FROM %s
                """,
                (snapshot.product_id, user_id),
            )
            existing = cur.fetchone()

            if existing:
                old_price = existing["current_price"]
                has_drop = (
                    old_price is not None
                    and snapshot.price is not None
                    and snapshot.price < old_price
                )

                cur.execute(
                    """
                    UPDATE watched_products
                    SET
                        user_id = %s,
                        product_url = %s,
                        name = %s,
                        brand = %s,
                        previous_price = %s,
                        current_price = %s,
                        was_price = %s,
                        cup_price = %s,
                        in_stock = %s,
                        image_url = %s,
                        last_checked_at = %s,
                        has_drop = CASE WHEN %s THEN TRUE ELSE has_drop END
                    WHERE product_id = %s
                      AND user_id IS NOT DISTINCT FROM %s
                    """,
                    (
                        user_id,
                        snapshot.canonical_url,
                        snapshot.name,
                        snapshot.brand,
                        old_price,
                        snapshot.price,
                        snapshot.was_price,
                        snapshot.cup_price,
                        snapshot.in_stock,
                        snapshot.image_url,
                        now,
                        has_drop,
                        snapshot.product_id,
                        user_id,
                    ),
                )
            else:
                cur.execute(
                    """
                    INSERT INTO watched_products (
                        user_id,
                        product_id,
                        product_url,
                        name,
                        brand,
                        current_price,
                        previous_price,
                        was_price,
                        cup_price,
                        in_stock,
                        image_url,
                        last_checked_at,
                        has_drop,
                        created_at
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, FALSE, %s)
                    """,
                    (
                        user_id,
                        snapshot.product_id,
                        snapshot.canonical_url,
                        snapshot.name,
                        snapshot.brand,
                        snapshot.price,
                        None,
                        snapshot.was_price,
                        snapshot.cup_price,
                        snapshot.in_stock,
                        snapshot.image_url,
                        now,
                        now,
                    ),
                )

            cur.execute(
                """
                SELECT price
                FROM price_history
                WHERE product_id = %s
                  AND user_id IS NOT DISTINCT FROM %s
                ORDER BY recorded_at DESC, id DESC
                LIMIT 1
                """,
                (snapshot.product_id, user_id),
            )
            latest_history = cur.fetchone()

            # Manual saves should still leave an audit trail, but background
            # refreshes only add history when the price actually changes.
            if (
                record_history_always
                or latest_history is None
                or latest_history["price"] != snapshot.price
            ):
                cur.execute(
                    """
                    INSERT INTO price_history (user_id, product_id, price, recorded_at)
                    VALUES (%s, %s, %s, %s)
                    """,
                    (user_id, snapshot.product_id, snapshot.price, now),
                )

        conn.commit()


def list_products(*, user_id=None):
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT *
                FROM watched_products
                WHERE user_id IS NOT DISTINCT FROM %s
                ORDER BY has_drop DESC, created_at DESC
            """, (user_id,))
            return cur.fetchall()


def remove_product(product_id, *, user_id=None):
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                DELETE FROM price_history
                WHERE product_id = %s
                  AND user_id IS NOT DISTINCT FROM %s
                """,
                (product_id, user_id),
            )
            cur.execute(
                """
                DELETE FROM watched_products
                WHERE product_id = %s
                  AND user_id IS NOT DISTINCT FROM %s
                """,
                (product_id, user_id),
            )
        conn.commit()


def get_price_history(product_id, *, user_id=None):
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT price, recorded_at
                FROM price_history
                WHERE product_id = %s
                  AND user_id IS NOT DISTINCT FROM %s
                ORDER BY recorded_at ASC
                """,
                (product_id, user_id),
            )
            return cur.fetchall()


def refresh_all_products(*, user_id=None):
    products = list_products(user_id=user_id)
    drops = []
    increases = []
    errors = []
    updated = []

    for p in products:
        try:
            snapshot = fetch_product_snapshot(p["product_url"])
            old_price = p["current_price"]
            save_product(snapshot, user_id=user_id)

            has_drop = (
                old_price is not None
                and snapshot.price is not None
                and snapshot.price < old_price
            )
            has_increase = (
                old_price is not None
                and snapshot.price is not None
                and snapshot.price > old_price
            )

            entry = {
                "product_id": snapshot.product_id,
                "name": snapshot.name,
                "old_price": old_price,
                "new_price": snapshot.price,
                "has_drop": has_drop,
                "has_increase": has_increase,
            }

            updated.append(entry)
            if has_drop:
                drops.append(entry)
            if has_increase:
                increases.append(entry)

        except Exception as exc:
            errors.append(
                {"product_id": p["product_id"], "error": str(exc)}
            )

    return {
        "updated": updated,
        "drops": drops,
        "increases": increases,
        "errors": errors,
    }


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        parsed = urlparse(self.path)
        params = parse_qs(parsed.query)
        current_user = self._get_current_user()
        current_user_id = current_user["id"] if current_user else None

        if parsed.path in ("/", "/dashboard", "/pricecompare.html", "/pricecompare.html"):
            html = (Path(__file__).parent / "pricecompare.html").read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            self.wfile.write(html)
            return

        if parsed.path == "/product":
            target = (params.get("target") or [""])[0].strip()
            if not target:
                self._send(400, {"error": "missing ?target="})
                return
            try:
                snapshot = fetch_product_snapshot(target)
                self._send(200, snapshot.to_dict())
            except Exception as exc:
                self._send(500, {"error": str(exc)})
            return

        if parsed.path == "/save":
            target = (params.get("target") or [""])[0].strip()
            if not target:
                self._send(400, {"error": "missing ?target="})
                return
            try:
                snapshot = fetch_product_snapshot(target)
                save_product(snapshot, user_id=current_user_id, record_history_always=True)
                self._send(200, snapshot.to_dict())
            except Exception as exc:
                self._send(500, {"error": str(exc)})
            return

        if parsed.path == "/watchlist":
            try:
                self._send(200, {"products": list_products(user_id=current_user_id)})
            except Exception as exc:
                self._send(500, {"error": str(exc)})
            return

        if parsed.path == "/refresh-all":
            try:
                self._send(200, refresh_all_products(user_id=current_user_id))
            except Exception as exc:
                self._send(500, {"error": str(exc)})
            return

        if parsed.path == "/remove":
            product_id = (params.get("product_id") or [""])[0].strip()
            if not product_id:
                self._send(400, {"error": "missing ?product_id="})
                return
            try:
                remove_product(product_id, user_id=current_user_id)
                self._send(200, {"ok": True})
            except Exception as exc:
                self._send(500, {"error": str(exc)})
            return

        if parsed.path == "/history":
            product_id = (params.get("product_id") or [""])[0].strip()
            if not product_id:
                self._send(400, {"error": "missing ?product_id="})
                return
            try:
                self._send(200, {"history": get_price_history(product_id, user_id=current_user_id)})
            except Exception as exc:
                self._send(500, {"error": str(exc)})
            return

        if parsed.path == "/auth/me":
            user = self._get_current_user()
            self._send(200, {"user": sanitise_user_row(user)})
            return

        self._send(404, {"error": "not found"})

    def do_POST(self):
        parsed = urlparse(self.path)
        payload = self._read_json_body()

        if parsed.path == "/auth/signup":
            try:
                password = (payload.get("password") or "").strip()
                confirm_password = (payload.get("confirm_password") or "").strip()
                if password != confirm_password:
                    raise ValueError("Passwords do not match.")
                user = create_user(
                    username=payload.get("username"),
                    email=payload.get("email"),
                    first_name=payload.get("first_name"),
                    last_name=payload.get("last_name"),
                    password=password,
                )
                token, expires_at = create_session(user["id"])
                self._send(
                    200,
                    {"user": sanitise_user_row(user)},
                    headers=self._session_headers(token, expires_at),
                )
            except psycopg.errors.UniqueViolation:
                self._send(400, {"error": "That username or email is already in use."})
            except ValueError as exc:
                self._send(400, {"error": str(exc)})
            except Exception as exc:
                self._send(500, {"error": str(exc)})
            return

        if parsed.path == "/auth/login":
            try:
                user = authenticate_user(
                    identifier=payload.get("identifier"),
                    password=(payload.get("password") or "").strip(),
                )
                token, expires_at = create_session(user["id"])
                self._send(
                    200,
                    {"user": sanitise_user_row(user)},
                    headers=self._session_headers(token, expires_at),
                )
            except ValueError as exc:
                self._send(400, {"error": str(exc)})
            except Exception as exc:
                self._send(500, {"error": str(exc)})
            return

        if parsed.path == "/auth/logout":
            try:
                revoke_session(self._get_session_token())
                self._send(
                    200,
                    {"ok": True},
                    headers=self._clear_session_headers(),
                )
            except Exception as exc:
                self._send(500, {"error": str(exc)})
            return

        self._send(404, {"error": "not found"})

    def _json_default(self, value):
        if isinstance(value, datetime):
            return value.isoformat()
        raise TypeError(
            f"Object of type {type(value).__name__} is not JSON serializable"
        )

    def _read_json_body(self):
        length = int(self.headers.get("Content-Length") or "0")
        if length <= 0:
            return {}
        raw = self.rfile.read(length)
        if not raw:
            return {}
        return json.loads(raw.decode("utf-8"))

    def _get_session_token(self):
        cookie_header = self.headers.get("Cookie")
        if not cookie_header:
            return None
        jar = cookies.SimpleCookie()
        jar.load(cookie_header)
        morsel = jar.get(SESSION_COOKIE_NAME)
        return morsel.value if morsel else None

    def _get_current_user(self):
        return get_user_by_session_token(self._get_session_token())

    def _session_headers(self, token, expires_at):
        return {
            "Set-Cookie": (
                f"{SESSION_COOKIE_NAME}={token}; Path=/; HttpOnly; SameSite=Lax; "
                f"Expires={expires_at.strftime('%a, %d %b %Y %H:%M:%S GMT')}"
            )
        }

    def _clear_session_headers(self):
        return {
            "Set-Cookie": (
                f"{SESSION_COOKIE_NAME}=; Path=/; HttpOnly; SameSite=Lax; "
                "Expires=Thu, 01 Jan 1970 00:00:00 GMT"
            )
        }

    def _send(self, status, data, *, headers=None):
        body = json.dumps(data, default=self._json_default).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Access-Control-Allow-Origin", "*")
        if headers:
            for key, value in headers.items():
                self.send_header(key, value)
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass


if __name__ == "__main__":
    init_db()
    print(
        f"Running at http://{APP_HOST}:{APP_PORT} using PostgreSQL database '{DB_NAME}'"
    )
    HTTPServer((APP_HOST, APP_PORT), Handler).serve_forever()
