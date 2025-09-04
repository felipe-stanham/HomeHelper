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

from homehelper.core.config import ConfigManager
from homehelper.managers.port_manager import PortManager, PortAllocation


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
            assert len(port_manager.allocations) == 0
            assert len(port_manager.app_ports) == 0
    
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
    
    def test_persistence_save_and_load(self, mock_config_manager, temp_config_dir):
        """Test saving and loading port allocations"""
        with patch('socket.socket') as mock_socket:
            mock_socket.return_value.__enter__.return_value.bind.return_value = None
            
            # Create first port manager and allocate ports
            port_manager1 = PortManager(mock_config_manager)
            port1 = port_manager1.allocate_port("app1", "service")
            port2 = port_manager1.allocate_port("app2", "streamlit")
            
            # Create second port manager (should load from disk)
            port_manager2 = PortManager(mock_config_manager)
            
            # Should have loaded the allocations
            assert len(port_manager2.allocations) == 2
            assert port_manager2.get_app_port("app1") == port1
            assert port_manager2.get_app_port("app2") == port2
    
    def test_persistence_corrupted_file(self, mock_config_manager, temp_config_dir):
        """Test handling of corrupted persistence file"""
        # Create corrupted file
        ports_file = temp_config_dir / "registry" / "ports.json"
        ports_file.parent.mkdir(parents=True, exist_ok=True)
        with open(ports_file, 'w') as f:
            f.write("invalid json content")
        
        with patch('socket.socket') as mock_socket:
            mock_socket.return_value.__enter__.return_value.bind.return_value = None
            
            # Should handle corrupted file gracefully
            port_manager = PortManager(mock_config_manager)
            assert len(port_manager.allocations) == 0
