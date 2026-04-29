"""
Unit tests for SecretManager (P-0006).
"""
import logging
import os
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "src"))

from latarnia.core.config import ConfigManager
from latarnia.managers.app_manager import AppManager, AppRegistry
from latarnia.managers.secret_manager import (
    SecretManager,
    ValidationResult,
    SecretMetadata,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def env_root(tmp_path):
    """Simulate /opt/latarnia/{env}/ layout in a tmp dir."""
    (tmp_path / "data").mkdir()
    return tmp_path


@pytest.fixture
def mock_config_manager(env_root):
    cm = Mock(spec=ConfigManager)
    cm.get_data_dir.return_value = env_root / "data"
    return cm


@pytest.fixture
def mock_app_manager():
    am = Mock(spec=AppManager)
    am.registry = Mock(spec=AppRegistry)
    am.registry.get_all_apps.return_value = []
    return am


@pytest.fixture
def secret_manager(mock_config_manager, mock_app_manager):
    return SecretManager(mock_config_manager, mock_app_manager, env="dev")


def _write_master(env_root: Path, content: str, mode: int = 0o600) -> Path:
    path = env_root / "secrets.env"
    path.write_text(content)
    os.chmod(path, mode)
    return path


def _app_entry(app_id: str, requires_secrets: list[str]):
    """Minimal duck-typed app entry for SecretManager calls."""
    config = SimpleNamespace(requires_secrets=requires_secrets)
    manifest = SimpleNamespace(config=config)
    return SimpleNamespace(app_id=app_id, manifest=manifest)


# ---------------------------------------------------------------------------
# cap-002: load() + parse + permission check
# ---------------------------------------------------------------------------

class TestParseAndLoad:

    def test_parse_dotenv_happy_path(self, secret_manager):
        text = "KEY1=val1\nKEY2=val2\n"
        assert SecretManager._parse_dotenv(text) == {"KEY1": "val1", "KEY2": "val2"}

    def test_parse_dotenv_handles_comments_and_blanks(self, secret_manager):
        text = "# top comment\n\nKEY1=val1\n\n  # indented comment\nKEY2=val2\n"
        assert SecretManager._parse_dotenv(text) == {"KEY1": "val1", "KEY2": "val2"}

    def test_parse_dotenv_single_quoted_value_kept_literal(self, secret_manager):
        text = "KEY=" + "'value with $ and = and spaces'\n"
        assert SecretManager._parse_dotenv(text) == {"KEY": "value with $ and = and spaces"}

    def test_parse_dotenv_rejects_line_without_equals(self, secret_manager):
        with pytest.raises(ValueError):
            SecretManager._parse_dotenv("NOT_VALID\n")

    def test_parse_dotenv_rejects_empty_key(self, secret_manager):
        with pytest.raises(ValueError):
            SecretManager._parse_dotenv("=foo\n")

    def test_load_missing_file_returns_empty(self, secret_manager):
        """No file → no warning, returns empty dict."""
        assert secret_manager.load() == {}

    def test_load_happy_path(self, secret_manager, env_root):
        _write_master(env_root, "KEY1=val1\n# c\n\nKEY2=val2\n", mode=0o600)
        assert secret_manager.load() == {"KEY1": "val1", "KEY2": "val2"}

    def test_load_refuses_loose_mode(self, secret_manager, env_root, caplog):
        _write_master(env_root, "KEY1=val1\n", mode=0o644)
        with caplog.at_level(logging.WARNING, logger="latarnia.secret_manager"):
            result = secret_manager.load()
        assert result == {}
        assert any("too permissive" in rec.message for rec in caplog.records)
        # The warning must NOT contain the value.
        assert all("val1" not in rec.message for rec in caplog.records)

    def test_load_logs_only_count_not_values(self, secret_manager, env_root, caplog):
        _write_master(env_root, "SENTINEL=xyz123\n", mode=0o600)
        with caplog.at_level(logging.INFO, logger="latarnia.secret_manager"):
            secret_manager.load()
        assert all("xyz123" not in rec.message for rec in caplog.records)
        assert any("Loaded 1 secret" in rec.message for rec in caplog.records)

    def test_load_handles_malformed_file(self, secret_manager, env_root, caplog):
        _write_master(env_root, "VALID=ok\nNOT_VALID_LINE\n", mode=0o600)
        with caplog.at_level(logging.ERROR, logger="latarnia.secret_manager"):
            assert secret_manager.load() == {}
        assert any("Failed to parse" in rec.message for rec in caplog.records)


# ---------------------------------------------------------------------------
# cap-005: validation
# ---------------------------------------------------------------------------

class TestValidate:

    def test_no_declared_secrets_always_ok(self, secret_manager):
        app = _app_entry("a", [])
        assert secret_manager.validate(app) == ValidationResult(ok=True)

    def test_all_declared_present_ok(self, secret_manager, env_root):
        _write_master(env_root, "A=1\nB=2\n", mode=0o600)
        app = _app_entry("a", ["A", "B"])
        assert secret_manager.validate(app).ok is True

    def test_missing_secret_reports_first_missing(self, secret_manager, env_root):
        _write_master(env_root, "A=1\n", mode=0o600)
        app = _app_entry("a", ["A", "B", "C"])
        result = secret_manager.validate(app)
        assert result.ok is False
        assert result.missing == ["B", "C"]
        assert "missing required secret: B" in result.detail

    def test_no_master_file_reports_all_missing(self, secret_manager):
        app = _app_entry("a", ["A", "B"])
        result = secret_manager.validate(app)
        assert result.ok is False
        assert result.missing == ["A", "B"]


# ---------------------------------------------------------------------------
# cap-003: materialize() writes filtered file
# ---------------------------------------------------------------------------

class TestMaterialize:

    def test_writes_only_declared_keys_with_mode_600(self, secret_manager, env_root):
        _write_master(env_root, "A=1\nB=2\nC=3\n", mode=0o600)
        app = _app_entry("myapp", ["A", "B"])

        result, path = secret_manager.materialize(app)

        assert result.ok is True
        assert path == env_root / "secrets" / "myapp.env"
        assert path.exists()
        # Filtered: only A and B, not C; declaration order preserved.
        assert path.read_text() == "A=1\nB=2\n"
        # Mode 600.
        assert (path.stat().st_mode & 0o777) == 0o600
        # Parent dir mode 700.
        assert ((env_root / "secrets").stat().st_mode & 0o777) == 0o700

    def test_no_declared_secrets_writes_nothing(self, secret_manager):
        app = _app_entry("myapp", [])
        result, path = secret_manager.materialize(app)
        assert result.ok is True
        assert path is None
        # `secrets/` dir not created when nothing to write.
        assert not (secret_manager.per_app_dir).exists()

    def test_validation_failure_writes_no_file(self, secret_manager, env_root):
        _write_master(env_root, "A=1\n", mode=0o600)  # B missing
        app = _app_entry("myapp", ["A", "B"])

        result, path = secret_manager.materialize(app)

        assert result.ok is False
        assert path is None
        # No per-app file was written.
        assert not (env_root / "secrets" / "myapp.env").exists()

    def test_materialize_overwrites_stale_file(self, secret_manager, env_root):
        _write_master(env_root, "A=new\n", mode=0o600)
        # Pre-existing stale per-app file with old content.
        (env_root / "secrets").mkdir(mode=0o700)
        stale = env_root / "secrets" / "myapp.env"
        stale.write_text("A=stale\nGHOST=value\n")
        os.chmod(stale, 0o600)

        app = _app_entry("myapp", ["A"])
        result, path = secret_manager.materialize(app)

        assert result.ok is True
        assert path.read_text() == "A=new\n"  # GHOST gone

    def test_materialize_does_not_log_values(self, secret_manager, env_root, caplog):
        _write_master(env_root, "SENTINEL=xyz123\n", mode=0o600)
        app = _app_entry("myapp", ["SENTINEL"])
        with caplog.at_level(logging.DEBUG, logger="latarnia.secret_manager"):
            secret_manager.materialize(app)
        assert all("xyz123" not in rec.message for rec in caplog.records)


class TestGetFilteredEnv:

    def test_returns_filtered_dict(self, secret_manager, env_root):
        _write_master(env_root, "A=1\nB=2\nC=3\n", mode=0o600)
        app = _app_entry("myapp", ["A", "C"])
        result, env = secret_manager.get_filtered_env(app)
        assert result.ok is True
        assert env == {"A": "1", "C": "3"}

    def test_validation_failure_returns_empty_env(self, secret_manager, env_root):
        _write_master(env_root, "A=1\n", mode=0o600)
        app = _app_entry("myapp", ["A", "B"])
        result, env = secret_manager.get_filtered_env(app)
        assert result.ok is False
        assert env == {}


# ---------------------------------------------------------------------------
# cap-006: list_secrets() — never returns values
# ---------------------------------------------------------------------------

class TestListSecrets:

    def test_returns_metadata_with_no_values(self, secret_manager, env_root, mock_app_manager):
        _write_master(env_root, "A=1\nB=2\n", mode=0o600)
        # Two registered apps, one declares both secrets, one declares only A.
        mock_app_manager.registry.get_all_apps.return_value = [
            _app_entry("alpha", ["A", "B"]),
            _app_entry("beta", ["A"]),
        ]

        listed = secret_manager.list_secrets()

        assert {m.name for m in listed} == {"A", "B"}
        # Sorted by name
        assert [m.name for m in listed] == ["A", "B"]
        # Used-by sets correct
        a = next(m for m in listed if m.name == "A")
        b = next(m for m in listed if m.name == "B")
        assert sorted(a.used_by) == ["alpha", "beta"]
        assert b.used_by == ["alpha"]
        # set_at is a real datetime
        assert isinstance(a.set_at, datetime)
        # Metadata serialization has no `value` field.
        d = a.to_dict()
        assert "value" not in d
        assert set(d.keys()) == {"name", "set_at", "used_by"}
        # And no value of '1' or '2' anywhere in the serialized form
        as_text = repr([m.to_dict() for m in listed])
        assert "'1'" not in as_text and "'2'" not in as_text

    def test_empty_when_no_master_file(self, secret_manager):
        assert secret_manager.list_secrets() == []

    def test_unused_secret_has_empty_used_by(self, secret_manager, env_root, mock_app_manager):
        _write_master(env_root, "ORPHAN=v\n", mode=0o600)
        mock_app_manager.registry.get_all_apps.return_value = []
        [meta] = secret_manager.list_secrets()
        assert meta.used_by == []


# ---------------------------------------------------------------------------
# cap-007: end-to-end logging-hygiene gate (sentinel)
# ---------------------------------------------------------------------------

class TestLoggingHygiene:

    def test_no_secret_value_in_any_log_during_full_flow(
        self, secret_manager, env_root, caplog,
    ):
        SENTINEL = "sentinel-value-xyz123"
        _write_master(env_root, f"SENTINEL_KEY={SENTINEL}\n", mode=0o600)
        app = _app_entry("myapp", ["SENTINEL_KEY"])

        with caplog.at_level(logging.DEBUG, logger="latarnia.secret_manager"):
            secret_manager.load()
            secret_manager.validate(app)
            secret_manager.materialize(app)
            secret_manager.get_filtered_env(app)
            secret_manager.list_secrets()

        for rec in caplog.records:
            # Check both formatted message and raw args for leakage.
            assert SENTINEL not in rec.message
            assert SENTINEL not in str(rec.args)

    def test_validation_failure_logs_key_not_value(
        self, secret_manager, env_root, caplog,
    ):
        SENTINEL = "sentinel-xyz999"
        # A is set; B is missing. The detail names B (a key, not a value).
        _write_master(env_root, f"A={SENTINEL}\n", mode=0o600)
        app = _app_entry("myapp", ["A", "B"])
        with caplog.at_level(logging.DEBUG, logger="latarnia.secret_manager"):
            result = secret_manager.validate(app)
        assert "B" in result.detail
        for rec in caplog.records:
            assert SENTINEL not in rec.message
