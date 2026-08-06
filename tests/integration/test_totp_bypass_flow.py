"""
Integration test for the dev-only TOTP bypass over real HTTP (T-0010).

Proves the thing the bypass exists for — an automated browser can log in with a
throwaway code — and the thing that makes it safe: the same request is rejected
when the bypass predicate is off.

Owns a throwaway database and drops it afterwards. Skipped when Postgres is
unreachable.
"""
import os

import pyotp
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

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
TEST_DB = "latarnia_platform_test_totp_bypass"


def _stack(monkeypatch, dev_bypass):
    """Full auth router on a throwaway DB. Returns (client, ctx, teardown)."""
    monkeypatch.setenv("ENV", "dev")  # relaxes the Secure cookie for http TestClient
    cfg = ConfigManager()
    cfg.load_config()
    pg = PgClient(cfg)
    if not pg.check_connectivity():
        pytest.skip("Postgres not reachable")

    db = AuthDB(cfg, pg)
    db.db_name = TEST_DB
    if pg.database_exists(TEST_DB):
        pg.drop_database(TEST_DB)
    assert db.initialize()

    totp_key = os.urandom(32)
    users = UserStore(db)
    sessions = SessionStore(db, cfg)
    totp = TOTPAuthProvider(db, lambda: totp_key, issuer="Test",
                            dev_bypass=dev_bypass)
    jwt_auth = JWTAuth(lambda: os.urandom(32).hex())
    token_store = MachineTokenStore(db, jwt_auth)
    app = FastAPI()
    app.include_router(
        build_auth_router(db, users, sessions, totp, cfg,
                         jwt_auth=jwt_auth, token_store=token_store)
    )
    client = TestClient(app, follow_redirects=False)
    return client, {"users": users, "totp": totp, "pg": pg}


@pytest.fixture
def bypassed(monkeypatch):
    client, ctx = _stack(monkeypatch, dev_bypass=lambda: True)
    yield client, ctx
    ctx["pg"].drop_database(TEST_DB)


@pytest.fixture
def normal(monkeypatch):
    client, ctx = _stack(monkeypatch, dev_bypass=None)
    yield client, ctx
    ctx["pg"].drop_database(TEST_DB)


def _enroll_admin_normally(client, ctx):
    """Activate the bootstrap superuser using a real code (bypass-independent)."""
    assert client.get("/auth/setup").status_code == 200
    user = ctx["users"].get_user_by_username(BOOTSTRAP_USERNAME)
    secret = ctx["totp"].get_existing_secret(user["id"])
    r = client.post("/auth/setup", data={"code": pyotp.TOTP(secret).now()})
    assert r.status_code == 303
    client.cookies.clear()
    return user


def test_login_with_bypass_accepts_wrong_code(bypassed):
    client, ctx = bypassed
    _enroll_admin_normally(client, ctx)

    r = client.post("/auth/login", data={"username": "admin", "code": "000000"})
    assert r.status_code == 303
    assert r.headers["location"] == "/dashboard"
    assert COOKIE in r.cookies


def test_login_without_bypass_rejects_wrong_code(normal):
    client, ctx = normal
    _enroll_admin_normally(client, ctx)

    r = client.post("/auth/login", data={"username": "admin", "code": "000000"})
    assert r.status_code == 401
    assert "Invalid username or code." in r.text
    assert COOKIE not in r.cookies


def test_repeated_logins_with_bypass_all_succeed(bypassed):
    """Replay rejection is what breaks per-test logins; the bypass sidesteps it."""
    client, ctx = bypassed
    _enroll_admin_normally(client, ctx)

    for _ in range(3):
        r = client.post("/auth/login",
                        data={"username": "admin", "code": "000000"})
        assert r.status_code == 303
        assert COOKIE in r.cookies
        client.cookies.clear()


def test_bypass_still_rejects_unknown_user(bypassed):
    """The bypass skips TOTP, not identity — an unknown username is still 401."""
    client, ctx = bypassed
    _enroll_admin_normally(client, ctx)

    r = client.post("/auth/login",
                    data={"username": "nobody", "code": "000000"})
    assert r.status_code == 401
    assert COOKIE not in r.cookies


def test_bypass_still_rejects_inactive_user(bypassed):
    """An invited-but-not-enrolled user cannot log in even with the bypass on."""
    client, ctx = bypassed
    _enroll_admin_normally(client, ctx)
    ctx["users"].create_user("ghost")  # inactive, never enrolled

    r = client.post("/auth/login",
                    data={"username": "ghost", "code": "000000"})
    assert r.status_code == 401
    assert COOKIE not in r.cookies


def test_bypass_completes_first_run_setup_without_authenticator(bypassed):
    """The payoff for a fresh dev DB: no QR scan needed to get a superuser."""
    client, ctx = bypassed
    assert client.get("/auth/setup").status_code == 200
    r = client.post("/auth/setup", data={"code": "000000"})
    assert r.status_code == 303
    assert COOKIE in r.cookies
    admin = ctx["users"].get_user_by_username(BOOTSTRAP_USERNAME)
    assert admin["is_superuser"] and admin["is_active"]
