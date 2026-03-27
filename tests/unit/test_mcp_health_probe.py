"""
Unit tests for MCP health probe in HealthMonitor

Tests the MCP liveness probe that runs after /health passes for apps
that declare mcp_server: true.
"""

import pytest
import asyncio
from pathlib import Path
from unittest.mock import Mock, AsyncMock, patch, MagicMock
from datetime import datetime

import sys
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "src"))

from latarnia.core.config import ConfigManager
from latarnia.managers.app_manager import (
    AppManager, AppRegistry, AppManifest, AppType, AppStatus,
    AppRuntimeInfo, AppRegistryEntry, MCPInfo, AppConfig,
)
from latarnia.managers.port_manager import PortManager
from latarnia.managers.service_manager import ServiceManager
from latarnia.managers.health_monitor import HealthMonitor, HealthCheckResult, HealthStatus


def _make_app_entry(
    mcp_server: bool = False,
    mcp_port: int = None,
    assigned_port: int = 8100,
) -> AppRegistryEntry:
    """Helper to create a test AppRegistryEntry with MCP settings."""
    config_kwargs = {"has_UI": True, "mcp_server": mcp_server}
    if mcp_port is not None:
        config_kwargs["mcp_port"] = mcp_port

    manifest = AppManifest(
        name="mcp-test-app",
        type=AppType.SERVICE,
        description="Test MCP app",
        version="1.0.0",
        author="Test",
        main_file="app.py",
        config=config_kwargs,
    )
    runtime_info = AppRuntimeInfo(assigned_port=assigned_port)

    mcp_info = None
    if mcp_server:
        mcp_info = MCPInfo(enabled=True, mcp_port=mcp_port)

    return AppRegistryEntry(
        app_id="mcp-test-app",
        name="mcp-test-app",
        type=AppType.SERVICE,
        description="Test MCP app",
        version="1.0.0",
        status=AppStatus.RUNNING,
        path=Path("/tmp/mcp-test-app"),
        manifest=manifest,
        runtime_info=runtime_info,
        mcp_info=mcp_info,
    )


class TestMCPHealthProbe:
    """Test cases for the MCP liveness probe in HealthMonitor."""

    @pytest.fixture
    def mock_config_manager(self):
        return Mock(spec=ConfigManager)

    @pytest.fixture
    def mock_app_manager(self):
        mgr = Mock(spec=AppManager)
        mgr.registry = Mock(spec=AppRegistry)
        return mgr

    @pytest.fixture
    def mock_service_manager(self):
        return Mock(spec=ServiceManager)

    @pytest.fixture
    def health_monitor(self, mock_config_manager, mock_app_manager, mock_service_manager):
        return HealthMonitor(mock_config_manager, mock_app_manager, mock_service_manager)

    # ------------------------------------------------------------------
    # Probe success
    # ------------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_mcp_probe_success(self, health_monitor, mock_app_manager):
        """MCP probe marks healthy=True when the MCP port returns 200."""
        app = _make_app_entry(mcp_server=True, mcp_port=9001)
        mock_app_manager.registry.get_app.return_value = app

        # Mock the HTTP session to return 200 on /sse
        mock_response = AsyncMock()
        mock_response.status = 200
        mock_response.__aenter__ = AsyncMock(return_value=mock_response)
        mock_response.__aexit__ = AsyncMock(return_value=False)

        mock_session = AsyncMock()
        mock_session.get.return_value = mock_response
        health_monitor._session = mock_session

        await health_monitor._probe_mcp_health(app)

        assert app.mcp_info.healthy is True
        mock_app_manager.registry.update_app.assert_called_with(
            "mcp-test-app", mcp_info=app.mcp_info
        )

    # ------------------------------------------------------------------
    # Probe failure (connection refused / non-2xx)
    # ------------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_mcp_probe_failure_connection_error(self, health_monitor, mock_app_manager):
        """MCP probe marks healthy=False when connection is refused."""
        app = _make_app_entry(mcp_server=True, mcp_port=9001)
        mock_app_manager.registry.get_app.return_value = app

        mock_session = AsyncMock()
        mock_session.get.side_effect = ConnectionRefusedError("Connection refused")
        health_monitor._session = mock_session

        await health_monitor._probe_mcp_health(app)

        assert app.mcp_info.healthy is False
        mock_app_manager.registry.update_app.assert_called_with(
            "mcp-test-app", mcp_info=app.mcp_info
        )

    @pytest.mark.asyncio
    async def test_mcp_probe_failure_non_2xx(self, health_monitor, mock_app_manager):
        """MCP probe marks healthy=False when all probed paths return non-2xx."""
        app = _make_app_entry(mcp_server=True, mcp_port=9001)
        mock_app_manager.registry.get_app.return_value = app

        # Return 404 for all probe paths
        mock_response = AsyncMock()
        mock_response.status = 404
        mock_response.__aenter__ = AsyncMock(return_value=mock_response)
        mock_response.__aexit__ = AsyncMock(return_value=False)

        mock_session = AsyncMock()
        mock_session.get.return_value = mock_response
        health_monitor._session = mock_session

        await health_monitor._probe_mcp_health(app)

        assert app.mcp_info.healthy is False

    # ------------------------------------------------------------------
    # Probe timeout
    # ------------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_mcp_probe_timeout(self, health_monitor, mock_app_manager):
        """MCP probe marks healthy=False when the request times out."""
        app = _make_app_entry(mcp_server=True, mcp_port=9001)
        mock_app_manager.registry.get_app.return_value = app

        mock_session = AsyncMock()
        mock_session.get.side_effect = asyncio.TimeoutError()
        health_monitor._session = mock_session

        await health_monitor._probe_mcp_health(app)

        assert app.mcp_info.healthy is False
        mock_app_manager.registry.update_app.assert_called_with(
            "mcp-test-app", mcp_info=app.mcp_info
        )

    # ------------------------------------------------------------------
    # Probe skipped when MCP is not enabled
    # ------------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_mcp_probe_skipped_when_not_enabled(self, health_monitor, mock_app_manager):
        """MCP probe is skipped entirely when mcp_server is false."""
        app = _make_app_entry(mcp_server=False)
        mock_app_manager.registry.get_app.return_value = app

        mock_session = AsyncMock()
        health_monitor._session = mock_session

        await health_monitor._probe_mcp_health(app)

        # Session.get should never be called
        mock_session.get.assert_not_called()
        # Registry should not be updated
        mock_app_manager.registry.update_app.assert_not_called()

    @pytest.mark.asyncio
    async def test_mcp_probe_skipped_when_no_mcp_info(self, health_monitor, mock_app_manager):
        """MCP probe is skipped when the app has no MCPInfo at all."""
        app = _make_app_entry(mcp_server=False)
        app.mcp_info = None
        mock_app_manager.registry.get_app.return_value = app

        mock_session = AsyncMock()
        health_monitor._session = mock_session

        await health_monitor._probe_mcp_health(app)

        mock_session.get.assert_not_called()

    @pytest.mark.asyncio
    async def test_mcp_probe_skipped_when_no_port(self, health_monitor, mock_app_manager):
        """MCP probe is skipped when mcp_server is true but mcp_port is None."""
        app = _make_app_entry(mcp_server=True, mcp_port=None)
        # Manually set mcp_info with no port
        app.mcp_info = MCPInfo(enabled=True, mcp_port=None)
        mock_app_manager.registry.get_app.return_value = app

        mock_session = AsyncMock()
        health_monitor._session = mock_session

        await health_monitor._probe_mcp_health(app)

        mock_session.get.assert_not_called()

    # ------------------------------------------------------------------
    # Probe tries multiple paths and succeeds on fallback
    # ------------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_mcp_probe_succeeds_on_fallback_path(self, health_monitor, mock_app_manager):
        """MCP probe tries /sse, then /mcp, then / — succeeds on /mcp."""
        app = _make_app_entry(mcp_server=True, mcp_port=9001)
        mock_app_manager.registry.get_app.return_value = app

        # First call (/sse) -> connection error, second (/mcp) -> 200
        mock_response_ok = AsyncMock()
        mock_response_ok.status = 200
        mock_response_ok.__aenter__ = AsyncMock(return_value=mock_response_ok)
        mock_response_ok.__aexit__ = AsyncMock(return_value=False)

        call_count = 0

        async def side_effect(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise ConnectionRefusedError("Connection refused")
            return mock_response_ok

        mock_session = AsyncMock()
        mock_session.get.side_effect = side_effect
        health_monitor._session = mock_session

        await health_monitor._probe_mcp_health(app)

        assert app.mcp_info.healthy is True
        assert call_count == 2  # /sse failed, /mcp succeeded


class TestMCPProbeIntegration:
    """Test that MCP probe is called as part of the health check flow."""

    @pytest.fixture
    def mock_config_manager(self):
        return Mock(spec=ConfigManager)

    @pytest.fixture
    def mock_app_manager(self):
        mgr = Mock(spec=AppManager)
        mgr.registry = Mock(spec=AppRegistry)
        return mgr

    @pytest.fixture
    def mock_service_manager(self):
        return Mock(spec=ServiceManager)

    @pytest.fixture
    def health_monitor(self, mock_config_manager, mock_app_manager, mock_service_manager):
        return HealthMonitor(mock_config_manager, mock_app_manager, mock_service_manager)

    @pytest.mark.asyncio
    async def test_health_check_calls_mcp_probe_on_success(
        self, health_monitor, mock_app_manager
    ):
        """After /health returns good, _probe_mcp_health is called."""
        app = _make_app_entry(mcp_server=True, mcp_port=9001)
        mock_app_manager.registry.get_app.return_value = app
        mock_app_manager.registry.update_app.return_value = True

        # Mock /health response
        mock_health_response = AsyncMock()
        mock_health_response.status = 200
        mock_health_response.json = AsyncMock(return_value={
            "health": "good",
            "message": "OK",
            "extra_info": {},
        })
        mock_health_response.__aenter__ = AsyncMock(return_value=mock_health_response)
        mock_health_response.__aexit__ = AsyncMock(return_value=False)

        mock_session = AsyncMock()
        mock_session.get.return_value = mock_health_response
        health_monitor._session = mock_session

        with patch.object(
            health_monitor, '_probe_mcp_health', new_callable=AsyncMock
        ) as mock_probe:
            result = await health_monitor._check_app_health("mcp-test-app")

        assert result is not None
        assert result.status == HealthStatus.GOOD
        mock_probe.assert_called_once_with(app)

    @pytest.mark.asyncio
    async def test_health_check_skips_mcp_probe_on_error(
        self, health_monitor, mock_app_manager
    ):
        """If /health returns error, _probe_mcp_health is NOT called."""
        app = _make_app_entry(mcp_server=True, mcp_port=9001)
        mock_app_manager.registry.get_app.return_value = app
        mock_app_manager.registry.update_app.return_value = True

        # Mock /health response with error status
        mock_health_response = AsyncMock()
        mock_health_response.status = 200
        mock_health_response.json = AsyncMock(return_value={
            "health": "error",
            "message": "Database down",
            "extra_info": {},
        })
        mock_health_response.__aenter__ = AsyncMock(return_value=mock_health_response)
        mock_health_response.__aexit__ = AsyncMock(return_value=False)

        mock_session = AsyncMock()
        mock_session.get.return_value = mock_health_response
        health_monitor._session = mock_session

        with patch.object(
            health_monitor, '_probe_mcp_health', new_callable=AsyncMock
        ) as mock_probe:
            result = await health_monitor._check_app_health("mcp-test-app")

        # MCP probe should NOT be called when /health status is error
        mock_probe.assert_not_called()
