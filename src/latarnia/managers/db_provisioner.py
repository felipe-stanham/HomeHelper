"""
Database provisioner for Latarnia platform.

Handles per-app database creation, role management, and migration execution.
"""
import hashlib
import logging
import secrets
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional, Tuple

from ..core.config import ConfigManager
from ..core.pg_client import PgClient


SCHEMA_VERSIONS_DDL = """
CREATE TABLE IF NOT EXISTS schema_versions (
    id SERIAL PRIMARY KEY,
    migration_file TEXT NOT NULL,
    migration_number INTEGER NOT NULL,
    checksum TEXT NOT NULL,
    applied_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    duration_ms INTEGER NOT NULL
)
"""


@dataclass
class ProvisioningResult:
    """Result of a database provisioning operation."""
    success: bool
    database_name: Optional[str] = None
    role_name: Optional[str] = None
    connection_url: Optional[str] = None
    applied_migrations: List[str] = field(default_factory=list)
    error_message: Optional[str] = None


class DbProvisioner:
    """Manages per-app database provisioning and migrations."""

    def __init__(self, config_manager: ConfigManager, pg_client: PgClient):
        self.config_manager = config_manager
        self.pg_client = pg_client
        self.logger = logging.getLogger("latarnia.db_provisioner")

    def provision_database(self, app_name: str, app_path: Path) -> ProvisioningResult:
        """Full provisioning workflow for an app with database: true.

        Creates role + database if they don't exist, runs pending migrations,
        and returns a connection URL for the app.
        """
        db_name, role_name = self._generate_names(app_name)
        password = secrets.token_urlsafe(32)

        try:
            # Create or update role
            if self.pg_client.role_exists(role_name):
                self.pg_client.alter_role_password(role_name, password)
                self.logger.info(f"Role {role_name} already exists, password updated")
            else:
                self.pg_client.create_role(role_name, password)

            # Create database if needed
            db_is_new = False
            if not self.pg_client.database_exists(db_name):
                self.pg_client.create_database(db_name, role_name)
                self.pg_client.revoke_public_connect(db_name)
                self.pg_client.grant_connect(db_name, role_name)
                db_is_new = True
                self.logger.info(f"Provisioned new database: {db_name}")
            else:
                self.logger.info(f"Database {db_name} already exists, reusing")

            # Create schema_versions table
            self.pg_client.execute_on_db(db_name, SCHEMA_VERSIONS_DDL)

            # Run migrations
            applied = []
            migration_files = self._list_migration_files(app_path)
            if migration_files:
                already_applied = self._get_applied_migrations(db_name)
                pending = [f for f in migration_files if f.name not in already_applied]

                if pending:
                    success, applied, error = self._run_migrations(db_name, pending)
                    if not success:
                        if db_is_new:
                            # Clean slate on initial provision failure
                            self._cleanup(db_name, role_name)
                        return ProvisioningResult(
                            success=False, error_message=error
                        )

            # Build connection URL
            pg = self.config_manager.config.postgres
            connection_url = (
                f"postgresql://{role_name}:{password}"
                f"@{pg.host}:{pg.port}/{db_name}"
            )

            return ProvisioningResult(
                success=True,
                database_name=db_name,
                role_name=role_name,
                connection_url=connection_url,
                applied_migrations=applied,
            )

        except Exception as e:
            self.logger.error(f"Provisioning failed for {app_name}: {e}")
            return ProvisioningResult(success=False, error_message=str(e))

    def run_version_bump_migrations(
        self, db_name: str, app_path: Path
    ) -> Tuple[bool, List[str], Optional[str]]:
        """Run only pending migrations for a version bump.

        Unlike initial provisioning, does NOT drop the database on failure.
        Returns: (success, newly_applied_file_names, error_message)
        """
        migration_files = self._list_migration_files(app_path)
        if not migration_files:
            return True, [], None

        already_applied = self._get_applied_migrations(db_name)
        pending = [f for f in migration_files if f.name not in already_applied]

        if not pending:
            self.logger.info(f"No pending migrations for {db_name}")
            return True, [], None

        return self._run_migrations(db_name, pending)

    def _generate_names(self, app_name: str) -> Tuple[str, str]:
        """Generate database name and role name from app name."""
        pg = self.config_manager.config.postgres
        clean_name = app_name.replace("-", "_").lower()
        db_name = f"{pg.database_prefix}{clean_name}"
        role_name = f"{pg.role_prefix}{clean_name}_role"
        return db_name, role_name

    def _list_migration_files(self, app_path: Path) -> List[Path]:
        """List migration files sorted by numeric prefix."""
        migrations_dir = app_path / "migrations"
        if not migrations_dir.exists():
            return []
        files = list(migrations_dir.glob("*.sql"))
        files.sort(key=lambda f: int(f.name.split("_")[0]))
        return files

    def _get_applied_migrations(self, db_name: str) -> set:
        """Get set of already-applied migration file names."""
        try:
            rows = self.pg_client.query_on_db(
                db_name, "SELECT migration_file FROM schema_versions"
            )
            return {r["migration_file"] for r in rows}
        except Exception:
            return set()

    def _run_migrations(
        self, db_name: str, pending_files: List[Path]
    ) -> Tuple[bool, List[str], Optional[str]]:
        """Execute pending migration files in a single transaction.

        Returns: (success, applied_file_names, error_message)
        """
        applied = []
        try:
            with self.pg_client.transaction(db_name) as conn:
                try:
                    for mig_file in pending_files:
                        sql_content = mig_file.read_text()
                        checksum = hashlib.sha256(sql_content.encode()).hexdigest()
                        migration_number = int(mig_file.name.split("_")[0])

                        start_time = time.monotonic()
                        conn.execute(sql_content)
                        duration_ms = int((time.monotonic() - start_time) * 1000)

                        conn.execute(
                            "INSERT INTO schema_versions "
                            "(migration_file, migration_number, checksum, duration_ms) "
                            "VALUES (%s, %s, %s, %s)",
                            (mig_file.name, migration_number, checksum, duration_ms),
                        )
                        applied.append(mig_file.name)
                    conn.commit()
                except Exception:
                    conn.rollback()
                    raise

            self.logger.info(
                f"Applied {len(pending_files)} migration(s) to {db_name}: "
                + ", ".join(applied)
            )
            return True, applied, None
        except Exception as e:
            error_msg = f"Migration failed on {db_name}: {e}"
            self.logger.error(error_msg)
            return False, [], error_msg

    def _cleanup(self, db_name: str, role_name: str) -> None:
        """Drop database and role on initial provisioning failure."""
        try:
            self.pg_client.drop_database(db_name)
            self.pg_client.drop_role(role_name)
            self.logger.info(f"Cleaned up failed provisioning: {db_name}, {role_name}")
        except Exception as e:
            self.logger.error(f"Cleanup failed for {db_name}/{role_name}: {e}")
