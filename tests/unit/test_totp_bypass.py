"""Unit tests for the dev-only TOTP bypass (T-0010).

Two halves: the gate that decides whether a bypass is permissible at all
(auth/dev_bypass.py), and the provider behaviour once it is active
(auth/providers/totp.py). The gate tests matter most — they are what keeps this
from being reachable in tst or prd.
"""
import json
import logging
from unittest.mock import Mock

import pyotp
import pytest

from latarnia.auth.dev_bypass import (
    DEV_TOTP_BYPASS_SECRET,
    dev_totp_bypass_enabled,
    is_truthy,
)
from latarnia.auth.providers.totp import TOTPAuthProvider

KEY = b"\x01" * 32


def _loader():
    return KEY


def _provider_with_real_secret(dev_bypass=None):
    """Provider whose stubbed db holds a genuine encrypted TOTP secret."""
    secret = pyotp.random_base32()
    enc = TOTPAuthProvider.encrypt_secret(secret, KEY)
    db = Mock()
    db.query_one.return_value = {
        "credential_data": {"totp_secret_enc": enc, "last_totp_window": 0}
    }
    db.execute_returning.return_value = {"id": "cred1"}
    provider = TOTPAuthProvider(db, _loader, dev_bypass=dev_bypass)
    return provider, db, secret


# =================================================== the gate (dev_bypass.py)

def _gate(env, secret_value, on_load=None):
    """Call the gate with a raw ENV value, exactly as main.py's `_raw_env` yields."""
    def secret_loader(name):
        if on_load is not None:
            on_load(name)
        return secret_value if name == DEV_TOTP_BYPASS_SECRET else None

    return dev_totp_bypass_enabled(lambda: env, secret_loader)


def test_enabled_in_dev_with_secret():
    assert _gate("dev", "1") is True


def test_not_enabled_in_dev_without_secret():
    assert _gate("dev", None) is False


def test_not_enabled_in_tst_with_secret():
    assert _gate("tst", "1") is False


def test_not_enabled_in_prd_with_secret():
    assert _gate("prd", "1") is False


def test_non_dev_env_does_not_read_secrets_file():
    """ENV is checked first, so a prd login never touches secrets.env."""
    def explode(name):
        raise AssertionError("secret_loader must not be called when ENV != dev")

    assert _gate("prd", "1", on_load=explode) is False


# --------------------------------------------------------------------------
# The gate must read the RAW ENV, never ConfigManager.get_env(), which falls
# back to "dev" for anything it does not recognise — including an unset ENV and
# a stray trailing space. Delegating to it would make condition 1 fail OPEN on a
# prd host with a typo, which is the entire failure mode this design exists to
# prevent. Each value below is one get_env() would report as "dev".
# --------------------------------------------------------------------------

@pytest.mark.parametrize(
    "raw_env",
    [
        "PRD ",         # trailing space — plausible systemd Environment= typo
        " prd",
        "prd ",
        "Prod",
        "production",
        "PROD",
        "",             # ENV= with no value
        None,           # ENV absent entirely
        "DEV",          # right env, wrong case — still refused (fail closed)
        " dev ",        # right env, stray whitespace — still refused
        "Dev",
    ],
)
def test_gate_refuses_every_env_that_get_env_would_coerce_to_dev(raw_env):
    assert _gate(raw_env, "1") is False


def test_gate_accepts_only_the_exact_literal_dev():
    assert _gate("dev", "1") is True


def test_config_get_env_really_does_coerce_these_to_dev(monkeypatch):
    """Pins the premise of the test above — if this ever changes, revisit the gate.

    Documents *why* the gate does not call get_env(): these values are not dev,
    yet get_env() reports them as dev.
    """
    from latarnia.core.config import ConfigManager

    for raw_env in ("PRD ", "production", "Prod"):
        monkeypatch.setenv("ENV", raw_env)
        assert ConfigManager().get_env() == "dev"
        # ...and the gate is not fooled by any of them.
        assert _gate(raw_env, "1") is False

    monkeypatch.delenv("ENV", raising=False)
    assert ConfigManager().get_env() == "dev"
    assert _gate(None, "1") is False


@pytest.mark.parametrize("value", ["1", "true", "TRUE", "True", "yes", "on", " 1 "])
def test_truthy_parsing_accepts(value):
    assert is_truthy(value) is True


@pytest.mark.parametrize(
    "value", ["0", "false", "no", "off", "", "   ", None, "maybe", "2"]
)
def test_truthy_parsing_rejects(value):
    assert is_truthy(value) is False


# ============================================ the provider (providers/totp.py)

def test_bypass_off_by_default():
    """No dev_bypass argument -> the bypass branch does not exist."""
    provider, _db, secret = _provider_with_real_secret()
    wrong = "000000"
    # Guard against the 1-in-a-million case where the real code is 000000.
    if pyotp.TOTP(secret).now() == wrong:
        wrong = "000001"
    assert provider.validate("u1", {"code": wrong}) is False


def test_bypass_accepts_any_six_digit_code():
    provider, db, _secret = _provider_with_real_secret(dev_bypass=lambda: True)
    assert provider.validate("u1", {"code": "000000"}) is True
    # Short-circuits before any credential lookup.
    db.query_one.assert_not_called()
    db.execute_returning.assert_not_called()


def test_bypass_still_requires_six_digits():
    provider, _db, _secret = _provider_with_real_secret(dev_bypass=lambda: True)
    assert provider.validate("u1", {"code": "12345"}) is False
    assert provider.validate("u1", {"code": ""}) is False
    assert provider.validate("u1", {}) is False


def test_bypass_defeats_replay():
    """The obstacle a naive 'accept any code' fix would leave in place."""
    provider, _db, _secret = _provider_with_real_secret(dev_bypass=lambda: True)
    assert provider.validate("u1", {"code": "000000"}) is True
    assert provider.validate("u1", {"code": "000000"}) is True


def test_bypass_not_applied_when_predicate_false():
    provider, _db, secret = _provider_with_real_secret(dev_bypass=lambda: False)
    wrong = "000000"
    if pyotp.TOTP(secret).now() == wrong:
        wrong = "000001"
    assert provider.validate("u1", {"code": wrong}) is False
    # Real validation still works with the predicate present but false.
    assert provider.validate("u1", {"code": pyotp.TOTP(secret).now()}) is True


def test_bypass_logs_warning(caplog):
    provider, _db, _secret = _provider_with_real_secret(dev_bypass=lambda: True)
    with caplog.at_level(logging.WARNING, logger="latarnia.auth.totp"):
        provider.validate("user-42", {"code": "000000"})
    warnings = [r for r in caplog.records
                if r.name == "latarnia.auth.totp" and r.levelno == logging.WARNING]
    assert len(warnings) == 1
    msg = warnings[0].getMessage()
    assert "user-42" in msg and "BYPASSED" in msg


def test_real_validation_unaffected_without_bypass():
    """Regression guard: the normal happy path still works untouched."""
    provider, _db, secret = _provider_with_real_secret()
    assert provider.validate("u1", {"code": pyotp.TOTP(secret).now()}) is True
