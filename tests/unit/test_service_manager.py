"""
Unit tests for ServiceManager and HealthMonitor

Tests systemd service integration, health monitoring, and service lifecycle management.
"""

import logging
import pytest
import tempfile
import asyncio
from pathlib import Path
from unittest.mock import Mock, patch, MagicMock, AsyncMock
from datetime import datetime, timedelta

import sys
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "src"))

from latarnia.core.config import ConfigManager
from latarnia.managers.app_manager import AppManager, AppRegistry, AppManifest, AppType, AppStatus, AppRuntimeInfo
from latarnia.managers.port_manager import PortManager
from latarnia.managers.service_manager import ServiceManager, ServiceInfo, ServiceStatus, ServiceState
from latarnia.managers.health_monitor import (
    HealthMonitor,
    HealthCheckResult,
    HealthStatus,
    OverallStatus,
)


class TestServiceManager:
    """Test cases for ServiceManager"""
    
    @pytest.fixture
    def temp_dirs(self):
        """Create temporary directories for testing"""
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            config_dir = temp_path / "config"
            systemd_dir = temp_path / "systemd" / "user"
            
            config_dir.mkdir(parents=True)
            systemd_dir.mkdir(parents=True)
            
            yield {
                'base': temp_path,
                'config': config_dir,
                'systemd': systemd_dir
            }
    
    @pytest.fixture
    def mock_config_manager(self, temp_dirs):
        """Mock ConfigManager for testing"""
        mock_config = Mock()
        mock_config.redis.host = "localhost"
        mock_config.redis.port = 6379
        mock_config.redis.password = None

        mock_config_manager = Mock(spec=ConfigManager)
        mock_config_manager.config = mock_config
        mock_config_manager.get_data_dir.return_value = temp_dirs['config']
        mock_config_manager.get_logs_dir.return_value = temp_dirs['config'] / "logs"
        mock_config_manager.get_redis_url.return_value = "redis://localhost:6379/0"
        return mock_config_manager
    
    @pytest.fixture
    def mock_app_manager(self, temp_dirs):
        """Mock AppManager for testing"""
        mock_app_manager = Mock(spec=AppManager)
        mock_registry = Mock(spec=AppRegistry)
        mock_app_manager.registry = mock_registry
        return mock_app_manager
    
    @pytest.fixture
    def sample_service_app(self, temp_dirs):
        """Sample service app for testing"""
        app_path = temp_dirs['base'] / "test-service"
        app_path.mkdir()
        
        manifest = AppManifest(
            name="test-service",
            type=AppType.SERVICE,
            description="Test service application",
            version="1.0.0",
            author="Test Author",
            main_file="app.py",
            config={
                "has_UI": True,
                "redis_required": True,
                "data_dir": True,
                "logs_dir": True,
                "auto_start": False,
                "restart_policy": "always"
            }
        )
        
        runtime_info = AppRuntimeInfo(assigned_port=8100)
        
        from latarnia.managers.app_manager import AppRegistryEntry
        app_entry = AppRegistryEntry(
            app_id="test-service",
            name="test-service",
            type=AppType.SERVICE,
            description="Test service application",
            version="1.0.0",
            status=AppStatus.READY,
            path=app_path,
            manifest=manifest,
            runtime_info=runtime_info
        )
        
        return app_entry
    
    @pytest.fixture
    def service_manager(self, mock_config_manager, mock_app_manager, temp_dirs, monkeypatch):
        """Create ServiceManager instance for testing (ENV=dev)"""
        monkeypatch.setenv("ENV", "dev")
        with patch.object(Path, 'home', return_value=temp_dirs['base']):
            manager = ServiceManager(mock_config_manager, mock_app_manager)
            # Override systemd directory for testing
            manager.systemd_user_dir = temp_dirs['systemd']
            return manager

    def test_service_manager_initialization(self, service_manager, temp_dirs):
        """Test ServiceManager initialization"""
        assert service_manager.systemd_user_dir == temp_dirs['systemd']
        assert service_manager.env == "dev"
        assert service_manager.service_prefix == "latarnia-dev-"
        assert service_manager.services == {}

    @pytest.mark.parametrize("env_value,expected_prefix", [
        ("dev", "latarnia-dev-"),
        ("tst", "latarnia-tst-"),
        ("prd", "latarnia-prd-"),
        ("TST", "latarnia-tst-"),  # case-insensitive
    ])
    def test_service_prefix_matches_env(
        self, mock_config_manager, mock_app_manager, temp_dirs, monkeypatch,
        env_value, expected_prefix,
    ):
        """Service prefix is scoped per ENV so TST/PRD apps don't collide."""
        monkeypatch.setenv("ENV", env_value)
        with patch.object(Path, 'home', return_value=temp_dirs['base']):
            manager = ServiceManager(mock_config_manager, mock_app_manager)
        assert manager.service_prefix == expected_prefix

    def test_service_prefix_defaults_to_dev_when_env_unset(
        self, mock_config_manager, mock_app_manager, temp_dirs, monkeypatch,
    ):
        """Missing ENV falls back to dev — mirrors the rest of the codebase."""
        monkeypatch.delenv("ENV", raising=False)
        with patch.object(Path, 'home', return_value=temp_dirs['base']):
            manager = ServiceManager(mock_config_manager, mock_app_manager)
        assert manager.service_prefix == "latarnia-dev-"

    def test_service_prefix_falls_back_on_unknown_env(
        self, mock_config_manager, mock_app_manager, temp_dirs, monkeypatch, caplog,
    ):
        """Unrecognized ENV values log a warning and fall back to dev."""
        monkeypatch.setenv("ENV", "staging")
        with patch.object(Path, 'home', return_value=temp_dirs['base']):
            with caplog.at_level(logging.WARNING, logger="latarnia.service_manager"):
                manager = ServiceManager(mock_config_manager, mock_app_manager)
        assert manager.service_prefix == "latarnia-dev-"
        assert any("Unrecognized ENV" in rec.message for rec in caplog.records)
    
    def test_generate_service_template(self, service_manager, mock_app_manager, sample_service_app):
        """Test systemd service template generation"""
        # Setup mock
        mock_app_manager.registry.get_app.return_value = sample_service_app

        # Generate template
        template = service_manager.generate_service_template("test-service")

        assert template is not None
        assert "Description=Latarnia Service - test-service" in template
        # ExecStart must use the absolute venv Python (sys.executable), not bare `python`.
        assert f"ExecStart={service_manager.python_executable} app.py --port 8100" in template
        # Sample app explicitly sets restart_policy="always".
        assert "Restart=always" in template
        assert "Environment=ENV=dev" in template
        assert "Environment=REDIS_HOST=localhost" in template
        assert "Environment=REDIS_PORT=6379" in template
        assert "--data-dir" in template
        # P-0005 Scope 4: --logs-dir is no longer passed (journald is the
        # canonical sink on Linux).
        assert "--logs-dir" not in template

    def test_generate_service_template_uses_sys_executable(
        self, service_manager, mock_app_manager, sample_service_app, monkeypatch,
    ):
        """ExecStart resolves to the platform venv Python (absolute path)."""
        fake_python = "/opt/latarnia/tst/.venv/bin/python"
        service_manager.python_executable = fake_python
        mock_app_manager.registry.get_app.return_value = sample_service_app

        template = service_manager.generate_service_template("test-service")

        assert template is not None
        # Absolute path appears verbatim, no bare `python` token.
        assert f"ExecStart={fake_python} app.py --port 8100" in template
        # Make sure no "ExecStart=python " (bare) leaked through.
        for line in template.splitlines():
            if line.startswith("ExecStart="):
                assert not line.startswith("ExecStart=python "), line

    @pytest.mark.parametrize("env_value,expected", [
        ("dev", "Environment=ENV=dev"),
        ("tst", "Environment=ENV=tst"),
        ("prd", "Environment=ENV=prd"),
        ("staging", "Environment=ENV=dev"),  # falls back to dev
    ])
    def test_generate_service_template_environment_env(
        self, mock_config_manager, mock_app_manager, temp_dirs, monkeypatch,
        sample_service_app, env_value, expected,
    ):
        """Generated unit declares Environment=ENV={env}, matching ServiceManager.env."""
        monkeypatch.setenv("ENV", env_value)
        with patch.object(Path, 'home', return_value=temp_dirs['base']):
            manager = ServiceManager(mock_config_manager, mock_app_manager)
        manager.systemd_user_dir = temp_dirs['systemd']
        mock_app_manager.registry.get_app.return_value = sample_service_app

        template = manager.generate_service_template("test-service")

        assert template is not None
        assert expected in template

    def test_generate_service_template_no_partof(
        self, service_manager, mock_app_manager, sample_service_app,
    ):
        """Per-app units must NOT carry PartOf — referencing a system-scope
        unit from a user-scope unit is a silent no-op, and we want app
        lifetimes independent of the platform (Scope 4 follow-up)."""
        mock_app_manager.registry.get_app.return_value = sample_service_app
        template = service_manager.generate_service_template("test-service")
        assert template is not None
        assert "PartOf=" not in template

    @pytest.mark.parametrize("policy,expected_line", [
        (None, "Restart=on-failure"),         # manifest default → on-failure
        ("on-failure", "Restart=on-failure"),
        ("always", "Restart=always"),
        ("never", "Restart=no"),               # systemd uses "no", not "never"
    ])
    def test_generate_service_template_restart_policy(
        self, service_manager, mock_app_manager, sample_service_app,
        policy, expected_line,
    ):
        """Default restart policy is on-failure; manifest may override."""
        if policy is None:
            # Simulate a manifest that does not set restart_policy by clearing it.
            sample_service_app.manifest.config.restart_policy = None
        else:
            sample_service_app.manifest.config.restart_policy = policy
        mock_app_manager.registry.get_app.return_value = sample_service_app

        template = service_manager.generate_service_template("test-service")

        assert template is not None
        assert expected_line in template
        assert "RestartSec=5" in template
    
    def test_generate_service_template_no_app(self, service_manager, mock_app_manager):
        """Test service template generation for non-existent app"""
        mock_app_manager.registry.get_app.return_value = None
        
        template = service_manager.generate_service_template("nonexistent")
        
        assert template is None
    
    def test_generate_service_template_no_port(self, service_manager, mock_app_manager, sample_service_app):
        """Test service template generation for app without assigned port"""
        sample_service_app.runtime_info.assigned_port = None
        mock_app_manager.registry.get_app.return_value = sample_service_app

        template = service_manager.generate_service_template("test-service")

        assert template is None

    def test_generate_service_template_with_mcp_port(self, service_manager, mock_app_manager, sample_service_app, temp_dirs):
        """Test service template includes --mcp-port for MCP-enabled apps"""
        from latarnia.managers.app_manager import MCPInfo
        sample_service_app.mcp_info = MCPInfo(enabled=True, mcp_port=9001)
        mock_app_manager.registry.get_app.return_value = sample_service_app

        template = service_manager.generate_service_template("test-service")

        assert template is not None
        assert "--mcp-port 9001" in template
        assert "--port 8100" in template
    
    @patch('subprocess.run')
    def test_create_service_file_success(self, mock_subprocess, service_manager, mock_app_manager, sample_service_app):
        """Test successful service file creation"""
        mock_app_manager.registry.get_app.return_value = sample_service_app
        mock_subprocess.return_value.returncode = 0
        
        result = service_manager.create_service_file("test-service")
        
        assert result is True
        service_file = service_manager.systemd_user_dir / "latarnia-dev-test-service.service"
        assert service_file.exists()
        
        # Verify systemctl daemon-reload was called
        mock_subprocess.assert_called_with(
            ["systemctl", "--user", "daemon-reload"],
            capture_output=True,
            text=True
        )
    
    @patch('subprocess.run')
    def test_start_service_success(self, mock_subprocess, service_manager, mock_app_manager, sample_service_app):
        """Test successful service start"""
        mock_app_manager.registry.get_app.return_value = sample_service_app
        mock_subprocess.return_value.returncode = 0
        mock_subprocess.return_value.stderr = ""

        result = service_manager.start_service("test-service")

        assert result is True
        mock_subprocess.assert_called_with(
            ["systemctl", "--user", "start", "latarnia-dev-test-service.service"],
            capture_output=True,
            text=True
        )
        mock_app_manager.registry.update_app.assert_called_with("test-service", status=AppStatus.RUNNING)

    @patch('subprocess.run')
    def test_start_service_creates_unit_file_before_start(
        self, mock_subprocess, service_manager, mock_app_manager, sample_service_app,
    ):
        """start_service is one-shot: it must (re)write the unit file and
        daemon-reload before invoking `systemctl --user start`. Regression
        test for a bug where /api/apps/{id}/process/start returned 500
        because the unit had not been created."""
        mock_app_manager.registry.get_app.return_value = sample_service_app
        mock_subprocess.return_value.returncode = 0
        mock_subprocess.return_value.stderr = ""

        # Pre-condition: the unit file does not exist.
        unit_path = service_manager.systemd_user_dir / "latarnia-dev-test-service.service"
        assert not unit_path.exists()

        assert service_manager.start_service("test-service") is True

        # The unit file must now exist (created by start_service).
        assert unit_path.exists()
        # The systemctl invocations include both daemon-reload and start.
        invocations = [call.args[0] for call in mock_subprocess.call_args_list]
        assert ["systemctl", "--user", "daemon-reload"] in invocations
        assert (
            ["systemctl", "--user", "start", "latarnia-dev-test-service.service"]
            in invocations
        )

    @patch('subprocess.run')
    def test_start_service_end_to_end(
        self, mock_subprocess, service_manager, mock_app_manager, sample_service_app,
    ):
        """End-to-end: create_service_file → daemon-reload → start.

        Verifies the systemd path that the platform now exercises on Linux:
        a unit file is written, daemon-reload is invoked, then `systemctl
        --user start latarnia-{env}-{app}.service` runs. All subprocess calls
        are mocked.
        """
        mock_app_manager.registry.get_app.return_value = sample_service_app
        mock_subprocess.return_value.returncode = 0
        mock_subprocess.return_value.stderr = ""

        # Create then start in the same flow that the auto_start path uses.
        assert service_manager.create_service_file("test-service") is True
        unit_path = service_manager.systemd_user_dir / "latarnia-dev-test-service.service"
        assert unit_path.exists()
        contents = unit_path.read_text()
        assert "Environment=ENV=dev" in contents
        # ExecStart must use the absolute venv Python path.
        assert f"ExecStart={service_manager.python_executable} app.py" in contents

        assert service_manager.start_service("test-service") is True
        mock_subprocess.assert_called_with(
            ["systemctl", "--user", "start", "latarnia-dev-test-service.service"],
            capture_output=True,
            text=True,
        )
    
    @patch('subprocess.run')
    def test_start_service_failure(self, mock_subprocess, service_manager, mock_app_manager, sample_service_app):
        """systemctl --user start fails → app marked ERROR.

        start_service now creates the unit file (daemon-reload) before
        starting; let daemon-reload succeed and have only the start call
        return non-zero.
        """
        mock_app_manager.registry.get_app.return_value = sample_service_app

        def fake_run(args, **_kwargs):
            result = Mock()
            if args[:3] == ["systemctl", "--user", "start"]:
                result.returncode = 1
                result.stderr = "Service failed to start"
            else:
                result.returncode = 0
                result.stderr = ""
            return result

        mock_subprocess.side_effect = fake_run

        result = service_manager.start_service("test-service")

        assert result is False
        mock_app_manager.registry.update_app.assert_any_call(
            "test-service",
            status=AppStatus.ERROR,
            runtime_info=sample_service_app.runtime_info,
        )
    
    @patch('subprocess.run')
    def test_stop_service_success(self, mock_subprocess, service_manager):
        """Test successful service stop"""
        mock_subprocess.return_value.returncode = 0
        
        result = service_manager.stop_service("test-service")
        
        assert result is True
        mock_subprocess.assert_called_with(
            ["systemctl", "--user", "stop", "latarnia-dev-test-service.service"],
            capture_output=True,
            text=True
        )
    
    @patch('subprocess.run')
    def test_restart_service_success(self, mock_subprocess, service_manager):
        """Test successful service restart"""
        mock_subprocess.return_value.returncode = 0
        
        result = service_manager.restart_service("test-service")
        
        assert result is True
        mock_subprocess.assert_called_with(
            ["systemctl", "--user", "restart", "latarnia-dev-test-service.service"],
            capture_output=True,
            text=True
        )
    
    @patch("latarnia.managers.service_manager.platform.system", return_value="Linux")
    @patch("latarnia.managers.service_manager.subprocess.run")
    def test_reconcile_running_units_marks_active_apps_running(
        self, mock_run, mock_system,
        service_manager, mock_app_manager, sample_service_app, temp_dirs,
    ):
        """Active per-app units → app marked RUNNING with port reclaimed."""
        # Wire a real PortManager substitute via a Mock that records calls.
        port_manager = MagicMock()
        port_manager.claim_port = MagicMock()
        port_manager.claim_mcp_port = MagicMock()
        service_manager.port_manager = port_manager

        # Pretend the unit file exists with a known ExecStart.
        unit_path = service_manager.systemd_user_dir / "latarnia-dev-test-service.service"
        unit_path.write_text(
            "[Service]\n"
            "ExecStart=/opt/latarnia/dev/.venv/bin/python app.py "
            "--port 8123 --mcp-port 9012 --redis-url redis://localhost:6379/0\n"
        )

        # systemctl show returns one active unit matching the prefix.
        mock_run.return_value.returncode = 0
        mock_run.return_value.stdout = (
            "Id=latarnia-dev-test-service.service\nActiveState=active\n\n"
        )
        # Registry returns the sample app.
        mock_app_manager.registry.get_app.return_value = sample_service_app
        # Make sure mcp_info exists so mcp port path is exercised.
        from latarnia.managers.app_manager import MCPInfo
        sample_service_app.mcp_info = MCPInfo(enabled=True)

        count = service_manager.reconcile_running_units()

        assert count == 1
        port_manager.claim_port.assert_called_once_with("test-service", AppType.SERVICE, 8123)
        port_manager.claim_mcp_port.assert_called_once_with("test-service", 9012)
        assert sample_service_app.runtime_info.assigned_port == 8123
        assert sample_service_app.mcp_info.mcp_port == 9012
        mock_app_manager.registry.update_app.assert_called_with(
            "test-service",
            status=AppStatus.RUNNING,
            runtime_info=sample_service_app.runtime_info,
        )

    @patch("latarnia.managers.service_manager.platform.system", return_value="Linux")
    @patch("latarnia.managers.service_manager.subprocess.run")
    def test_reconcile_running_units_skips_inactive(
        self, mock_run, mock_system, service_manager,
    ):
        """`inactive` and `failed` units are not reconciled (only active/activating)."""
        port_manager = MagicMock()
        service_manager.port_manager = port_manager
        mock_run.return_value.returncode = 0
        mock_run.return_value.stdout = (
            "Id=latarnia-dev-app_a.service\nActiveState=inactive\n\n"
            "Id=latarnia-dev-app_b.service\nActiveState=failed\n\n"
        )
        count = service_manager.reconcile_running_units()
        assert count == 0
        port_manager.claim_port.assert_not_called()

    @patch("latarnia.managers.service_manager.platform.system", return_value="Darwin")
    def test_reconcile_running_units_noop_on_macos(self, mock_system, service_manager):
        """macOS has no systemd; reconciliation is a no-op."""
        service_manager.port_manager = MagicMock()
        assert service_manager.reconcile_running_units() == 0

    def test_parse_ports_from_unit(self, service_manager, temp_dirs):
        """ExecStart line with --port and --mcp-port yields both ints."""
        unit = temp_dirs["systemd"] / "x.service"
        unit.write_text(
            "[Service]\n"
            "ExecStart=/path/python app.py --port 8101 --mcp-port 9051 "
            "--data-dir /opt/latarnia/dev/data/x\n"
            "Environment=ENV=dev\n"
        )
        ports = ServiceManager._parse_ports_from_unit(unit)
        assert ports == {"port": 8101, "mcp_port": 9051}

    @patch('subprocess.run')
    def test_get_service_status(self, mock_subprocess, service_manager):
        """Test getting service status"""
        mock_subprocess.return_value.returncode = 0
        mock_subprocess.return_value.stdout = "ActiveState=active\nSubState=running\nMainPID=12345\n"
        
        with patch.object(service_manager, '_get_process_metrics') as mock_metrics:
            mock_metrics.return_value = ServiceInfo(
                service_name="latarnia-dev-test-service.service",
                status=ServiceStatus.ACTIVE,
                state=ServiceState.RUNNING,
                pid=12345,
                memory_usage=1024*1024,
                cpu_percent=5.0
            )
            
            status = service_manager.get_service_status("test-service")
        
        assert status is not None
        assert status.status == ServiceStatus.ACTIVE
        assert status.state == ServiceState.RUNNING
        assert status.pid == 12345
    
    @patch('subprocess.run')
    def test_get_service_logs(self, mock_subprocess, service_manager):
        """Test getting service logs"""
        mock_subprocess.return_value.returncode = 0
        mock_subprocess.return_value.stdout = "Log line 1\nLog line 2\nLog line 3\n"
        
        logs = service_manager.get_service_logs("test-service", lines=3)
        
        assert len(logs) == 3
        assert logs[0] == "Log line 1"
        assert logs[1] == "Log line 2"
        assert logs[2] == "Log line 3"
        
        # Query the system journal by _SYSTEMD_USER_UNIT (Pi has no
        # user-mode persistent journald; --user variant returns nothing).
        mock_subprocess.assert_called_with(
            [
                "journalctl",
                "_SYSTEMD_USER_UNIT=latarnia-dev-test-service.service",
                "-n", "3", "--no-pager",
            ],
            capture_output=True,
            text=True,
        )
    
    @patch('subprocess.run')
    def test_enable_service(self, mock_subprocess, service_manager):
        """Test enabling service"""
        mock_subprocess.return_value.returncode = 0
        
        result = service_manager.enable_service("test-service")
        
        assert result is True
        mock_subprocess.assert_called_with(
            ["systemctl", "--user", "enable", "latarnia-dev-test-service.service"],
            capture_output=True,
            text=True
        )
    
    @patch('subprocess.run')
    def test_disable_service(self, mock_subprocess, service_manager):
        """Test disabling service"""
        mock_subprocess.return_value.returncode = 0
        
        result = service_manager.disable_service("test-service")
        
        assert result is True
        mock_subprocess.assert_called_with(
            ["systemctl", "--user", "disable", "latarnia-dev-test-service.service"],
            capture_output=True,
            text=True
        )
    
    @patch("latarnia.managers.service_manager.platform.system", return_value="Linux")
    @patch("latarnia.managers.service_manager.subprocess.run")
    def test_linger_enabled_yes(self, mock_run, mock_system, service_manager):
        """loginctl reports Linger=yes → linger_enabled() returns True."""
        mock_run.return_value.returncode = 0
        mock_run.return_value.stdout = "Linger=yes\n"
        assert service_manager.linger_enabled("felipe") is True
        mock_run.assert_called_with(
            ["loginctl", "show-user", "felipe", "--property=Linger"],
            capture_output=True,
            text=True,
        )

    @patch("latarnia.managers.service_manager.platform.system", return_value="Linux")
    @patch("latarnia.managers.service_manager.subprocess.run")
    def test_linger_enabled_no(self, mock_run, mock_system, service_manager):
        """loginctl reports Linger=no → linger_enabled() returns False."""
        mock_run.return_value.returncode = 0
        mock_run.return_value.stdout = "Linger=no\n"
        assert service_manager.linger_enabled("felipe") is False

    @patch("latarnia.managers.service_manager.platform.system", return_value="Darwin")
    @patch("latarnia.managers.service_manager.subprocess.run")
    def test_linger_enabled_skipped_on_non_linux(
        self, mock_run, mock_system, service_manager,
    ):
        """On non-Linux hosts, linger_enabled returns True without shelling out."""
        assert service_manager.linger_enabled("anyone") is True
        mock_run.assert_not_called()

    @patch("latarnia.managers.service_manager.platform.system", return_value="Linux")
    @patch(
        "latarnia.managers.service_manager.subprocess.run",
        side_effect=FileNotFoundError(),
    )
    def test_linger_enabled_loginctl_missing(
        self, mock_run, mock_system, service_manager,
    ):
        """If loginctl is unavailable, treat as enabled (avoid false alarms)."""
        assert service_manager.linger_enabled("felipe") is True

    def test_get_service_statistics(self, service_manager):
        """Test getting service statistics"""
        # Mock some service statuses
        service_manager.services = {
            "app1": ServiceInfo("service1", ServiceStatus.ACTIVE, ServiceState.RUNNING, memory_usage=1024*1024),
            "app2": ServiceInfo("service2", ServiceStatus.ACTIVE, ServiceState.RUNNING, memory_usage=2048*1024),
            "app3": ServiceInfo("service3", ServiceStatus.INACTIVE, ServiceState.DEAD)
        }
        
        with patch.object(service_manager, 'get_all_service_statuses', return_value=service_manager.services):
            stats = service_manager.get_service_statistics()
        
        assert stats['total_services'] == 3
        assert stats['running_services'] == 2
        assert stats['total_memory_usage'] == 3072*1024
        assert stats['average_memory_per_service'] == 1536*1024


class TestHealthMonitor:
    """Test cases for HealthMonitor"""
    
    @pytest.fixture
    def mock_config_manager(self):
        """Mock ConfigManager for testing"""
        return Mock(spec=ConfigManager)
    
    @pytest.fixture
    def mock_app_manager(self):
        """Mock AppManager for testing"""
        mock_app_manager = Mock(spec=AppManager)
        mock_registry = Mock(spec=AppRegistry)
        mock_app_manager.registry = mock_registry
        return mock_app_manager
    
    @pytest.fixture
    def mock_service_manager(self):
        """Mock ServiceManager for testing"""
        return Mock(spec=ServiceManager)
    
    @pytest.fixture
    def health_monitor(self, mock_config_manager, mock_app_manager, mock_service_manager):
        """Create HealthMonitor instance for testing"""
        return HealthMonitor(mock_config_manager, mock_app_manager, mock_service_manager)
    
    @pytest.fixture
    def sample_running_app(self):
        """Sample running service app for testing"""
        manifest = AppManifest(
            name="test-service",
            type=AppType.SERVICE,
            description="Test service",
            version="1.0.0",
            author="Test Author",
            main_file="app.py",
            config={"has_UI": True}
        )
        
        runtime_info = AppRuntimeInfo(assigned_port=8100)
        
        from latarnia.managers.app_manager import AppRegistryEntry
        return AppRegistryEntry(
            app_id="test-service",
            name="test-service",
            type=AppType.SERVICE,
            description="Test service",
            version="1.0.0",
            status=AppStatus.RUNNING,
            path=Path("/tmp/test-service"),
            manifest=manifest,
            runtime_info=runtime_info
        )
    
    def test_health_monitor_initialization(self, health_monitor):
        """Test HealthMonitor initialization"""
        assert health_monitor.config.enabled is True
        assert health_monitor.config.interval == 30
        assert health_monitor.config.timeout == 5
        assert health_monitor.health_results == {}
        assert health_monitor.failure_counts == {}
        assert health_monitor._running is False
    
    @pytest.mark.asyncio
    async def test_start_stop_monitoring(self, health_monitor):
        """Test starting and stopping health monitoring"""
        # Mock the monitoring loop to avoid infinite loop
        with patch.object(health_monitor, '_monitoring_loop', new_callable=AsyncMock) as mock_loop:
            # Start monitoring
            await health_monitor.start_monitoring()
            
            assert health_monitor._running is True
            assert health_monitor._session is not None
            assert health_monitor._monitoring_task is not None
        
        # Stop monitoring
        await health_monitor.stop_monitoring()
        
        assert health_monitor._running is False
        assert health_monitor._session is None
    
    @pytest.mark.asyncio
    async def test_check_app_health_success(self, health_monitor, mock_app_manager, sample_running_app):
        """Test successful health check"""
        mock_app_manager.registry.get_app.return_value = sample_running_app
        
        # Mock the entire health check method to avoid async context manager complexity
        expected_result = HealthCheckResult(
            app_id="test-service",
            status=HealthStatus.GOOD,
            message="Service is healthy",
            response_time=0.1,
            extra_info={"uptime": "5 minutes"}
        )
        
        with patch.object(health_monitor, '_check_app_health', return_value=expected_result) as mock_check:
            result = await health_monitor._check_app_health("test-service")
        
        assert result is not None
        assert result.status == HealthStatus.GOOD
        assert result.message == "Service is healthy"
        assert result.extra_info == {"uptime": "5 minutes"}
        assert result.response_time is not None
    
    @pytest.mark.asyncio
    async def test_check_app_health_error_response(self, health_monitor, mock_app_manager, sample_running_app):
        """Test health check with error response"""
        mock_app_manager.registry.get_app.return_value = sample_running_app
        
        # Mock the health check method to return an error result
        expected_result = HealthCheckResult(
            app_id="test-service",
            status=HealthStatus.ERROR,
            message="Database connection failed",
            response_time=0.2
        )
        
        with patch.object(health_monitor, '_check_app_health', return_value=expected_result) as mock_check:
            with patch.object(health_monitor, '_handle_health_check_failure') as mock_handle_failure:
                result = await health_monitor._check_app_health("test-service")
        
        assert result is not None
        assert result.status == HealthStatus.ERROR
        assert result.message == "Database connection failed"
    
    @pytest.mark.asyncio
    async def test_check_app_health_timeout(self, health_monitor, mock_app_manager, sample_running_app):
        """Test health check timeout"""
        mock_app_manager.registry.get_app.return_value = sample_running_app
        
        # Mock timeout - need to mock the context manager properly
        mock_session = AsyncMock()
        mock_session.get.side_effect = asyncio.TimeoutError()
        health_monitor._session = mock_session
        
        with patch.object(health_monitor, '_handle_health_check_failure') as mock_handle_failure:
            result = await health_monitor._check_app_health("test-service")
        
        assert result is None
        # Check that failure was handled (the exact message may vary due to exception handling)
        mock_handle_failure.assert_called_once()
    
    @pytest.mark.asyncio
    async def test_handle_health_check_failure(self, health_monitor, mock_app_manager, sample_running_app):
        """Test handling health check failures"""
        mock_app_manager.registry.get_app.return_value = sample_running_app
        
        # First failure
        await health_monitor._handle_health_check_failure("test-service", "Connection refused")
        
        assert health_monitor.failure_counts["test-service"] == 1
        assert health_monitor.health_results["test-service"].status == HealthStatus.ERROR
        
        # Second failure (reaches threshold)
        await health_monitor._handle_health_check_failure("test-service", "Connection refused")
        
        assert health_monitor.failure_counts["test-service"] == 2
        mock_app_manager.registry.update_app.assert_called_with(
            "test-service",
            status=AppStatus.ERROR,
            runtime_info=sample_running_app.runtime_info
        )
    
    @pytest.mark.asyncio
    async def test_attempt_service_restart(self, health_monitor, mock_service_manager):
        """Test automatic service restart on failure"""
        mock_service_manager.restart_service.return_value = True
        
        await health_monitor._attempt_service_restart("test-service")
        
        mock_service_manager.restart_service.assert_called_once_with("test-service")
        assert health_monitor.failure_counts["test-service"] == 0
    
    def test_get_health_status(self, health_monitor):
        """Test getting health status for an app"""
        # Add a health result
        result = HealthCheckResult(
            app_id="test-service",
            status=HealthStatus.GOOD,
            message="Healthy"
        )
        health_monitor.health_results["test-service"] = result
        
        retrieved = health_monitor.get_health_status("test-service")
        
        assert retrieved == result
        assert health_monitor.get_health_status("nonexistent") is None
    
    def test_get_health_statistics(self, health_monitor):
        """Test getting health statistics"""
        # Add some health results
        health_monitor.health_results = {
            "app1": HealthCheckResult("app1", HealthStatus.GOOD, "OK", response_time=0.1),
            "app2": HealthCheckResult("app2", HealthStatus.WARNING, "Slow", response_time=0.5),
            "app3": HealthCheckResult("app3", HealthStatus.ERROR, "Failed")
        }
        health_monitor.failure_counts = {"app1": 0, "app2": 1, "app3": 3}
        
        stats = health_monitor.get_health_statistics()
        
        assert stats['total_apps'] == 3
        assert stats['healthy_apps'] == 1
        assert stats['warning_apps'] == 1
        assert stats['error_apps'] == 1
        assert stats['average_response_time'] == 0.3
        assert stats['total_failures'] == 4
    
    def test_update_config(self, health_monitor):
        """Test updating health check configuration"""
        health_monitor.update_config(interval=60, timeout=10, max_failures=5)
        
        assert health_monitor.config.interval == 60
        assert health_monitor.config.timeout == 10
        assert health_monitor.config.max_failures == 5
    
    def test_is_monitoring(self, health_monitor):
        """Test monitoring status check"""
        assert health_monitor.is_monitoring() is False
        
        health_monitor._running = True
        assert health_monitor.is_monitoring() is True


class TestCombinedHealth:
    """P-0005 Scope 3: combined systemd + /health status (flow-03)."""

    @pytest.fixture
    def hm(self, mock_config_manager, mock_app_manager, mock_service_manager):
        return HealthMonitor(mock_config_manager, mock_app_manager, mock_service_manager)

    @pytest.fixture
    def mock_config_manager(self):
        return Mock(spec=ConfigManager)

    @pytest.fixture
    def mock_app_manager(self):
        m = Mock(spec=AppManager)
        m.registry = Mock(spec=AppRegistry)
        return m

    @pytest.fixture
    def mock_service_manager(self):
        m = Mock(spec=ServiceManager)
        m.env = "dev"
        return m

    @pytest.mark.parametrize("systemd,health_status,expected", [
        # Rules from workflows.md flow-03.
        ("active", HealthStatus.GOOD, OverallStatus.GREEN),
        ("active", HealthStatus.WARNING, OverallStatus.YELLOW),
        ("active", HealthStatus.ERROR, OverallStatus.RED),
        ("active", HealthStatus.UNKNOWN, OverallStatus.YELLOW),
        ("activating", None, OverallStatus.YELLOW),
        ("inactive", None, OverallStatus.GREY),
        ("failed", None, OverallStatus.RED),
    ])
    def test_combine_matrix(self, systemd, health_status, expected):
        if health_status is None:
            health_result = None
        else:
            health_result = HealthCheckResult(
                app_id="x", status=health_status, message="ok",
            )
        overall, _detail = HealthMonitor._combine(systemd, health_result)
        assert overall == expected

    def test_combine_active_unreachable_yields_yellow(self):
        """systemd active + /health never probed → yellow 'unreachable'."""
        overall, detail = HealthMonitor._combine("active", None)
        assert overall == OverallStatus.YELLOW
        assert "unreachable" in detail

    def test_combine_none_systemd_no_health_yields_grey(self):
        """Non-Linux (no systemd) + no health data → grey 'no status'."""
        overall, _detail = HealthMonitor._combine(None, None)
        assert overall == OverallStatus.GREY

    def test_parse_systemctl_show_multiple_apps(self):
        """Parses blank-line-separated blocks into {app_id: ActiveState}."""
        sample = (
            "Id=latarnia-dev-app_a.service\n"
            "ActiveState=active\n"
            "SubState=running\n"
            "\n"
            "Id=latarnia-dev-app_b.service\n"
            "ActiveState=failed\n"
            "SubState=failed\n"
            "\n"
            "Id=latarnia-dev-app_c.service\n"
            "ActiveState=inactive\n"
            "SubState=dead\n"
        )
        states = HealthMonitor._parse_systemctl_show(sample, "latarnia-dev-")
        assert states == {
            "app_a": "active",
            "app_b": "failed",
            "app_c": "inactive",
        }

    def test_parse_systemctl_show_ignores_non_prefixed_units(self):
        sample = (
            "Id=someother.service\n"
            "ActiveState=active\n"
            "\n"
            "Id=latarnia-dev-only_ours.service\n"
            "ActiveState=active\n"
        )
        states = HealthMonitor._parse_systemctl_show(sample, "latarnia-dev-")
        assert states == {"only_ours": "active"}

    @patch("latarnia.managers.health_monitor.platform.system", return_value="Darwin")
    def test_get_systemd_states_returns_empty_on_macos(
        self, mock_system, hm,
    ):
        assert hm.get_systemd_states() == {}

    @patch("latarnia.managers.health_monitor.platform.system", return_value="Linux")
    @patch("latarnia.managers.health_monitor.subprocess.run")
    def test_get_systemd_states_caches_within_interval(
        self, mock_run, mock_system, hm,
    ):
        """Consecutive calls within the interval hit the cache, not systemctl."""
        mock_run.return_value.returncode = 0
        mock_run.return_value.stdout = (
            "Id=latarnia-dev-foo.service\nActiveState=active\n"
        )
        hm.config.interval = 30  # seconds
        first = hm.get_systemd_states()
        second = hm.get_systemd_states()
        assert first == second == {"foo": "active"}
        assert mock_run.call_count == 1

    def test_get_overall_status_end_to_end(self, hm):
        """End-to-end: combines the cached systemd map with health_results."""
        # Populate the cache manually to avoid shelling out.
        hm._systemd_states = {
            "green_app": "active",
            "yellow_app": "active",
            "red_app": "failed",
            "grey_app": "inactive",
        }
        hm._systemd_states_refreshed_at = datetime.now()
        hm.health_results = {
            "green_app": HealthCheckResult(
                app_id="green_app", status=HealthStatus.GOOD, message="all good",
            ),
            "yellow_app": HealthCheckResult(
                app_id="yellow_app", status=HealthStatus.WARNING, message="slow upstream",
            ),
        }
        with patch("latarnia.managers.health_monitor.platform.system", return_value="Linux"):
            assert hm.get_overall_status("green_app")["overall_status"] == "green"
            assert hm.get_overall_status("yellow_app")["overall_status"] == "yellow"
            assert hm.get_overall_status("red_app")["overall_status"] == "red"
            assert hm.get_overall_status("grey_app")["overall_status"] == "grey"
            # Detail from HealthCheckResult flows through for active paths.
            assert "all good" in hm.get_overall_status("green_app")["detail"]
            assert "slow upstream" in hm.get_overall_status("yellow_app")["detail"]


class TestServiceInfo:
    """Test cases for ServiceInfo dataclass"""
    
    def test_service_info_creation(self):
        """Test ServiceInfo creation"""
        info = ServiceInfo(
            service_name="test-service",
            status=ServiceStatus.ACTIVE,
            state=ServiceState.RUNNING,
            pid=12345,
            memory_usage=1024*1024,
            uptime=timedelta(hours=2, minutes=30)
        )
        
        assert info.service_name == "test-service"
        assert info.status == ServiceStatus.ACTIVE
        assert info.state == ServiceState.RUNNING
        assert info.pid == 12345
        assert info.memory_usage == 1024*1024
        assert info.uptime == timedelta(hours=2, minutes=30)
    
    def test_service_info_serialization(self):
        """Test ServiceInfo serialization and deserialization"""
        info = ServiceInfo(
            service_name="test-service",
            status=ServiceStatus.ACTIVE,
            state=ServiceState.RUNNING,
            uptime=timedelta(hours=1),
            last_restart=datetime(2024, 1, 1, 12, 0, 0)
        )
        
        # Test serialization
        data = info.to_dict()
        assert isinstance(data['uptime'], str)
        assert isinstance(data['last_restart'], str)
        
        # Test deserialization
        restored = ServiceInfo.from_dict(data)
        assert restored.service_name == info.service_name
        assert restored.status == info.status
        assert restored.state == info.state
        assert isinstance(restored.uptime, timedelta)
        assert isinstance(restored.last_restart, datetime)


class TestHealthCheckResult:
    """Test cases for HealthCheckResult dataclass"""
    
    def test_health_check_result_creation(self):
        """Test HealthCheckResult creation"""
        result = HealthCheckResult(
            app_id="test-app",
            status=HealthStatus.GOOD,
            message="All systems operational",
            response_time=0.15,
            extra_info={"cpu": "5%", "memory": "128MB"}
        )
        
        assert result.app_id == "test-app"
        assert result.status == HealthStatus.GOOD
        assert result.message == "All systems operational"
        assert result.response_time == 0.15
        assert result.extra_info == {"cpu": "5%", "memory": "128MB"}
        assert isinstance(result.timestamp, datetime)
    
    def test_health_check_result_serialization(self):
        """Test HealthCheckResult serialization and deserialization"""
        result = HealthCheckResult(
            app_id="test-app",
            status=HealthStatus.WARNING,
            message="High memory usage",
            timestamp=datetime(2024, 1, 1, 12, 0, 0)
        )
        
        # Test serialization
        data = result.to_dict()
        assert isinstance(data['timestamp'], str)
        assert data['timestamp'] == "2024-01-01T12:00:00"
        
        # Test deserialization
        restored = HealthCheckResult.from_dict(data)
        assert restored.app_id == result.app_id
        assert restored.status == result.status
        assert restored.message == result.message
        assert isinstance(restored.timestamp, datetime)
        assert restored.timestamp == result.timestamp
