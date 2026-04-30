"""
Secret Manager for Latarnia (P-0006).

Owns the per-environment master secrets file and the per-app filtered files
referenced by systemd `EnvironmentFile=` directives. Apps declare names in
`config.requires_secrets`; the platform refuses to start an app whose
declared secrets aren't all present in the master file.

Master file:    /opt/latarnia/{env}/secrets.env       (operator-edited, mode 600)
Per-app dir:    /opt/latarnia/{env}/secrets/          (platform-managed, mode 700)
Per-app file:   /opt/latarnia/{env}/secrets/{app_id}.env  (platform-written, mode 600)

Logging contract: NO method on this class ever logs a secret value. Only
key names, paths, and counts may appear in log output.
"""
from __future__ import annotations

import logging
import os
import stat
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from ..core.config import ConfigManager
from .app_manager import AppManager


@dataclass
class ValidationResult:
    """Outcome of `SecretManager.validate(app)`."""
    ok: bool
    missing: List[str] = field(default_factory=list)
    detail: str = ""


@dataclass
class SecretMetadata:
    """One entry in `GET /api/secrets`. Never carries the value itself."""
    name: str
    set_at: Optional[datetime]
    used_by: List[str]

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "set_at": self.set_at.isoformat() if self.set_at else None,
            "used_by": list(self.used_by),
        }


class SecretManager:
    """Manage the per-env master + per-app filtered secrets files."""

    def __init__(self, config_manager: ConfigManager, app_manager: AppManager,
                 env: Optional[str] = None) -> None:
        self.config_manager = config_manager
        self.app_manager = app_manager
        # Env mirrors ServiceManager's resolution so TST/PRD never collide.
        if env is None:
            env = os.environ.get("ENV", "dev").lower()
            if env not in ("dev", "tst", "prd"):
                env = "dev"
        self.env = env
        self.logger = logging.getLogger("latarnia.secret_manager")

        # Env-root = parent of the data dir. Both `/opt/latarnia/{env}/data`
        # and the local `data` relative path resolve correctly here.
        env_root = Path(self.config_manager.get_data_dir()).parent
        self.master_file_path = env_root / "secrets.env"
        self.per_app_dir = env_root / "secrets"

    # ------------------------------------------------------------------
    # Loading + parsing
    # ------------------------------------------------------------------

    def load(self) -> Dict[str, str]:
        """Read the master file and return its parsed key/value pairs.

        Returns an empty dict (no warning) if the file doesn't exist —
        valid state for an env with no secrets configured. Returns an
        empty dict (with WARNING) if the file's mode is wider than 600.
        """
        if not self.master_file_path.exists():
            return {}

        if not self._mode_is_strict(self.master_file_path, max_other=0o077):
            mode = oct(self.master_file_path.stat().st_mode & 0o777)
            self.logger.warning(
                "Refusing to read master secrets file %s: mode %s is too "
                "permissive (require 600 or stricter). Run: chmod 600 %s",
                self.master_file_path, mode, self.master_file_path,
            )
            return {}

        try:
            text = self.master_file_path.read_text()
        except OSError as e:
            self.logger.error(
                "Failed to read master secrets file %s: %s",
                self.master_file_path, type(e).__name__,
            )
            return {}

        try:
            parsed = self._parse_dotenv(text)
        except ValueError as e:
            # _parse_dotenv may raise on malformed lines. Never log values
            # — log only the line number / parse error class.
            self.logger.error(
                "Failed to parse master secrets file %s: %s",
                self.master_file_path, e,
            )
            return {}

        self.logger.info(
            "Loaded %d secret key(s) from %s",
            len(parsed), self.master_file_path,
        )
        return parsed

    @staticmethod
    def _parse_dotenv(text: str) -> Dict[str, str]:
        """Parse a single-line dotenv file.

        Format:
          - `KEY=value` per line
          - `# comment` lines and blank lines tolerated
          - Single-quoted values keep their content literally:
            `KEY='value with $ and = signs'`
          - Lines with no `=` or empty key raise ValueError (caller logs
            and treats the file as unusable).
        """
        result: Dict[str, str] = {}
        for lineno, raw in enumerate(text.splitlines(), start=1):
            line = raw.strip()
            if not line or line.startswith("#"):
                continue
            if "=" not in line:
                raise ValueError(f"line {lineno}: missing '='")
            key, _, value = line.partition("=")
            key = key.strip()
            if not key:
                raise ValueError(f"line {lineno}: empty key")
            value = value.strip()
            if len(value) >= 2 and value.startswith("'") and value.endswith("'"):
                value = value[1:-1]
            result[key] = value
        return result

    @staticmethod
    def _mode_is_strict(path: Path, max_other: int = 0o077) -> bool:
        """True if no bits set in `max_other` are present on `path`."""
        try:
            mode = path.stat().st_mode & 0o777
        except OSError:
            return False
        return (mode & max_other) == 0

    # ------------------------------------------------------------------
    # Validation + materialization
    # ------------------------------------------------------------------

    def validate(self, app_entry) -> ValidationResult:
        """Check that every declared secret is present in the master file."""
        declared = list(getattr(app_entry.manifest.config, "requires_secrets", []) or [])
        if not declared:
            return ValidationResult(ok=True)

        master = self.load()
        missing = [k for k in declared if k not in master]
        if missing:
            return ValidationResult(
                ok=False,
                missing=missing,
                detail=f"missing required secret: {missing[0]}",
            )
        return ValidationResult(ok=True)

    def materialize(self, app_entry) -> Tuple[ValidationResult, Optional[Path]]:
        """Validate and (if ok) write the per-app filtered file.

        Returns (result, path-or-None). Path is None when validation fails
        OR when the app declares no secrets (no file needed).
        """
        result = self.validate(app_entry)
        if not result.ok:
            return result, None

        declared = list(app_entry.manifest.config.requires_secrets or [])
        if not declared:
            return result, None

        master = self.load()
        filtered = {k: master[k] for k in declared}

        self.per_app_dir.mkdir(mode=0o700, exist_ok=True)
        # Tighten directory mode if it pre-existed with looser perms.
        try:
            os.chmod(self.per_app_dir, 0o700)
        except OSError:
            pass

        target = self.per_app_dir / f"{app_entry.app_id}.env"
        # Atomic create-with-mode-600. Open with O_TRUNC to overwrite cleanly.
        # Catch only OSError so the matching narrow `except OSError` in the
        # caller's release-ports path stays correct. Anything else (which
        # would indicate a programming bug here, not an I/O failure) bubbles
        # up to the caller's outer exception handler.
        flags = os.O_WRONLY | os.O_CREAT | os.O_TRUNC
        fd = os.open(str(target), flags, 0o600)
        try:
            with os.fdopen(fd, "w") as f:
                for key in declared:
                    f.write(f"{key}={filtered[key]}\n")
        except OSError:
            try:
                target.unlink(missing_ok=True)
            except OSError:
                pass
            raise
        # Belt-and-braces: ensure mode in case the file pre-existed.
        try:
            os.chmod(target, 0o600)
        except OSError:
            pass

        self.logger.info(
            "Wrote %d secret(s) for %s to %s",
            len(declared), app_entry.app_id, target,
        )
        return result, target

    def get_filtered_env(self, app_entry) -> Tuple[ValidationResult, Dict[str, str]]:
        """In-memory equivalent of materialize() for the Darwin path.

        SubprocessLauncher merges the returned dict into Popen `env=` —
        no file is written.
        """
        result = self.validate(app_entry)
        if not result.ok:
            return result, {}
        declared = list(app_entry.manifest.config.requires_secrets or [])
        if not declared:
            return result, {}
        master = self.load()
        return result, {k: master[k] for k in declared}

    # ------------------------------------------------------------------
    # Listing (cap-006)
    # ------------------------------------------------------------------

    def per_app_path(self, app_id: str) -> Path:
        """Path where `materialize` would write the per-app file for `app_id`."""
        return self.per_app_dir / f"{app_id}.env"

    def list_secrets(self) -> List[SecretMetadata]:
        """Return metadata for every secret in the master file (no values)."""
        master = self.load()
        if not master:
            return []
        try:
            mtime = self.master_file_path.stat().st_mtime
            set_at: Optional[datetime] = datetime.fromtimestamp(mtime, tz=timezone.utc)
        except OSError:
            set_at = None

        # Build the consumer list once: name -> [app_id, ...]
        consumers: Dict[str, List[str]] = {name: [] for name in master}
        for app in self.app_manager.registry.get_all_apps():
            declared = getattr(app.manifest.config, "requires_secrets", []) or []
            for name in declared:
                if name in consumers:
                    consumers[name].append(app.app_id)

        return [
            SecretMetadata(name=name, set_at=set_at, used_by=consumers[name])
            for name in sorted(master.keys())
        ]
