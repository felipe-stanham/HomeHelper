"""
Unit tests for PgClient — mocks psycopg connections.
"""
import pytest
from unittest.mock import Mock, patch, MagicMock
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "src"))

from latarnia.core.config import ConfigManager
from latarnia.core.pg_client import PgClient


@pytest.fixture
def mock_config_manager():
    cm = Mock(spec=ConfigManager)
    cm.get_postgres_dsn.return_value = "postgresql://@localhost:5432/postgres"
    return cm


@pytest.fixture
def pg_client(mock_config_manager):
    return PgClient(mock_config_manager)


class TestPgClientConnectivity:

    @patch("latarnia.core.pg_client.psycopg.connect")
    def test_check_connectivity_success(self, mock_connect, pg_client):
        mock_conn = MagicMock()
        mock_connect.return_value.__enter__ = Mock(return_value=mock_conn)
        mock_connect.return_value.__exit__ = Mock(return_value=False)
        assert pg_client.check_connectivity() is True

    @patch("latarnia.core.pg_client.psycopg.connect")
    def test_check_connectivity_failure(self, mock_connect, pg_client):
        mock_connect.side_effect = Exception("Connection refused")
        assert pg_client.check_connectivity() is False


class TestPgClientRoles:

    @patch("latarnia.core.pg_client.psycopg.connect")
    def test_role_exists_true(self, mock_connect, pg_client):
        mock_conn = MagicMock()
        mock_connect.return_value.__enter__ = Mock(return_value=mock_conn)
        mock_connect.return_value.__exit__ = Mock(return_value=False)
        mock_conn.execute.return_value.fetchone.return_value = {"?column?": 1}
        assert pg_client.role_exists("test_role") is True

    @patch("latarnia.core.pg_client.psycopg.connect")
    def test_role_exists_false(self, mock_connect, pg_client):
        mock_conn = MagicMock()
        mock_connect.return_value.__enter__ = Mock(return_value=mock_conn)
        mock_connect.return_value.__exit__ = Mock(return_value=False)
        mock_conn.execute.return_value.fetchone.return_value = None
        assert pg_client.role_exists("nonexistent") is False

    @patch("latarnia.core.pg_client.psycopg.connect")
    def test_create_role(self, mock_connect, pg_client):
        mock_conn = MagicMock()
        mock_connect.return_value.__enter__ = Mock(return_value=mock_conn)
        mock_connect.return_value.__exit__ = Mock(return_value=False)
        pg_client.create_role("test_role", "secret123")
        mock_conn.execute.assert_called_once()


class TestPgClientDatabases:

    @patch("latarnia.core.pg_client.psycopg.connect")
    def test_database_exists_true(self, mock_connect, pg_client):
        mock_conn = MagicMock()
        mock_connect.return_value.__enter__ = Mock(return_value=mock_conn)
        mock_connect.return_value.__exit__ = Mock(return_value=False)
        mock_conn.execute.return_value.fetchone.return_value = {"?column?": 1}
        assert pg_client.database_exists("test_db") is True

    @patch("latarnia.core.pg_client.psycopg.connect")
    def test_database_exists_false(self, mock_connect, pg_client):
        mock_conn = MagicMock()
        mock_connect.return_value.__enter__ = Mock(return_value=mock_conn)
        mock_connect.return_value.__exit__ = Mock(return_value=False)
        mock_conn.execute.return_value.fetchone.return_value = None
        assert pg_client.database_exists("nonexistent") is False

    @patch("latarnia.core.pg_client.psycopg.connect")
    def test_create_database(self, mock_connect, pg_client):
        mock_conn = MagicMock()
        mock_connect.return_value.__enter__ = Mock(return_value=mock_conn)
        mock_connect.return_value.__exit__ = Mock(return_value=False)
        pg_client.create_database("test_db", "test_role")
        mock_conn.execute.assert_called_once()

    @patch("latarnia.core.pg_client.psycopg.connect")
    def test_drop_database(self, mock_connect, pg_client):
        mock_conn = MagicMock()
        mock_connect.return_value.__enter__ = Mock(return_value=mock_conn)
        mock_connect.return_value.__exit__ = Mock(return_value=False)
        pg_client.drop_database("test_db")
        assert mock_conn.execute.call_count == 2  # terminate + drop

    @patch("latarnia.core.pg_client.psycopg.connect")
    def test_drop_role(self, mock_connect, pg_client):
        mock_conn = MagicMock()
        mock_connect.return_value.__enter__ = Mock(return_value=mock_conn)
        mock_connect.return_value.__exit__ = Mock(return_value=False)
        pg_client.drop_role("test_role")
        mock_conn.execute.assert_called_once()
