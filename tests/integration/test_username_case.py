"""
Integration tests for case-insensitive usernames (P-0011).

Covers cap-001 end to end (invite rejects a case variant, login accepts one),
cap-002 (migration 007: fold, collision auto-rename, CHECK constraint), and
cap-003 (a migration WARNING reaches the platform logger).

Every test owns a throwaway database and drops it afterwards — the live
`latarnia_platform_dev` is never touched. Skipped when Postgres is unreachable.
"""
import logging
import os
import time
from pathlib import Path

import psycopg
import pyotp
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from psycopg.rows import dict_row

from latarnia.auth import AuthDB
from latarnia.auth.jwt_auth import JWTAuth
from latarnia.auth.providers import TOTPAuthProvider
from latarnia.auth.routes import build_auth_router
from latarnia.auth.sessions import SessionStore
from latarnia.auth.tokens import MachineTokenStore
from latarnia.auth.users import BOOTSTRAP_USERNAME, UserStore
from latarnia.core.config import ConfigManager
from latarnia.core.pg_client import PgClient

COOKIE = "latarnia_session"
MIGRATIONS = Path(__file__).parents[2] / "src" / "latarnia" / "auth" / "migrations"
USERS_DDL = (MIGRATIONS / "001_create_users.sql").read_text()
MIG_007 = (MIGRATIONS / "007_lowercase_usernames.sql").read_text()

DB_MIGRATION = "latarnia_platform_test_username_case"
DB_E2E = "latarnia_platform_test_username_case_e2e"
DB_NOTICE = "latarnia_platform_test_username_case_notice"


def _cfg_and_pg(monkeypatch):
    monkeypatch.setenv("ENV", "dev")  # relaxes Secure cookie for the http TestClient
    cfg = ConfigManager()
    cfg.load_config()
    pg = PgClient(cfg)
    if not pg.check_connectivity():
        pytest.skip("Postgres not reachable")
    return cfg, pg


# ============================================================ cap-002 fixture

@pytest.fixture
def bare(monkeypatch):
    """A throwaway DB holding only the `users` table from migration 001.

    Yields an autocommit psycopg connection. Migration 007 is applied by each
    test via `_apply_007` so the pre-migration state can be seeded first.
    """
    cfg, pg = _cfg_and_pg(monkeypatch)
    if pg.database_exists(DB_MIGRATION):
        pg.drop_database(DB_MIGRATION)
    pg.create_plain_database(DB_MIGRATION)
    conn = psycopg.connect(
        cfg.get_postgres_dsn(DB_MIGRATION), autocommit=True, row_factory=dict_row
    )
    conn.execute(USERS_DDL)
    yield conn
    conn.close()
    pg.drop_database(DB_MIGRATION)


def _seed(conn, username, created_at):
    """Insert a user with an explicit created_at (drives rename ordering)."""
    row = conn.execute(
        "INSERT INTO users (username, created_at) VALUES (%s, %s) RETURNING id",
        (username, created_at),
    ).fetchone()
    return row["id"]


def _apply_007(conn):
    # No params -> psycopg uses the simple protocol, so the multi-statement
    # migration body runs exactly as AuthDB._run_migrations executes it.
    conn.execute(MIG_007)


def _names(conn):
    rows = conn.execute(
        "SELECT username FROM users ORDER BY created_at, id"
    ).fetchall()
    return [r["username"] for r in rows]


# ============================================================ cap-002 tests

def test_migration_007_folds_existing(bare):
    uid = _seed(bare, "Felipe", "2026-01-01")
    _apply_007(bare)
    row = bare.execute("SELECT id, username FROM users").fetchone()
    assert row["username"] == "felipe"
    assert row["id"] == uid  # same identity, only the label changed


def test_migration_007_leaves_lowercase_alone(bare):
    _seed(bare, "admin", "2026-01-01")
    before = bare.execute("SELECT username, created_at FROM users").fetchone()
    _apply_007(bare)
    after = bare.execute("SELECT username, created_at FROM users").fetchone()
    assert after == before


def test_migration_007_renames_newer_collision(bare):
    old = _seed(bare, "felipe", "2026-01-01")
    new = _seed(bare, "Felipe", "2026-02-01")
    _apply_007(bare)
    assert _names(bare) == ["felipe", "felipe2"]
    ids = {r["id"] for r in bare.execute("SELECT id FROM users").fetchall()}
    assert ids == {old, new}
    assert bare.execute("SELECT COUNT(*) AS n FROM users").fetchone()["n"] == 2


def test_migration_007_suffix_skips_taken(bare):
    _seed(bare, "felipe", "2026-01-01")
    _seed(bare, "felipe2", "2026-01-15")
    _seed(bare, "Felipe", "2026-02-01")
    _apply_007(bare)
    # 2 is already taken by an untouched row, so the collision lands on 3.
    assert _names(bare) == ["felipe", "felipe2", "felipe3"]


def test_migration_007_resolves_three_way_collision(bare):
    _seed(bare, "felipe", "2026-01-01")
    _seed(bare, "Felipe", "2026-02-01")
    _seed(bare, "FELIPE", "2026-03-01")
    _apply_007(bare)
    assert _names(bare) == ["felipe", "felipe2", "felipe3"]


def test_migration_007_check_rejects_uppercase(bare):
    _apply_007(bare)
    with pytest.raises(psycopg.errors.CheckViolation) as exc:
        bare.execute("INSERT INTO users (username) VALUES ('Bob')")
    assert "users_username_lowercase" in str(exc.value)


def test_migration_007_idempotent(bare):
    _seed(bare, "felipe", "2026-01-01")
    _seed(bare, "Felipe", "2026-02-01")
    _apply_007(bare)
    first = _names(bare)
    _apply_007(bare)  # must not raise, must not rename again
    assert _names(bare) == first == ["felipe", "felipe2"]


def test_migration_007_long_name_stays_within_64(bare):
    _seed(bare, "a" * 64, "2026-01-01")
    _seed(bare, "A" * 64, "2026-02-01")
    _apply_007(bare)
    names = _names(bare)
    assert names[0] == "a" * 64
    assert names[1] == "a" * 62 + "2"
    assert len(names[1]) == 63  # left(name, 62) + one digit


def test_migration_007_no_collisions_is_a_noop(bare):
    _seed(bare, "admin", "2026-01-01")
    _seed(bare, "Bob", "2026-02-01")
    _apply_007(bare)
    assert _names(bare) == ["admin", "bob"]


# ============================================================ cap-001 fixture

@pytest.fixture
def ctx(monkeypatch):
    """Full auth stack on a throwaway DB with all migrations (001-007) applied."""
    cfg, pg = _cfg_and_pg(monkeypatch)
    db = AuthDB(cfg, pg)
    db.db_name = DB_E2E
    if pg.database_exists(DB_E2E):
        pg.drop_database(DB_E2E)
    assert db.initialize()

    totp_key = os.urandom(32)
    jwt_secret = os.urandom(32).hex()
    users = UserStore(db)
    sessions = SessionStore(db, cfg)
    totp = TOTPAuthProvider(db, lambda: totp_key, issuer="Test")
    jwt_auth = JWTAuth(lambda: jwt_secret)
    token_store = MachineTokenStore(db, jwt_auth)
    app = FastAPI()
    app.include_router(
        build_auth_router(db, users, sessions, totp, cfg,
                         jwt_auth=jwt_auth, token_store=token_store)
    )
    client = TestClient(app, follow_redirects=False)

    yield {"client": client, "db": db, "users": users, "totp": totp}

    pg.drop_database(DB_E2E)


def _complete_first_setup(ctx):
    """Enroll and activate the bootstrap superuser. Returns (user, secret, cookie)."""
    client, users, totp = ctx["client"], ctx["users"], ctx["totp"]
    assert client.get("/auth/setup").status_code == 200
    user = users.get_user_by_username(BOOTSTRAP_USERNAME)
    secret = totp.get_existing_secret(user["id"])
    r = client.post("/auth/setup", data={"code": pyotp.TOTP(secret).now()})
    assert r.status_code == 303
    return user, secret, r.cookies[COOKIE]


def _code_for(secret, offset_windows=0):
    return pyotp.TOTP(secret).at(int(time.time()) + offset_windows * 30)


# ============================================================ cap-001 tests

def test_invite_stores_lowercase(ctx):
    client, db = ctx["client"], ctx["db"]
    _admin, _secret, admin_token = _complete_first_setup(ctx)

    client.cookies.clear()
    r = client.post("/api/auth/users", json={"username": "Felipe"},
                    cookies={COOKIE: admin_token})
    assert r.status_code == 200
    row = db.query_one("SELECT username FROM users WHERE username <> 'admin'")
    assert row["username"] == "felipe"


def test_invite_duplicate_is_case_insensitive(ctx):
    client, db = ctx["client"], ctx["db"]
    _admin, _secret, admin_token = _complete_first_setup(ctx)

    client.cookies.clear()
    assert client.post("/api/auth/users", json={"username": "felipe"},
                       cookies={COOKIE: admin_token}).status_code == 200

    # A case variant of an existing username is now a conflict, not a new user.
    client.cookies.clear()
    r = client.post("/api/auth/users", json={"username": "Felipe"},
                    cookies={COOKIE: admin_token})
    assert r.status_code == 409
    assert r.json()["detail"] == "username already exists"

    n = db.query_one(
        "SELECT COUNT(*) AS n FROM users WHERE lower(username) = 'felipe'"
    )["n"]
    assert n == 1


def test_invite_duplicate_of_bootstrap_superuser_rejected(ctx):
    client = ctx["client"]
    _admin, _secret, admin_token = _complete_first_setup(ctx)
    client.cookies.clear()
    r = client.post("/api/auth/users", json={"username": "ADMIN"},
                    cookies={COOKIE: admin_token})
    assert r.status_code == 409


def test_login_accepts_mixed_case(ctx):
    client = ctx["client"]
    _admin, secret, _token = _complete_first_setup(ctx)
    client.cookies.clear()

    # Enrolled as "admin", logging in as "ADMIN". Next TOTP window so the code
    # isn't a replay of the setup window.
    r = client.post("/auth/login",
                    data={"username": "ADMIN", "code": _code_for(secret, 1)})
    assert r.status_code == 303
    assert r.headers["location"] == "/dashboard"
    assert COOKIE in r.cookies


def test_login_accepts_surrounding_whitespace(ctx):
    client = ctx["client"]
    _admin, secret, _token = _complete_first_setup(ctx)
    client.cookies.clear()
    r = client.post("/auth/login",
                    data={"username": "  Admin  ", "code": _code_for(secret, 1)})
    assert r.status_code == 303
    assert COOKIE in r.cookies


def test_login_still_rejects_unknown_user(ctx):
    client = ctx["client"]
    _complete_first_setup(ctx)
    client.cookies.clear()
    r = client.post("/auth/login",
                    data={"username": "NoSuchPerson", "code": "000000"})
    assert r.status_code == 401
    assert "Invalid username or code." in r.text
    assert COOKIE not in r.cookies


# ============================================================ cap-003 test

def test_migration_warning_reaches_logger_end_to_end(monkeypatch, tmp_path, caplog):
    """A RAISE WARNING inside a migration must surface on latarnia.auth.db."""
    cfg, pg = _cfg_and_pg(monkeypatch)
    (tmp_path / "001_warn.sql").write_text(
        "DO $$ BEGIN RAISE WARNING 'boom'; END $$;"
    )
    db = AuthDB(cfg, pg)
    db.db_name = DB_NOTICE
    db.migrations_dir = tmp_path
    if pg.database_exists(DB_NOTICE):
        pg.drop_database(DB_NOTICE)
    try:
        with caplog.at_level(logging.DEBUG, logger="latarnia.auth.db"):
            assert db.initialize()
        assert any(
            r.name == "latarnia.auth.db"
            and r.levelno == logging.WARNING
            and "boom" in r.getMessage()
            for r in caplog.records
        )
    finally:
        pg.drop_database(DB_NOTICE)
