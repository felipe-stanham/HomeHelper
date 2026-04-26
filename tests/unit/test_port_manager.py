"""
Unit tests for PortManager

Tests port allocation, tracking, and cleanup functionality.
"""

import json
import pytest
import tempfile
from pathlib import Path
from unittest.mock import Mock, patch, MagicMock
from datetime import datetime, timedelta

import sys
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "src"))

from latarnia.core.config import ConfigManager
from latarnia.managers.port_manager import PortManager, PortAllocation


class TestPortManager:
    """Test cases for PortManager"""
    
    @pytest.fixture
    def temp_config_dir(self):
        """Create temporary config directory"""
        with tempfile.TemporaryDirectory() as temp_dir:
            yield Path(temp_dir)
    
    @pytest.fixture
    def mock_config_manager(self, temp_config_dir):
        """Mock ConfigManager with test configuration"""
        mock_config = Mock()
        mock_config.process_manager.port_range.start = 8100
        mock_config.process_manager.port_range.end = 8105  # Small range for testing
        mock_config.process_manager.mcp_port_range.start = 9001
        mock_config.process_manager.mcp_port_range.end = 9005  # Small range for testing

        mock_config_manager = Mock(spec=ConfigManager)
        mock_config_manager.config = mock_config
        mock_config_manager.get_data_dir.return_value = temp_config_dir

        return mock_config_manager
    
    @pytest.fixture
    def port_manager(self, mock_config_manager):
        """Create PortManager instance for testing"""
        with patch('socket.socket') as mock_socket:
            # Mock socket to always return available ports
            mock_socket.return_value.__enter__.return_value.bind.return_value = None
            return PortManager(mock_config_manager)
    
    def test_port_allocation_creation(self):
        """Test PortAllocation dataclass creation and serialization"""
        allocation = PortAllocation(
            port=8100,
            app_id="test-app",
            app_type="service",
            allocated_at=datetime.now(),
            status="allocated"
        )
        
        assert allocation.port == 8100
        assert allocation.app_id == "test-app"
        assert allocation.app_type == "service"
        assert allocation.status == "allocated"
        
        # Test serialization
        data = allocation.to_dict()
        assert isinstance(data['allocated_at'], str)
        
        # Test deserialization
        restored = PortAllocation.from_dict(data)
        assert restored.port == allocation.port
        assert restored.app_id == allocation.app_id
    
    def test_port_manager_initialization(self, mock_config_manager):
        """Test PortManager initialization"""
        with patch('socket.socket') as mock_socket:
            mock_socket.return_value.__enter__.return_value.bind.return_value = None

            port_manager = PortManager(mock_config_manager)

            assert port_manager.port_start == 8100
            assert port_manager.port_end == 8105
            assert port_manager.mcp_port_start == 9001
            assert port_manager.mcp_port_end == 9005
            assert len(port_manager.allocations) == 0
            assert len(port_manager.app_ports) == 0
            assert len(port_manager.mcp_allocations) == 0
            assert len(port_manager.app_mcp_ports) == 0
    
    @patch('socket.socket')
    def test_allocate_port_success(self, mock_socket, port_manager):
        """Test successful port allocation"""
        # Mock socket to indicate port is available
        mock_socket.return_value.__enter__.return_value.bind.return_value = None
        
        port = port_manager.allocate_port("test-app", "service")
        
        assert port is not None
        assert 8100 <= port <= 8105
        assert port in port_manager.allocations
        assert port_manager.app_ports["test-app"] == port
        
        allocation = port_manager.allocations[port]
        assert allocation.app_id == "test-app"
        assert allocation.app_type == "service"
        assert allocation.status == "allocated"
    
    @patch('socket.socket')
    def test_allocate_port_preferred(self, mock_socket, port_manager):
        """Test port allocation with preferred port"""
        mock_socket.return_value.__enter__.return_value.bind.return_value = None
        
        preferred_port = 8103
        port = port_manager.allocate_port("test-app", "service", preferred_port)
        
        assert port == preferred_port
        assert port_manager.app_ports["test-app"] == preferred_port
    
    @patch('socket.socket')
    def test_allocate_port_no_available_ports(self, mock_socket, port_manager):
        """Test port allocation when no ports are available"""
        # Mock socket to indicate all ports are in use
        mock_socket.return_value.__enter__.return_value.bind.side_effect = OSError("Port in use")
        
        port = port_manager.allocate_port("test-app", "service")
        
        assert port is None
        assert "test-app" not in port_manager.app_ports
    
    @patch('socket.socket')
    def test_allocate_port_reuse_existing(self, mock_socket, port_manager):
        """Test reusing existing port allocation"""
        mock_socket.return_value.__enter__.return_value.bind.return_value = None
        
        # First allocation
        port1 = port_manager.allocate_port("test-app", "service")
        assert port1 is not None
        
        # Second allocation for same app should reuse port
        port2 = port_manager.allocate_port("test-app", "service")
        assert port2 == port1
    
    def test_release_port_success(self, port_manager):
        """Test successful port release"""
        with patch('socket.socket') as mock_socket:
            mock_socket.return_value.__enter__.return_value.bind.return_value = None
            
            # Allocate port first
            port = port_manager.allocate_port("test-app", "service")
            assert port is not None
            
            # Release port
            result = port_manager.release_port("test-app")
            
            assert result is True
            assert "test-app" not in port_manager.app_ports
            assert port not in port_manager.allocations
    
    def test_release_port_not_found(self, port_manager):
        """Test releasing port for non-existent app"""
        result = port_manager.release_port("non-existent-app")
        assert result is False
    
    def test_get_app_port(self, port_manager):
        """Test getting port for an app"""
        with patch('socket.socket') as mock_socket:
            mock_socket.return_value.__enter__.return_value.bind.return_value = None
            
            # No port allocated initially
            assert port_manager.get_app_port("test-app") is None
            
            # Allocate port
            allocated_port = port_manager.allocate_port("test-app", "service")
            
            # Should return allocated port
            assert port_manager.get_app_port("test-app") == allocated_port
    
    def test_mark_port_in_use(self, port_manager):
        """Test marking port as in use"""
        with patch('socket.socket') as mock_socket:
            mock_socket.return_value.__enter__.return_value.bind.return_value = None
            
            # Allocate port
            port = port_manager.allocate_port("test-app", "service")
            
            # Mark as in use
            result = port_manager.mark_port_in_use("test-app")
            
            assert result is True
            assert port_manager.allocations[port].status == "in_use"
    
    def test_get_allocated_ports(self, port_manager):
        """Test getting all allocated ports"""
        with patch('socket.socket') as mock_socket:
            mock_socket.return_value.__enter__.return_value.bind.return_value = None
            
            # Initially empty
            assert len(port_manager.get_allocated_ports()) == 0
            
            # Allocate some ports
            port_manager.allocate_port("app1", "service")
            port_manager.allocate_port("app2", "streamlit")
            
            allocations = port_manager.get_allocated_ports()
            assert len(allocations) == 2
            
            app_ids = [alloc.app_id for alloc in allocations]
            assert "app1" in app_ids
            assert "app2" in app_ids
    
    @patch('socket.socket')
    def test_get_available_ports(self, mock_socket, port_manager):
        """Test getting available ports"""
        mock_socket.return_value.__enter__.return_value.bind.return_value = None
        
        # All ports should be available initially
        available = port_manager.get_available_ports()
        assert len(available) == 6  # 8100-8105 inclusive
        
        # Allocate one port
        port_manager.allocate_port("test-app", "service")
        
        # One less port should be available
        available_after = port_manager.get_available_ports()
        assert len(available_after) == 5
    
    def test_cleanup_stale_allocations(self, port_manager):
        """Test cleanup of stale port allocations"""
        with patch('socket.socket') as mock_socket:
            mock_socket.return_value.__enter__.return_value.bind.return_value = None
            
            # Allocate port
            port = port_manager.allocate_port("test-app", "service")
            
            # Make allocation old
            allocation = port_manager.allocations[port]
            allocation.allocated_at = datetime.now() - timedelta(hours=2)
            
            # Mock port as available (indicating it's stale)
            mock_socket.return_value.__enter__.return_value.bind.return_value = None
            
            # Cleanup should remove stale allocation
            cleaned = port_manager.cleanup_stale_allocations()
            
            assert cleaned == 1
            assert "test-app" not in port_manager.app_ports
    
    def test_get_port_statistics(self, port_manager):
        """Test port statistics generation"""
        with patch('socket.socket') as mock_socket:
            mock_socket.return_value.__enter__.return_value.bind.return_value = None
            
            # Get initial stats
            stats = port_manager.get_port_statistics()
            assert stats['total_ports'] == 6
            assert stats['allocated_ports'] == 0
            assert stats['utilization_percent'] == 0.0
            
            # Allocate some ports
            port_manager.allocate_port("app1", "service")
            port_manager.allocate_port("app2", "streamlit")
            
            # Get updated stats
            stats_after = port_manager.get_port_statistics()
            assert stats_after['allocated_ports'] == 2
            assert stats_after['utilization_percent'] == 33.3
            assert stats_after['app_type_breakdown']['service'] == 1
            assert stats_after['app_type_breakdown']['streamlit'] == 1
    
    def test_in_memory_only_no_persistence(self, mock_config_manager, temp_config_dir):
        """Test that port manager is in-memory only (no persistence)"""
        with patch('socket.socket') as mock_socket:
            mock_socket.return_value.__enter__.return_value.bind.return_value = None
            
            # Create first port manager and allocate ports
            port_manager1 = PortManager(mock_config_manager)
            port1 = port_manager1.allocate_port("app1", "service")
            port2 = port_manager1.allocate_port("app2", "streamlit")
            
            assert len(port_manager1.allocations) == 2
            
            # Create second port manager (should be empty - no persistence)
            port_manager2 = PortManager(mock_config_manager)
            
            # Should be empty - fresh start
            assert len(port_manager2.allocations) == 0
            assert port_manager2.get_app_port("app1") is None
            assert port_manager2.get_app_port("app2") is None
    
    def test_no_persistence_files_created(self, mock_config_manager, temp_config_dir):
        """Test that no persistence files are created"""
        with patch('socket.socket') as mock_socket:
            mock_socket.return_value.__enter__.return_value.bind.return_value = None

            # Create port manager and allocate ports
            port_manager = PortManager(mock_config_manager)
            port_manager.allocate_port("app1", "service")

            # Verify no persistence files were created
            ports_file = temp_config_dir / "registry" / "ports.json"
            assert not ports_file.exists()  # No persistence file should be created

    # --- MCP Port Allocation Tests ---

    @patch('socket.socket')
    def test_allocate_mcp_port_success(self, mock_socket, port_manager):
        """Test successful MCP port allocation"""
        mock_socket.return_value.__enter__.return_value.bind.return_value = None

        mcp_port = port_manager.allocate_mcp_port("test-app")

        assert mcp_port is not None
        assert 9001 <= mcp_port <= 9005
        assert mcp_port in port_manager.mcp_allocations
        assert port_manager.app_mcp_ports["test-app"] == mcp_port

        allocation = port_manager.mcp_allocations[mcp_port]
        assert allocation.app_id == "test-app"
        assert allocation.app_type == "mcp"
        assert allocation.status == "allocated"

    @patch('socket.socket')
    def test_allocate_mcp_port_no_available(self, mock_socket, port_manager):
        """Test MCP port allocation when no ports are available"""
        mock_socket.return_value.__enter__.return_value.bind.side_effect = OSError("Port in use")

        mcp_port = port_manager.allocate_mcp_port("test-app")

        assert mcp_port is None
        assert "test-app" not in port_manager.app_mcp_ports

    @patch('socket.socket')
    def test_allocate_mcp_port_reuse_existing(self, mock_socket, port_manager):
        """Test reusing existing MCP port allocation"""
        mock_socket.return_value.__enter__.return_value.bind.return_value = None

        port1 = port_manager.allocate_mcp_port("test-app")
        assert port1 is not None

        port2 = port_manager.allocate_mcp_port("test-app")
        assert port2 == port1

    def test_release_mcp_port_success(self, port_manager):
        """Test successful MCP port release"""
        with patch('socket.socket') as mock_socket:
            mock_socket.return_value.__enter__.return_value.bind.return_value = None

            mcp_port = port_manager.allocate_mcp_port("test-app")
            assert mcp_port is not None

            result = port_manager.release_mcp_port("test-app")

            assert result is True
            assert "test-app" not in port_manager.app_mcp_ports
            assert mcp_port not in port_manager.mcp_allocations

    def test_release_mcp_port_not_found(self, port_manager):
        """Test releasing MCP port for non-existent app"""
        result = port_manager.release_mcp_port("non-existent-app")
        assert result is False

    @patch('socket.socket')
    def test_get_app_mcp_port(self, mock_socket, port_manager):
        """Test getting MCP port for an app"""
        mock_socket.return_value.__enter__.return_value.bind.return_value = None

        assert port_manager.get_app_mcp_port("test-app") is None

        allocated_port = port_manager.allocate_mcp_port("test-app")
        assert port_manager.get_app_mcp_port("test-app") == allocated_port

    @patch('socket.socket')
    def test_mcp_ports_independent_from_rest_ports(self, mock_socket, port_manager):
        """Test that MCP and REST port allocations are independent"""
        mock_socket.return_value.__enter__.return_value.bind.return_value = None

        rest_port = port_manager.allocate_port("test-app", "service")
        mcp_port = port_manager.allocate_mcp_port("test-app")

        assert rest_port is not None
        assert mcp_port is not None
        assert rest_port != mcp_port
        assert port_manager.app_ports["test-app"] == rest_port
        assert port_manager.app_mcp_ports["test-app"] == mcp_port

        # Release REST port should not affect MCP port
        port_manager.release_port("test-app")
        assert port_manager.get_app_mcp_port("test-app") == mcp_port

        # Release MCP port
        port_manager.release_mcp_port("test-app")
        assert port_manager.get_app_mcp_port("test-app") is None

    def test_claim_port_records_allocation_without_availability_check(self, port_manager):
        """claim_port reserves a specific port even if it's already in use
        externally (the reconciliation use case — the platform's per-app
        unit is the one using it)."""
        # Don't bother mocking socket — claim_port skips availability checks.
        port = port_manager.claim_port("reconciled-app", "service", 8123)
        assert port == 8123
        assert port_manager.app_ports["reconciled-app"] == 8123
        assert 8123 in port_manager.allocations
        assert port_manager.allocations[8123].app_id == "reconciled-app"
        assert port_manager.allocations[8123].app_type == "service"

    def test_claim_mcp_port_records_allocation(self, port_manager):
        """claim_mcp_port mirrors claim_port for MCP allocations."""
        port = port_manager.claim_mcp_port("reconciled-app", 9012)
        assert port == 9012
        assert port_manager.app_mcp_ports["reconciled-app"] == 9012
        assert 9012 in port_manager.mcp_allocations

    @patch('socket.socket')
    def test_port_statistics_includes_mcp(self, mock_socket, port_manager):
        """Test that port statistics include MCP port counts"""
        mock_socket.return_value.__enter__.return_value.bind.return_value = None

        port_manager.allocate_port("app1", "service")
        port_manager.allocate_mcp_port("app1")
        port_manager.allocate_mcp_port("app2")

        stats = port_manager.get_port_statistics()

        assert stats['mcp_total_ports'] == 5  # 9001-9005
        assert stats['mcp_allocated_ports'] == 2
        assert stats['mcp_port_range'] == "9001-9005"
        assert stats['mcp_utilization_percent'] == 40.0
        # REST stats still correct
        assert stats['allocated_ports'] == 1
