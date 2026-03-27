"""
Unit tests for DbProvisioner — mocks PgClient.
"""
import pytest
from unittest.mock import Mock, patch, MagicMock
from pathlib import Path
import sys
import json

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "src"))

from latarnia.core.config import ConfigManager, PostgresConfig, LatarniaConfig
from latarnia.core.pg_client import PgClient
from latarnia.managers.db_provisioner import DbProvisioner, ProvisioningResult


@pytest.fixture
def mock_config_manager():
    mock_pg = PostgresConfig(
        host="localhost", port=5432,
        database_prefix="latarnia_", role_prefix="latarnia_",
    )
    mock_config = Mock()
    mock_config.postgres = mock_pg
    cm = Mock(spec=ConfigManager)
    cm.config = mock_config
    return cm


@pytest.fixture
def mock_pg_client():
    client = Mock(spec=PgClient)
    client.role_exists.return_value = False
    client.database_exists.return_value = False
    client.query_on_db.return_value = []  # no applied migrations
    # Mock the transaction context manager
    mock_conn = MagicMock()
    client.transaction.return_value.__enter__ = Mock(return_value=mock_conn)
    client.transaction.return_value.__exit__ = Mock(return_value=False)
    return client


@pytest.fixture
def provisioner(mock_config_manager, mock_pg_client):
    return DbProvisioner(mock_config_manager, mock_pg_client)


class TestGenerateNames:

    def test_generate_names_simple(self, provisioner):
        db, role = provisioner._generate_names("crm")
        assert db == "latarnia_crm"
        assert role == "latarnia_crm_role"

    def test_generate_names_with_hyphens(self, provisioner):
        db, role = provisioner._generate_names("my-app")
        assert db == "latarnia_my_app"
        assert role == "latarnia_my_app_role"


class TestProvisionDatabase:

    def test_provision_new_database_no_migrations(self, provisioner, mock_pg_client, tmp_path):
        result = provisioner.provision_database("crm", tmp_path)

        assert result.success is True
        assert result.database_name == "latarnia_crm"
        assert result.role_name == "latarnia_crm_role"
        assert "postgresql://" in result.connection_url
        mock_pg_client.create_role.assert_called_once()
        mock_pg_client.create_database.assert_called_once()
        mock_pg_client.revoke_public_connect.assert_called_once()
        mock_pg_client.grant_connect.assert_called_once()

    def test_provision_existing_role_updates_password(self, provisioner, mock_pg_client, tmp_path):
        mock_pg_client.role_exists.return_value = True
        result = provisioner.provision_database("crm", tmp_path)

        assert result.success is True
        mock_pg_client.create_role.assert_not_called()
        mock_pg_client.alter_role_password.assert_called_once()

    def test_provision_existing_database_reused(self, provisioner, mock_pg_client, tmp_path):
        mock_pg_client.database_exists.return_value = True
        result = provisioner.provision_database("crm", tmp_path)

        assert result.success is True
        mock_pg_client.create_database.assert_not_called()
        mock_pg_client.revoke_public_connect.assert_not_called()

    def test_provision_with_migrations(self, provisioner, mock_pg_client, tmp_path):
        # Create migration files
        mig_dir = tmp_path / "migrations"
        mig_dir.mkdir()
        (mig_dir / "001_initial.sql").write_text("CREATE TABLE foo (id INT);")
        (mig_dir / "002_add_bar.sql").write_text("ALTER TABLE foo ADD bar TEXT;")

        result = provisioner.provision_database("crm", tmp_path)

        assert result.success is True
        assert result.applied_migrations == ["001_initial.sql", "002_add_bar.sql"]
        mock_pg_client.transaction.assert_called()

    def test_provision_migration_failure_cleans_up(self, provisioner, mock_pg_client, tmp_path):
        mig_dir = tmp_path / "migrations"
        mig_dir.mkdir()
        (mig_dir / "001_bad.sql").write_text("INVALID SQL;")
        # Make the transaction's conn.execute raise an error
        mock_conn = MagicMock()
        mock_conn.execute.side_effect = Exception("syntax error")
        mock_pg_client.transaction.return_value.__enter__ = Mock(return_value=mock_conn)
        mock_pg_client.transaction.return_value.__exit__ = Mock(return_value=False)

        result = provisioner.provision_database("crm", tmp_path)

        assert result.success is False
        assert "syntax error" in result.error_message
        # Should clean up since DB was new
        mock_pg_client.drop_database.assert_called_once()
        mock_pg_client.drop_role.assert_called_once()


class TestMigrationRunner:

    def test_list_migration_files_sorted(self, provisioner, tmp_path):
        mig_dir = tmp_path / "migrations"
        mig_dir.mkdir()
        (mig_dir / "003_third.sql").write_text("-- third")
        (mig_dir / "001_first.sql").write_text("-- first")
        (mig_dir / "002_second.sql").write_text("-- second")

        files = provisioner._list_migration_files(tmp_path)
        assert [f.name for f in files] == [
            "001_first.sql", "002_second.sql", "003_third.sql"
        ]

    def test_list_migration_files_no_dir(self, provisioner, tmp_path):
        files = provisioner._list_migration_files(tmp_path)
        assert files == []


class TestVersionBumpMigrations:

    def test_version_bump_runs_pending_only(self, provisioner, mock_pg_client, tmp_path):
        mig_dir = tmp_path / "migrations"
        mig_dir.mkdir()
        (mig_dir / "001_initial.sql").write_text("CREATE TABLE foo (id INT);")
        (mig_dir / "002_new.sql").write_text("ALTER TABLE foo ADD bar TEXT;")

        # 001 already applied
        mock_pg_client.query_on_db.return_value = [
            {"migration_file": "001_initial.sql"}
        ]

        success, applied, error = provisioner.run_version_bump_migrations(
            "latarnia_crm", tmp_path
        )

        assert success is True
        assert applied == ["002_new.sql"]
        mock_pg_client.transaction.assert_called()

    def test_version_bump_no_pending(self, provisioner, mock_pg_client, tmp_path):
        mig_dir = tmp_path / "migrations"
        mig_dir.mkdir()
        (mig_dir / "001_initial.sql").write_text("CREATE TABLE foo (id INT);")
        mock_pg_client.query_on_db.return_value = [
            {"migration_file": "001_initial.sql"}
        ]

        success, applied, error = provisioner.run_version_bump_migrations(
            "latarnia_crm", tmp_path
        )

        assert success is True
        assert applied == []
        mock_pg_client.transaction.assert_not_called()

    def test_version_bump_failure_no_cleanup(self, provisioner, mock_pg_client, tmp_path):
        mig_dir = tmp_path / "migrations"
        mig_dir.mkdir()
        (mig_dir / "001_initial.sql").write_text("ok")
        (mig_dir / "002_bad.sql").write_text("INVALID")
        mock_pg_client.query_on_db.return_value = [
            {"migration_file": "001_initial.sql"}
        ]
        # Make the transaction's conn.execute raise on the second migration
        mock_conn = MagicMock()
        mock_conn.execute.side_effect = [None, Exception("syntax error")]
        mock_pg_client.transaction.return_value.__enter__ = Mock(return_value=mock_conn)
        mock_pg_client.transaction.return_value.__exit__ = Mock(return_value=False)

        success, applied, error = provisioner.run_version_bump_migrations(
            "latarnia_crm", tmp_path
        )

        assert success is False
        assert "syntax error" in error
        # Should NOT drop database on version bump failure
        mock_pg_client.drop_database.assert_not_called()
        mock_pg_client.drop_role.assert_not_called()
