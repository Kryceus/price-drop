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
import re
import secrets
import time

import psycopg
from psycopg.rows import dict_row

from store_scrapers import fetch_product_snapshot
from generic_product_extractor import normalize_target_url
from woolworths_scraper import ProductSnapshot


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


def normalise_env_assignment(value, key):
    if not value:
        return value
    value = value.strip().strip("\"'")
    prefix = f"{key}="
    if value.startswith(prefix):
        return value[len(prefix):].strip().strip("\"'")
    return value


DB_HOST = os.getenv("DB_HOST", "localhost")
DB_PORT = int(os.getenv("DB_PORT", "5432"))
DB_NAME = os.getenv("DB_NAME", "pricecompare")
DB_USER = os.getenv("DB_USER", "postgres")
DB_PASSWORD = os.getenv("DB_PASSWORD", "")
DATABASE_URL = normalise_env_assignment(os.getenv("DATABASE_URL"), "DATABASE_URL")
APP_HOST = os.getenv("APP_HOST", "127.0.0.1")
APP_PORT = int(os.getenv("APP_PORT") or os.getenv("PORT") or "8080")
SESSION_COOKIE_NAME = "pricewatch_session"
SESSION_TTL_SECONDS = 60 * 60 * 24 * 30
SESSION_COOKIE_SAMESITE = os.getenv("SESSION_COOKIE_SAMESITE", "Lax")
SESSION_COOKIE_SECURE = os.getenv("SESSION_COOKIE_SECURE", "false").lower() in {
    "1",
    "true",
    "yes",
}
FRONTEND_ORIGINS = {
    origin.strip()
    for origin in os.getenv(
        "FRONTEND_ORIGINS",
        "http://127.0.0.1:3000,http://localhost:3000,http://127.0.0.1:8080,http://localhost:8080,capacitor://localhost",
    ).split(",")
    if origin.strip()
}
PREVIEW_CACHE_TTL_SECONDS = 90
WOOLWORTHS_PRODUCT_ID_RE = re.compile(r"/shop/productdetails/(\d+)")
FIREBASE_CREDENTIALS_PATH = os.getenv("FIREBASE_CREDENTIALS_PATH")
FIREBASE_CREDENTIALS_JSON = normalise_env_assignment(
    os.getenv("FIREBASE_CREDENTIALS_JSON"),
    "FIREBASE_CREDENTIALS_JSON",
)
_snapshot_cache = {}
_firebase_app = None
_firebase_unavailable_reason = None


def utc_now():
    return datetime.now(timezone.utc).replace(microsecond=0)


def _normalize_cache_key(target):
    normalized = normalize_target_url(target)
    return normalized.normalized_url


def _get_cached_snapshot(target):
    try:
        cache_key = _normalize_cache_key(target)
    except Exception:
        return None

    cached = _snapshot_cache.get(cache_key)
    if cached is None:
        return None

    expires_at, snapshot = cached
    if expires_at <= time.time():
        _snapshot_cache.pop(cache_key, None)
        return None
    return snapshot


def _cache_snapshot(target, snapshot):
    try:
        cache_key = _normalize_cache_key(target)
    except Exception:
        return
    _snapshot_cache[cache_key] = (
        time.time() + PREVIEW_CACHE_TTL_SECONDS,
        snapshot,
    )


def resolve_product_snapshot(target, *, allow_cache=False):
    if allow_cache:
        cached = _get_cached_snapshot(target)
        if cached is not None:
            return cached

    snapshot = fetch_product_snapshot(target)
    _cache_snapshot(target, snapshot)
    return snapshot


def get_conn():
    if DATABASE_URL:
        return psycopg.connect(DATABASE_URL, row_factory=dict_row)

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
                CREATE TABLE IF NOT EXISTS products (
                    id SERIAL PRIMARY KEY,
                    external_product_id TEXT NOT NULL UNIQUE,
                    original_url TEXT,
                    product_url TEXT NOT NULL,
                    domain TEXT,
                    merchant_name TEXT,
                    status TEXT,
                    last_error TEXT,
                    last_error_at TIMESTAMPTZ,
                    last_seen_at TIMESTAMPTZ,
                    extraction_source TEXT,
                    extraction_confidence DOUBLE PRECISION,
                    name TEXT,
                    brand TEXT,
                    current_price DOUBLE PRECISION,
                    currency TEXT,
                    original_price DOUBLE PRECISION,
                    was_price DOUBLE PRECISION,
                    cup_price TEXT,
                    in_stock BOOLEAN,
                    image_url TEXT,
                    last_checked_at TIMESTAMPTZ,
                    created_at TIMESTAMPTZ NOT NULL,
                    updated_at TIMESTAMPTZ NOT NULL
                );
            """)

            cur.execute("""
                CREATE TABLE IF NOT EXISTS user_watchlists (
                    id SERIAL PRIMARY KEY,
                    user_id INTEGER REFERENCES users(id) ON DELETE CASCADE,
                    product_id INTEGER NOT NULL REFERENCES products(id) ON DELETE CASCADE,
                    active BOOLEAN NOT NULL DEFAULT TRUE,
                    last_seen_price DOUBLE PRECISION,
                    last_notified_price DOUBLE PRECISION,
                    notify_on_drop BOOLEAN NOT NULL DEFAULT TRUE,
                    notify_on_increase BOOLEAN NOT NULL DEFAULT FALSE,
                    created_at TIMESTAMPTZ NOT NULL
                );
            """)

            cur.execute("""
                CREATE TABLE IF NOT EXISTS user_device_tokens (
                    id SERIAL PRIMARY KEY,
                    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                    token_hash TEXT NOT NULL UNIQUE,
                    token TEXT NOT NULL,
                    platform TEXT,
                    device_label TEXT,
                    enabled BOOLEAN NOT NULL DEFAULT TRUE,
                    last_seen_at TIMESTAMPTZ NOT NULL,
                    created_at TIMESTAMPTZ NOT NULL,
                    updated_at TIMESTAMPTZ NOT NULL
                );
            """)

            cur.execute("""
                CREATE TABLE IF NOT EXISTS notification_events (
                    id SERIAL PRIMARY KEY,
                    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                    product_id INTEGER REFERENCES products(id) ON DELETE SET NULL,
                    device_token_id INTEGER REFERENCES user_device_tokens(id) ON DELETE SET NULL,
                    event_type TEXT NOT NULL,
                    title TEXT NOT NULL,
                    body TEXT NOT NULL,
                    payload JSONB,
                    status TEXT NOT NULL,
                    provider_message_id TEXT,
                    error TEXT,
                    created_at TIMESTAMPTZ NOT NULL,
                    sent_at TIMESTAMPTZ
                );
            """)

            cur.execute("""
                CREATE TABLE IF NOT EXISTS product_price_history (
                    id SERIAL PRIMARY KEY,
                    product_id INTEGER NOT NULL REFERENCES products(id) ON DELETE CASCADE,
                    price DOUBLE PRECISION,
                    was_price DOUBLE PRECISION,
                    in_stock BOOLEAN,
                    recorded_at TIMESTAMPTZ NOT NULL
                );
            """)

            cur.execute("""
                DO $$
                BEGIN
                    IF EXISTS (
                        SELECT 1
                        FROM information_schema.tables
                        WHERE table_schema = 'public'
                          AND table_name = 'watched_products'
                          AND table_type = 'BASE TABLE'
                    ) AND NOT EXISTS (
                        SELECT 1
                        FROM pg_class c
                        JOIN pg_namespace n ON n.oid = c.relnamespace
                        WHERE n.nspname = 'public'
                          AND c.relname = 'watched_products_legacy'
                    ) THEN
                        ALTER TABLE watched_products RENAME TO watched_products_legacy;
                    END IF;
                END
                $$;
            """)

            cur.execute("""
                DO $$
                BEGIN
                    IF EXISTS (
                        SELECT 1
                        FROM information_schema.tables
                        WHERE table_schema = 'public'
                          AND table_name = 'price_history'
                          AND table_type = 'BASE TABLE'
                    ) AND NOT EXISTS (
                        SELECT 1
                        FROM pg_class c
                        JOIN pg_namespace n ON n.oid = c.relnamespace
                        WHERE n.nspname = 'public'
                          AND c.relname = 'price_history_legacy'
                    ) THEN
                        ALTER TABLE price_history RENAME TO price_history_legacy;
                    END IF;
                END
                $$;
            """)

            cur.execute("""
                CREATE INDEX IF NOT EXISTS products_last_checked_idx
                ON products(last_checked_at)
            """)

            cur.execute("""
                CREATE INDEX IF NOT EXISTS watchlists_scope_idx
                ON user_watchlists ((COALESCE(user_id, 0)), active, created_at DESC)
            """)

            cur.execute("""
                CREATE UNIQUE INDEX IF NOT EXISTS user_watchlists_scope_product_idx
                ON user_watchlists ((COALESCE(user_id, 0)), product_id)
            """)

            cur.execute("""
                CREATE INDEX IF NOT EXISTS user_device_tokens_user_idx
                ON user_device_tokens(user_id, enabled)
            """)

            cur.execute("""
                CREATE INDEX IF NOT EXISTS notification_events_user_created_idx
                ON notification_events(user_id, created_at DESC)
            """)

            cur.execute("""
                CREATE INDEX IF NOT EXISTS watchlists_product_idx
                ON user_watchlists(product_id, active)
            """)

            cur.execute("""
                CREATE INDEX IF NOT EXISTS product_price_history_product_idx
                ON product_price_history(product_id, recorded_at DESC)
            """)

            cur.execute("""
                ALTER TABLE user_watchlists
                ADD COLUMN IF NOT EXISTS last_notified_price DOUBLE PRECISION
            """)

            cur.execute("""
                ALTER TABLE user_watchlists
                ADD COLUMN IF NOT EXISTS notify_on_drop BOOLEAN NOT NULL DEFAULT TRUE
            """)

            cur.execute("""
                ALTER TABLE user_watchlists
                ADD COLUMN IF NOT EXISTS notify_on_increase BOOLEAN NOT NULL DEFAULT FALSE
            """)

            cur.execute("""
                ALTER TABLE products
                ADD COLUMN IF NOT EXISTS original_price DOUBLE PRECISION
            """)

            cur.execute("""
                ALTER TABLE products
                ADD COLUMN IF NOT EXISTS original_url TEXT
            """)

            cur.execute("""
                ALTER TABLE products
                ADD COLUMN IF NOT EXISTS domain TEXT
            """)

            cur.execute("""
                ALTER TABLE products
                ADD COLUMN IF NOT EXISTS merchant_name TEXT
            """)

            cur.execute("""
                ALTER TABLE products
                ADD COLUMN IF NOT EXISTS status TEXT
            """)

            cur.execute("""
                ALTER TABLE products
                ADD COLUMN IF NOT EXISTS last_error TEXT
            """)

            cur.execute("""
                ALTER TABLE products
                ADD COLUMN IF NOT EXISTS last_error_at TIMESTAMPTZ
            """)

            cur.execute("""
                ALTER TABLE products
                ADD COLUMN IF NOT EXISTS last_seen_at TIMESTAMPTZ
            """)

            cur.execute("""
                ALTER TABLE products
                ADD COLUMN IF NOT EXISTS currency TEXT
            """)

            cur.execute("""
                ALTER TABLE products
                ADD COLUMN IF NOT EXISTS extraction_source TEXT
            """)

            cur.execute("""
                ALTER TABLE products
                ADD COLUMN IF NOT EXISTS extraction_confidence DOUBLE PRECISION
            """)

            cur.execute("""
                UPDATE products
                SET original_url = product_url
                WHERE original_url IS NULL AND product_url IS NOT NULL
            """)

            cur.execute("""
                UPDATE products
                SET domain = LOWER(SPLIT_PART(REGEXP_REPLACE(product_url, '^https?://', ''), '/', 1))
                WHERE (domain IS NULL OR domain = '')
                  AND product_url IS NOT NULL
            """)

            cur.execute("""
                UPDATE products
                SET merchant_name = CASE
                    WHEN domain LIKE '%woolworths%' THEN 'Woolworths'
                    WHEN domain LIKE '%amazon%' THEN 'Amazon'
                    WHEN domain LIKE '%coles%' THEN 'Coles'
                    WHEN domain LIKE '%aldi%' THEN 'ALDI'
                    WHEN domain LIKE '%iga%' THEN 'IGA'
                    WHEN domain IS NOT NULL AND domain <> '' THEN INITCAP(SPLIT_PART(REPLACE(domain, 'www.', ''), '.', 1))
                    ELSE merchant_name
                END
                WHERE merchant_name IS NULL OR merchant_name = ''
            """)

            cur.execute("""
                UPDATE products
                SET status = 'active'
                WHERE status IS NULL OR status = ''
            """)

            cur.execute("""
                UPDATE products
                SET last_seen_at = COALESCE(last_checked_at, updated_at, created_at)
                WHERE last_seen_at IS NULL
            """)

            cur.execute("""
                UPDATE products
                SET currency = 'AUD'
                WHERE (currency IS NULL OR currency = '')
                  AND (
                    domain LIKE '%.com.au%'
                    OR domain LIKE '%woolworths%'
                    OR domain LIKE '%coles%'
                    OR domain LIKE '%amazon%'
                    OR domain LIKE '%aldi%'
                    OR domain LIKE '%iga%'
                  )
            """)

            cur.execute("""
                UPDATE products
                SET extraction_source = CASE
                    WHEN domain LIKE '%woolworths%' THEN 'retailer:woolworths'
                    WHEN domain LIKE '%amazon%' THEN 'retailer:amazon'
                    WHEN domain LIKE '%coles%' THEN 'retailer:coles'
                    WHEN domain LIKE '%aldi%' THEN 'retailer:aldi'
                    WHEN domain LIKE '%iga%' THEN 'retailer:iga'
                    WHEN domain IS NOT NULL AND domain <> '' THEN 'generic:legacy'
                    ELSE extraction_source
                END
                WHERE extraction_source IS NULL OR extraction_source = ''
            """)

            cur.execute("""
                UPDATE products
                SET extraction_confidence = CASE
                    WHEN extraction_source LIKE 'retailer:%' THEN 0.90
                    WHEN extraction_source LIKE 'generic:%' THEN 0.60
                    ELSE extraction_confidence
                END
                WHERE extraction_confidence IS NULL
            """)

            cur.execute("""
                SELECT EXISTS (
                    SELECT 1
                    FROM pg_class c
                    JOIN pg_namespace n ON n.oid = c.relnamespace
                    WHERE n.nspname = 'public'
                      AND c.relname = 'watched_products_legacy'
                      AND c.relkind = 'r'
                ) AS legacy_table
            """)
            watched_products_legacy = cur.fetchone()["legacy_table"]

            if watched_products_legacy:
                cur.execute("""
                    ALTER TABLE watched_products_legacy
                    ADD COLUMN IF NOT EXISTS user_id INTEGER REFERENCES users(id) ON DELETE CASCADE
                """)

                cur.execute("""
                    INSERT INTO products (
                        external_product_id,
                        product_url,
                        name,
                        brand,
                        current_price,
                        original_price,
                        was_price,
                        cup_price,
                        in_stock,
                        image_url,
                        last_checked_at,
                        created_at,
                        updated_at
                    )
                    SELECT
                        wp.product_id,
                        wp.product_url,
                        wp.name,
                        wp.brand,
                        wp.current_price,
                        COALESCE(wp.was_price, wp.current_price),
                        wp.was_price,
                        wp.cup_price,
                        wp.in_stock,
                        wp.image_url,
                        wp.last_checked_at,
                        wp.created_at,
                        COALESCE(wp.last_checked_at, wp.created_at)
                    FROM watched_products_legacy wp
                    ON CONFLICT (external_product_id) DO NOTHING
                """)

                cur.execute("""
                    INSERT INTO user_watchlists (
                        user_id,
                        product_id,
                        created_at,
                        last_seen_price
                    )
                    SELECT
                        wp.user_id,
                        p.id,
                        wp.created_at,
                        wp.current_price
                    FROM watched_products_legacy wp
                    JOIN products p ON p.external_product_id = wp.product_id
                    WHERE NOT EXISTS (
                        SELECT 1
                        FROM user_watchlists existing
                        WHERE existing.user_id IS NOT DISTINCT FROM wp.user_id
                          AND existing.product_id = p.id
                    )
                """)

            cur.execute("""
                SELECT EXISTS (
                    SELECT 1
                    FROM pg_class c
                    JOIN pg_namespace n ON n.oid = c.relnamespace
                    WHERE n.nspname = 'public'
                      AND c.relname = 'price_history_legacy'
                      AND c.relkind = 'r'
                ) AS legacy_table
            """)
            price_history_legacy = cur.fetchone()["legacy_table"]

            if price_history_legacy:
                cur.execute("""
                    ALTER TABLE price_history_legacy
                    ADD COLUMN IF NOT EXISTS user_id INTEGER REFERENCES users(id) ON DELETE CASCADE
                """)

                cur.execute("""
                    INSERT INTO product_price_history (
                        product_id,
                        price,
                        was_price,
                        in_stock,
                        recorded_at
                    )
                    SELECT DISTINCT
                        p.id,
                        ph.price,
                        prod.was_price,
                        prod.in_stock,
                        ph.recorded_at
                    FROM price_history_legacy ph
                    JOIN products p ON p.external_product_id = ph.product_id
                    LEFT JOIN watched_products_legacy prod
                        ON prod.product_id = ph.product_id
                    WHERE NOT EXISTS (
                        SELECT 1
                        FROM product_price_history existing
                        WHERE existing.product_id = p.id
                          AND existing.recorded_at = ph.recorded_at
                          AND existing.price IS NOT DISTINCT FROM ph.price
                    )
                """)

            cur.execute("""
                UPDATE products
                SET original_price = was_price
                WHERE original_price IS DISTINCT FROM was_price
            """)

            cur.execute("DROP VIEW IF EXISTS watched_products")
            cur.execute("""
                CREATE VIEW watched_products AS
                SELECT
                    p.id,
                    p.external_product_id AS product_id,
                    p.product_url,
                    p.name,
                    p.brand,
                    p.current_price,
                    p.original_price,
                    prev.price AS previous_price,
                    p.was_price,
                    p.cup_price,
                    p.in_stock,
                    p.image_url,
                    p.last_checked_at,
                    CASE
                        WHEN prev.price IS NOT NULL
                             AND p.current_price IS NOT NULL
                             AND p.current_price < prev.price
                        THEN TRUE ELSE FALSE
                    END AS has_drop,
                    p.created_at,
                    NULL::INTEGER AS user_id
                FROM products p
                LEFT JOIN LATERAL (
                    SELECT ph.price
                    FROM product_price_history ph
                    WHERE ph.product_id = p.id
                    ORDER BY ph.recorded_at DESC, ph.id DESC
                    OFFSET 1 LIMIT 1
                ) prev ON TRUE
            """)

            cur.execute("DROP VIEW IF EXISTS price_history")
            cur.execute("""
                CREATE VIEW price_history AS
                SELECT
                    ph.id,
                    NULL::INTEGER AS user_id,
                    p.external_product_id AS product_id,
                    ph.price,
                    ph.recorded_at
                FROM product_price_history ph
                JOIN products p ON p.id = ph.product_id
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


def get_snapshot_domain(snapshot):
    parsed = urlparse(snapshot.canonical_url or "")
    return (parsed.netloc or parsed.hostname or "").lower() or None


def get_snapshot_merchant_name(snapshot):
    domain = get_snapshot_domain(snapshot) or ""
    if "woolworths" in domain:
        return "Woolworths"
    if "amazon" in domain:
        return "Amazon"
    if "coles" in domain:
        return "Coles"
    if "aldi" in domain:
        return "ALDI"
    if "iga" in domain:
        return "IGA"
    if not domain:
        return None
    host = domain.removeprefix("www.")
    return host.split(".")[0].replace("-", " ").title()


def get_snapshot_extraction_source(snapshot):
    return snapshot.extraction_source or "generic:unknown"


def get_snapshot_extraction_confidence(snapshot):
    return snapshot.extraction_confidence


def snapshot_from_payload(payload):
    canonical_url = (payload.get("canonical_url") or payload.get("product_url") or "").strip()
    if not canonical_url:
        raise ValueError("Product URL is required.")

    product_id = (payload.get("product_id") or "").strip()
    if not product_id:
        raise ValueError("Product identifier is required.")

    return ProductSnapshot(
        product_id=product_id,
        name=payload.get("name"),
        brand=payload.get("brand"),
        price=payload.get("price"),
        was_price=payload.get("was_price"),
        cup_price=payload.get("cup_price"),
        in_stock=payload.get("in_stock"),
        availability=payload.get("availability"),
        image_url=payload.get("image_url"),
        canonical_url=canonical_url,
        currency=payload.get("currency"),
        original_url=payload.get("original_url") or canonical_url,
        extraction_source=payload.get("extraction_source"),
        extraction_confidence=payload.get("extraction_confidence"),
    )


def serialise_product_row(row):
    if not row:
        return None
    return {
        "id": row["external_product_id"],
        "external_product_id": row["external_product_id"],
        "original_url": row.get("original_url"),
        "product_url": row["product_url"],
        "domain": row.get("domain"),
        "merchant_name": row.get("merchant_name"),
        "status": row.get("status"),
        "last_error": row.get("last_error"),
        "last_error_at": row.get("last_error_at"),
        "last_seen_at": row.get("last_seen_at"),
        "extraction_source": row.get("extraction_source"),
        "extraction_confidence": row.get("extraction_confidence"),
        "name": row.get("name"),
        "brand": row.get("brand"),
        "current_price": row.get("current_price"),
        "currency": row.get("currency"),
        "original_price": row.get("original_price"),
        "was_price": row.get("was_price"),
        "cup_price": row.get("cup_price"),
        "in_stock": row.get("in_stock"),
        "image_url": row.get("image_url"),
        "last_checked_at": row.get("last_checked_at"),
        "notify_on_drop": row.get("notify_on_drop"),
        "notify_on_increase": row.get("notify_on_increase"),
        "last_notified_price": row.get("last_notified_price"),
    }


def upsert_product_snapshot(snapshot):
    now = utc_now()
    snapshot_domain = get_snapshot_domain(snapshot)
    snapshot_merchant_name = get_snapshot_merchant_name(snapshot)
    snapshot_original_url = snapshot.original_url or snapshot.canonical_url
    snapshot_extraction_source = get_snapshot_extraction_source(snapshot)
    snapshot_extraction_confidence = get_snapshot_extraction_confidence(snapshot)
    common_fields = {
        "original_url": snapshot_original_url,
        "product_url": snapshot.canonical_url,
        "domain": snapshot_domain,
        "merchant_name": snapshot_merchant_name,
        "status": "active",
        "last_error": None,
        "last_error_at": None,
        "last_seen_at": now,
        "extraction_source": snapshot_extraction_source,
        "extraction_confidence": snapshot_extraction_confidence,
        "name": snapshot.name,
        "brand": snapshot.brand,
        "current_price": snapshot.price,
        "currency": snapshot.currency,
        "original_price": snapshot.was_price,
        "was_price": snapshot.was_price,
        "cup_price": snapshot.cup_price,
        "in_stock": snapshot.in_stock,
        "image_url": snapshot.image_url,
        "last_checked_at": now,
        "updated_at": now,
    }

    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT id, current_price, original_price
                FROM products
                WHERE external_product_id = %s
                """,
                (snapshot.product_id,),
            )
            existing = cur.fetchone()

            if existing:
                old_price = existing["current_price"]
                assignments = ",\n                        ".join(
                    f"{column} = %s" for column in common_fields
                )
                cur.execute(
                    f"""
                    UPDATE products
                    SET
                        {assignments}
                    WHERE id = %s
                    RETURNING id, external_product_id, original_url, product_url, domain, merchant_name,
                              status, last_error, last_error_at, last_seen_at,
                              current_price, currency, original_price, was_price, cup_price,
                              in_stock, image_url, name, brand, extraction_source,
                              extraction_confidence, last_checked_at, created_at, updated_at
                    """,
                    (*common_fields.values(), existing["id"]),
                )
                product = cur.fetchone()
            else:
                old_price = None
                insert_fields = {
                    "external_product_id": snapshot.product_id,
                    **common_fields,
                    "created_at": now,
                }
                columns_sql = ",\n                        ".join(insert_fields.keys())
                placeholders_sql = ", ".join(["%s"] * len(insert_fields))
                cur.execute(
                    f"""
                    INSERT INTO products (
                        {columns_sql}
                    ) VALUES ({placeholders_sql})
                    RETURNING id, external_product_id, original_url, product_url, domain, merchant_name,
                              status, last_error, last_error_at, last_seen_at,
                              current_price, currency, original_price, was_price, cup_price,
                              in_stock, image_url, name, brand, extraction_source,
                              extraction_confidence, last_checked_at, created_at, updated_at
                    """,
                    tuple(insert_fields.values()),
                )
                product = cur.fetchone()

            cur.execute(
                """
                SELECT price
                FROM product_price_history
                WHERE product_id = %s
                ORDER BY recorded_at DESC, id DESC
                LIMIT 1
                """,
                (product["id"],),
            )
            latest_history = cur.fetchone()

            if latest_history is None or latest_history["price"] != snapshot.price:
                cur.execute(
                    """
                    INSERT INTO product_price_history (product_id, price, was_price, in_stock, recorded_at)
                    VALUES (%s, %s, %s, %s, %s)
                    """,
                    (product["id"], snapshot.price, snapshot.was_price, snapshot.in_stock, now),
                )

        conn.commit()

    return product, old_price


def mark_product_refresh_error(product_id, error_message):
    now = utc_now()
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE products
                SET status = %s,
                    last_error = %s,
                    last_error_at = %s,
                    updated_at = %s
                WHERE external_product_id = %s
                """,
                ("error", error_message, now, now, product_id),
            )
        conn.commit()


def add_product_to_watchlist(snapshot, *, user_id=None):
    product, _ = upsert_product_snapshot(snapshot)
    now = utc_now()

    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO user_watchlists (
                    user_id,
                    product_id,
                    created_at,
                    last_seen_price
                ) VALUES (%s, %s, %s, %s)
                ON CONFLICT ((COALESCE(user_id, 0)), product_id)
                DO UPDATE SET active = TRUE
                RETURNING id
                """,
                (user_id, product["id"], now, product["current_price"]),
            )
            cur.fetchone()
        conn.commit()

    return product


def _product_id_from_queued_target(normalized):
    parsed = urlparse(normalized.normalized_url)
    host = (parsed.hostname or normalized.domain or "").lower()

    if "woolworths.com.au" in host:
        match = WOOLWORTHS_PRODUCT_ID_RE.search(parsed.path)
        if match:
            return match.group(1)

    digest = hashlib.sha256(normalized.normalized_url.encode("utf-8")).hexdigest()[:16]
    store_slug = host.removeprefix("www.").split(".")[0] or "product"
    return f"{store_slug}:{digest}"


def queue_product_for_scheduled_refresh(target, *, user_id=None, error_message=None):
    normalized = normalize_target_url(target)
    now = utc_now()
    external_product_id = _product_id_from_queued_target(normalized)
    merchant_name = get_snapshot_merchant_name(
        ProductSnapshot(
            product_id=external_product_id,
            name=None,
            brand=None,
            price=None,
            was_price=None,
            cup_price=None,
            in_stock=None,
            availability=None,
            image_url=None,
            canonical_url=normalized.normalized_url,
            currency=None,
            original_url=normalized.original_url,
        )
    )
    last_error = error_message or "Queued for the next scheduled price check."

    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO products (
                    external_product_id,
                    original_url,
                    product_url,
                    domain,
                    merchant_name,
                    status,
                    last_error,
                    last_error_at,
                    last_seen_at,
                    extraction_source,
                    extraction_confidence,
                    name,
                    brand,
                    current_price,
                    currency,
                    original_price,
                    was_price,
                    cup_price,
                    in_stock,
                    image_url,
                    last_checked_at,
                    created_at,
                    updated_at
                ) VALUES (
                    %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                    %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s
                )
                ON CONFLICT (external_product_id) DO UPDATE
                SET original_url = EXCLUDED.original_url,
                    product_url = EXCLUDED.product_url,
                    domain = EXCLUDED.domain,
                    merchant_name = EXCLUDED.merchant_name,
                    status = EXCLUDED.status,
                    last_error = EXCLUDED.last_error,
                    last_error_at = EXCLUDED.last_error_at,
                    updated_at = EXCLUDED.updated_at
                RETURNING id, external_product_id, original_url, product_url, domain, merchant_name,
                          status, last_error, last_error_at, last_seen_at,
                          current_price, currency, original_price, was_price, cup_price,
                          in_stock, image_url, name, brand, extraction_source,
                          extraction_confidence, last_checked_at, created_at, updated_at
                """,
                (
                    external_product_id,
                    normalized.original_url,
                    normalized.normalized_url,
                    normalized.domain,
                    merchant_name,
                    "queued",
                    last_error,
                    now,
                    now,
                    "queued:scheduled-refresh",
                    0.0,
                    None,
                    None,
                    None,
                    None,
                    None,
                    None,
                    None,
                    None,
                    None,
                    None,
                    now,
                    now,
                ),
            )
            product = cur.fetchone()
            cur.execute(
                """
                INSERT INTO user_watchlists (
                    user_id,
                    product_id,
                    created_at,
                    last_seen_price
                ) VALUES (%s, %s, %s, %s)
                ON CONFLICT ((COALESCE(user_id, 0)), product_id)
                DO UPDATE SET active = TRUE
                RETURNING id
                """,
                (user_id, product["id"], now, product["current_price"]),
            )
            cur.fetchone()
        conn.commit()

    return product


def list_products(*, user_id=None):
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT
                    uw.id AS watchlist_id,
                    uw.user_id,
                    uw.created_at,
                    uw.last_seen_price,
                    uw.notify_on_drop,
                    uw.notify_on_increase,
                    uw.last_notified_price,
                    p.id AS product_db_id,
                    p.external_product_id AS product_id,
                    p.original_url,
                    p.product_url,
                    p.domain,
                    p.merchant_name,
                    p.status,
                    p.last_error,
                    p.last_error_at,
                    p.last_seen_at,
                    p.extraction_source,
                    p.extraction_confidence,
                    p.name,
                    p.brand,
                    p.current_price,
                    p.currency,
                    p.original_price,
                    prev.price AS previous_price,
                    p.was_price,
                    p.cup_price,
                    p.in_stock,
                    p.image_url,
                    p.last_checked_at,
                    CASE
                        WHEN prev.price IS NOT NULL AND p.current_price IS NOT NULL AND p.current_price < prev.price
                        THEN TRUE ELSE FALSE
                    END AS has_drop
                FROM user_watchlists uw
                JOIN products p ON p.id = uw.product_id
                LEFT JOIN LATERAL (
                    SELECT ph.price
                    FROM product_price_history ph
                    WHERE ph.product_id = p.id
                    ORDER BY ph.recorded_at DESC, ph.id DESC
                    OFFSET 1 LIMIT 1
                ) prev ON TRUE
                WHERE uw.user_id IS NOT DISTINCT FROM %s
                  AND uw.active = TRUE
                ORDER BY
                    CASE
                        WHEN prev.price IS NOT NULL AND p.current_price IS NOT NULL AND p.current_price < prev.price
                        THEN 1 ELSE 0
                    END DESC,
                    uw.created_at DESC
                """,
                (user_id,),
            )
            return cur.fetchall()


def get_watchlist_product(product_id, *, user_id=None):
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT
                    uw.id AS watchlist_id,
                    uw.user_id,
                    uw.created_at,
                    uw.last_seen_price,
                    uw.notify_on_drop,
                    uw.notify_on_increase,
                    uw.last_notified_price,
                    p.id AS product_db_id,
                    p.external_product_id,
                    p.original_url,
                    p.product_url,
                    p.domain,
                    p.merchant_name,
                    p.status,
                    p.last_error,
                    p.last_error_at,
                    p.last_seen_at,
                    p.extraction_source,
                    p.extraction_confidence,
                    p.name,
                    p.brand,
                    p.current_price,
                    p.currency,
                    p.original_price,
                    p.was_price,
                    p.cup_price,
                    p.in_stock,
                    p.image_url,
                    p.last_checked_at
                FROM user_watchlists uw
                JOIN products p ON p.id = uw.product_id
                WHERE p.external_product_id = %s
                  AND uw.user_id IS NOT DISTINCT FROM %s
                  AND uw.active = TRUE
                ORDER BY uw.created_at DESC
                LIMIT 1
                """,
                (product_id, user_id),
            )
            return cur.fetchone()


def remove_product(product_id, *, user_id=None):
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE user_watchlists uw
                SET active = FALSE
                FROM products p
                WHERE uw.product_id = p.id
                  AND p.external_product_id = %s
                  AND uw.user_id IS NOT DISTINCT FROM %s
                """,
                (product_id, user_id),
            )
        conn.commit()


def update_watchlist_notification_settings(product_id, *, user_id=None, notify_on_drop=True):
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE user_watchlists uw
                SET notify_on_drop = %s
                FROM products p
                WHERE uw.product_id = p.id
                  AND p.external_product_id = %s
                  AND uw.user_id IS NOT DISTINCT FROM %s
                  AND uw.active = TRUE
                RETURNING uw.id
                """,
                (notify_on_drop, product_id, user_id),
            )
            updated = cur.fetchone()
        conn.commit()

    if not updated:
        return None
    return get_watchlist_product(product_id, user_id=user_id)


def _hash_device_token(token):
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def register_device_token(*, user_id, token, platform=None, device_label=None):
    if not user_id:
        raise ValueError("You must be logged in to enable notifications.")
    token = (token or "").strip()
    if not token:
        raise ValueError("Device token is required.")

    now = utc_now()
    token_hash = _hash_device_token(token)
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO user_device_tokens (
                    user_id,
                    token_hash,
                    token,
                    platform,
                    device_label,
                    enabled,
                    last_seen_at,
                    created_at,
                    updated_at
                ) VALUES (%s, %s, %s, %s, %s, TRUE, %s, %s, %s)
                ON CONFLICT (token_hash)
                DO UPDATE SET
                    user_id = EXCLUDED.user_id,
                    token = EXCLUDED.token,
                    platform = EXCLUDED.platform,
                    device_label = EXCLUDED.device_label,
                    enabled = TRUE,
                    last_seen_at = EXCLUDED.last_seen_at,
                    updated_at = EXCLUDED.updated_at
                RETURNING id, user_id, platform, device_label, enabled, last_seen_at, created_at, updated_at
                """,
                (
                    user_id,
                    token_hash,
                    token,
                    _normalise_notification_platform(platform),
                    _normalise_optional_text(device_label, max_length=120),
                    now,
                    now,
                    now,
                ),
            )
            row = cur.fetchone()
        conn.commit()
    return row


def disable_device_token(*, user_id, token):
    if not user_id:
        raise ValueError("You must be logged in to update notifications.")
    token = (token or "").strip()
    if not token:
        raise ValueError("Device token is required.")

    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE user_device_tokens
                SET enabled = FALSE,
                    updated_at = %s
                WHERE user_id = %s
                  AND token_hash = %s
                RETURNING id
                """,
                (utc_now(), user_id, _hash_device_token(token)),
            )
            row = cur.fetchone()
        conn.commit()
    return row is not None


def _normalise_notification_platform(value):
    text = _normalise_optional_text(value, max_length=40)
    if not text:
        return None
    lowered = text.lower()
    if lowered in {"android", "ios", "web"}:
        return lowered
    return "other"


def _normalise_optional_text(value, *, max_length):
    if not isinstance(value, str):
        return None
    text = value.strip()
    if not text:
        return None
    return text[:max_length]


def _get_firebase_messaging():
    global _firebase_app, _firebase_unavailable_reason
    if _firebase_unavailable_reason:
        return None

    try:
        import firebase_admin
        from firebase_admin import credentials, messaging
    except Exception as exc:
        _firebase_unavailable_reason = f"firebase-admin is not installed: {exc}"
        return None

    if _firebase_app is None:
        try:
            if FIREBASE_CREDENTIALS_JSON:
                service_account = json.loads(FIREBASE_CREDENTIALS_JSON)
                credential = credentials.Certificate(service_account)
            elif FIREBASE_CREDENTIALS_PATH:
                credential = credentials.Certificate(FIREBASE_CREDENTIALS_PATH)
            else:
                _firebase_unavailable_reason = (
                    "Firebase credentials are not configured. Set FIREBASE_CREDENTIALS_JSON or FIREBASE_CREDENTIALS_PATH."
                )
                return None
            _firebase_app = firebase_admin.initialize_app(credential)
        except ValueError:
            _firebase_app = firebase_admin.get_app()
        except Exception as exc:
            _firebase_unavailable_reason = f"Firebase initialization failed: {exc}"
            return None

    return messaging


def firebase_status():
    messaging = _get_firebase_messaging()
    return {
        "configured": messaging is not None,
        "error": _firebase_unavailable_reason,
    }


def send_price_notification_to_user(*, user_id, product_id, event_type, title, body, data):
    messaging = _get_firebase_messaging()
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT id, token
                FROM user_device_tokens
                WHERE user_id = %s
                  AND enabled = TRUE
                """,
                (user_id,),
            )
            tokens = cur.fetchall()

            results = []
            for token_row in tokens:
                if messaging is None:
                    results.append(
                        _record_notification_event(
                            cur,
                            user_id=user_id,
                            product_id=product_id,
                            device_token_id=token_row["id"],
                            event_type=event_type,
                            title=title,
                            body=body,
                            data=data,
                            status="skipped",
                            error=_firebase_unavailable_reason,
                        )
                    )
                    continue

                try:
                    message = messaging.Message(
                        notification=messaging.Notification(title=title, body=body),
                        data={key: str(value) for key, value in data.items() if value is not None},
                        token=token_row["token"],
                    )
                    provider_message_id = messaging.send(message)
                    results.append(
                        _record_notification_event(
                            cur,
                            user_id=user_id,
                            product_id=product_id,
                            device_token_id=token_row["id"],
                            event_type=event_type,
                            title=title,
                            body=body,
                            data=data,
                            status="sent",
                            provider_message_id=provider_message_id,
                        )
                    )
                except Exception as exc:
                    results.append(
                        _record_notification_event(
                            cur,
                            user_id=user_id,
                            product_id=product_id,
                            device_token_id=token_row["id"],
                            event_type=event_type,
                            title=title,
                            body=body,
                            data=data,
                            status="failed",
                            error=str(exc),
                        )
                    )

            conn.commit()
    return results


def _record_notification_event(
    cur,
    *,
    user_id,
    product_id,
    device_token_id,
    event_type,
    title,
    body,
    data,
    status,
    provider_message_id=None,
    error=None,
):
    now = utc_now()
    cur.execute(
        """
        INSERT INTO notification_events (
            user_id,
            product_id,
            device_token_id,
            event_type,
            title,
            body,
            payload,
            status,
            provider_message_id,
            error,
            created_at,
            sent_at
        ) VALUES (%s, %s, %s, %s, %s, %s, %s::jsonb, %s, %s, %s, %s, %s)
        RETURNING id, status, error
        """,
        (
            user_id,
            product_id,
            device_token_id,
            event_type,
            title,
            body,
            json.dumps(data),
            status,
            provider_message_id,
            error,
            now,
            now if status == "sent" else None,
        ),
    )
    return cur.fetchone()


def notify_watchlists_for_price_change(product, *, old_price, new_price, has_drop, has_increase):
    if not (has_drop or has_increase):
        return []

    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT id, user_id, notify_on_drop, notify_on_increase, last_notified_price
                FROM user_watchlists
                WHERE product_id = %s
                  AND active = TRUE
                  AND user_id IS NOT NULL
                """,
                (product["id"],),
            )
            watchlists = cur.fetchall()

    notifications = []
    for watchlist in watchlists:
        should_notify = (
            has_drop and watchlist["notify_on_drop"]
        ) or (
            has_increase and watchlist["notify_on_increase"]
        )
        if not should_notify:
            continue
        if watchlist["last_notified_price"] == new_price:
            continue

        event_type = "price_drop" if has_drop else "price_increase"
        title = "Price drop" if has_drop else "Price increased"
        product_name = product.get("name") or "Tracked product"
        if has_drop:
            body = f"{product_name} dropped from {_format_money(old_price)} to {_format_money(new_price)}."
        else:
            body = f"{product_name} increased from {_format_money(old_price)} to {_format_money(new_price)}."
        data = {
            "event_type": event_type,
            "product_id": product["external_product_id"],
            "product_name": product_name,
            "old_price": old_price,
            "new_price": new_price,
            "product_url": product.get("product_url"),
        }

        results = send_price_notification_to_user(
            user_id=watchlist["user_id"],
            product_id=product["id"],
            event_type=event_type,
            title=title,
            body=body,
            data=data,
        )
        notifications.extend(results)

        if any(row.get("status") == "sent" for row in results):
            with get_conn() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        UPDATE user_watchlists
                        SET last_notified_price = %s
                        WHERE id = %s
                        """,
                        (new_price, watchlist["id"]),
                    )
                conn.commit()

    return notifications


def _format_money(value):
    if value is None:
        return "unknown"
    return f"${float(value):.2f}"


def get_price_history(product_id, *, user_id=None):
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT ph.price, ph.recorded_at
                FROM products p
                JOIN user_watchlists uw ON uw.product_id = p.id
                JOIN product_price_history ph ON ph.product_id = p.id
                WHERE p.external_product_id = %s
                  AND uw.user_id IS NOT DISTINCT FROM %s
                  AND uw.active = TRUE
                ORDER BY ph.recorded_at ASC, ph.id ASC
                """,
                (product_id, user_id),
            )
            return cur.fetchall()


def refresh_all_products(*, user_id=None, all_scopes=False):
    if all_scopes:
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT DISTINCT
                        p.external_product_id AS product_id,
                        p.product_url,
                        p.name,
                        p.current_price
                    FROM user_watchlists uw
                    JOIN products p ON p.id = uw.product_id
                    WHERE uw.active = TRUE
                    """
                )
                products = cur.fetchall()
    else:
        products = list_products(user_id=user_id)
    drops = []
    increases = []
    errors = []
    updated = []

    seen = set()
    for p in products:
        if p["product_id"] in seen:
            continue
        seen.add(p["product_id"])
        try:
            snapshot = resolve_product_snapshot(p["product_url"], allow_cache=False)
            old_price = p["current_price"]
            product, _ = upsert_product_snapshot(snapshot)

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

            notification_results = notify_watchlists_for_price_change(
                product,
                old_price=old_price,
                new_price=snapshot.price,
                has_drop=has_drop,
                has_increase=has_increase,
            )
            if notification_results:
                entry["notifications"] = [
                    {
                        "id": row.get("id"),
                        "status": row.get("status"),
                        "error": row.get("error"),
                    }
                    for row in notification_results
                ]

        except Exception as exc:
            mark_product_refresh_error(p["product_id"], str(exc))
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
    def do_OPTIONS(self):
        self.send_response(204)
        self._send_cors_headers()
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Access-Control-Max-Age", "86400")
        self.end_headers()

    def do_GET(self):
        parsed = urlparse(self.path)
        params = parse_qs(parsed.query)
        current_user = self._get_current_user()
        current_user_id = current_user["id"] if current_user else None

        if parsed.path in ("/", "/dashboard", "/pricecompare.html"):
            self._send(
                200,
                {
                    "message": "PriceWatch backend API is running.",
                    "frontend": "Use the Vite app at http://127.0.0.1:3000",
                },
            )
            return

        if parsed.path == "/product":
            target = (params.get("target") or [""])[0].strip()
            if not target:
                self._send(400, {"error": "missing ?target="})
                return
            try:
                snapshot = resolve_product_snapshot(target, allow_cache=True)
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
                snapshot = resolve_product_snapshot(target, allow_cache=True)
                add_product_to_watchlist(snapshot, user_id=current_user_id)
                self._send(200, snapshot.to_dict())
            except Exception as exc:
                try:
                    product = queue_product_for_scheduled_refresh(
                        target,
                        user_id=current_user_id,
                        error_message=f"Live price check failed: {exc}",
                    )
                    self._send(
                        202,
                        {
                            **serialise_product_row(product),
                            "queued": True,
                            "message": "Saved for the next scheduled price check.",
                        },
                    )
                except Exception as queue_exc:
                    self._send(500, {"error": str(queue_exc)})
            return

        if parsed.path == "/refresh":
            product_id = (params.get("product_id") or [""])[0].strip()
            if not product_id:
                self._send(400, {"error": "missing ?product_id="})
                return
            try:
                item = get_watchlist_product(product_id, user_id=current_user_id)
                if not item:
                    self._send(404, {"error": "Product not found in watchlist."})
                    return
                snapshot = resolve_product_snapshot(item["product_url"], allow_cache=False)
                add_product_to_watchlist(snapshot, user_id=current_user_id)
                self._send(200, serialise_product_row(get_watchlist_product(product_id, user_id=current_user_id)))
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

        if parsed.path == "/notifications/status":
            self._send(200, firebase_status())
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

        if parsed.path == "/notification-settings":
            current_user = self._get_current_user()
            current_user_id = current_user["id"] if current_user else None
            try:
                product_id = (payload.get("product_id") or "").strip()
                if not product_id:
                    raise ValueError("Product identifier is required.")
                notify_on_drop = bool(payload.get("notify_on_drop"))
                item = update_watchlist_notification_settings(
                    product_id,
                    user_id=current_user_id,
                    notify_on_drop=notify_on_drop,
                )
                if not item:
                    self._send(404, {"error": "Product not found in watchlist."})
                    return
                self._send(200, serialise_product_row(item))
            except ValueError as exc:
                self._send(400, {"error": str(exc)})
            except Exception as exc:
                self._send(500, {"error": str(exc)})
            return

        if parsed.path == "/notification-token":
            current_user = self._get_current_user()
            current_user_id = current_user["id"] if current_user else None
            try:
                row = register_device_token(
                    user_id=current_user_id,
                    token=payload.get("token"),
                    platform=payload.get("platform"),
                    device_label=payload.get("device_label"),
                )
                self._send(
                    200,
                    {
                        "ok": True,
                        "device_token": {
                            "id": row["id"],
                            "platform": row.get("platform"),
                            "device_label": row.get("device_label"),
                            "enabled": row.get("enabled"),
                            "last_seen_at": row.get("last_seen_at"),
                        },
                    },
                )
            except ValueError as exc:
                self._send(400, {"error": str(exc)})
            except Exception as exc:
                self._send(500, {"error": str(exc)})
            return

        if parsed.path == "/notification-token/remove":
            current_user = self._get_current_user()
            current_user_id = current_user["id"] if current_user else None
            try:
                disabled = disable_device_token(
                    user_id=current_user_id,
                    token=payload.get("token"),
                )
                self._send(200, {"ok": True, "disabled": disabled})
            except ValueError as exc:
                self._send(400, {"error": str(exc)})
            except Exception as exc:
                self._send(500, {"error": str(exc)})
            return

        if parsed.path == "/notifications/test":
            current_user = self._get_current_user()
            current_user_id = current_user["id"] if current_user else None
            try:
                if not current_user_id:
                    raise ValueError("You must be logged in to test notifications.")
                results = send_price_notification_to_user(
                    user_id=current_user_id,
                    product_id=None,
                    event_type="test",
                    title="Price Drop notifications are ready",
                    body="Your device can receive alerts from Price Drop.",
                    data={"event_type": "test"},
                )
                self._send(
                    200,
                    {
                        "ok": True,
                        "notifications": [
                            {
                                "id": row.get("id"),
                                "status": row.get("status"),
                                "error": row.get("error"),
                            }
                            for row in results
                        ],
                    },
                )
            except ValueError as exc:
                self._send(400, {"error": str(exc)})
            except Exception as exc:
                self._send(500, {"error": str(exc)})
            return

        if parsed.path == "/save-preview":
            current_user = self._get_current_user()
            current_user_id = current_user["id"] if current_user else None
            try:
                snapshot = snapshot_from_payload(payload)
                add_product_to_watchlist(snapshot, user_id=current_user_id)
                self._send(200, snapshot.to_dict())
            except ValueError as exc:
                self._send(400, {"error": str(exc)})
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
        secure = " Secure;" if SESSION_COOKIE_SECURE else ""
        return {
            "Set-Cookie": (
                f"{SESSION_COOKIE_NAME}={token}; Path=/; HttpOnly; SameSite={SESSION_COOKIE_SAMESITE};{secure} "
                f"Expires={expires_at.strftime('%a, %d %b %Y %H:%M:%S GMT')}"
            )
        }

    def _clear_session_headers(self):
        secure = " Secure;" if SESSION_COOKIE_SECURE else ""
        return {
            "Set-Cookie": (
                f"{SESSION_COOKIE_NAME}=; Path=/; HttpOnly; SameSite={SESSION_COOKIE_SAMESITE};{secure} "
                "Expires=Thu, 01 Jan 1970 00:00:00 GMT"
            )
        }

    def _send_cors_headers(self):
        origin = self.headers.get("Origin")
        if origin in FRONTEND_ORIGINS:
            self.send_header("Access-Control-Allow-Origin", origin)
            self.send_header("Access-Control-Allow-Credentials", "true")
            self.send_header("Vary", "Origin")

    def _send(self, status, data, *, headers=None):
        body = json.dumps(data, default=self._json_default).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self._send_cors_headers()
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
