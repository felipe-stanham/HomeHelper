"""
Unit tests for AppManager and AppRegistry

Tests application discovery, manifest parsing, and registry management.
"""

import json
import pytest
import tempfile
from pathlib import Path
from unittest.mock import Mock, patch, MagicMock
from datetime import datetime

import sys
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "src"))

from homehelper.core.config import ConfigManager
from homehelper.managers.app_manager import (
    AppManager, AppRegistry, AppRegistryEntry, AppManifest, 
    AppType, AppStatus, AppEndpoints, AppRuntimeInfo
)
from homehelper.managers.port_manager import PortManager


class TestAppManifest:
    """Test cases for AppManifest validation"""
    
    def test_valid_service_manifest(self):
        """Test valid service app manifest"""
        data = {
            "name": "test-service",
            "type": "service",
            "description": "Test service application",
            "version": "1.0.0",
            "author": "Test Author",
            "main_file": "app.py",
            "config": {
                "has_UI": True,
                "redis_required": False
            },
            "install": {
                "setup_commands": ["echo 'setup complete'"]
            }
        }
        
        manifest = AppManifest(**data)
        assert manifest.name == "test-service"
        assert manifest.type == AppType.SERVICE
        assert manifest.config.has_UI == True
        assert manifest.config.redis_required == False
        assert manifest.install.setup_commands == ["echo 'setup complete'"]
    
    def test_valid_streamlit_manifest(self):
        """Test valid Streamlit app manifest"""
        data = {
            "name": "data-viz",
            "type": "streamlit",
            "description": "Data visualization dashboard",
            "version": "2.1.0",
            "author": "Viz Author",
            "main_file": "app.py"
        }
        
        manifest = AppManifest(**data)
        assert manifest.name == "data-viz"
        assert manifest.type == AppType.STREAMLIT
        assert manifest.config.has_UI == False  # Default value
        assert manifest.config.auto_start == False  # Default value
    
    def test_invalid_version_format(self):
        """Test invalid version format"""
        data = {
            "name": "test-app",
            "type": "service",
            "description": "Test app",
            "version": "1.0",  # Invalid format
            "author": "Test Author",
            "main_file": "app.py"
        }
        
        with pytest.raises(Exception):  # Pydantic ValidationError
            AppManifest(**data)
    
    def test_missing_required_fields(self):
        """Test missing required fields"""
        data = {
            "name": "test-app",
            "type": "service"
            # Missing required fields: description, version, author, main_file
        }
        
        with pytest.raises(Exception):  # Pydantic ValidationError
            AppManifest(**data)


class TestAppRuntimeInfo:
    """Test cases for AppRuntimeInfo"""
    
    def test_runtime_info_serialization(self):
        """Test runtime info serialization and deserialization"""
        runtime_info = AppRuntimeInfo(
            assigned_port=8100,
            process_id="12345",
            started_at=datetime.now(),
            resource_usage={"cpu": 5.5, "memory": 128}
        )
        
        # Test serialization
        data = runtime_info.to_dict()
        assert isinstance(data['started_at'], str)
        assert data['assigned_port'] == 8100
        
        # Test deserialization
        restored = AppRuntimeInfo.from_dict(data)
        assert restored.assigned_port == runtime_info.assigned_port
        assert restored.process_id == runtime_info.process_id
        assert isinstance(restored.started_at, datetime)


class TestAppRegistryEntry:
    """Test cases for AppRegistryEntry"""
    
    @pytest.fixture
    def sample_manifest(self):
        """Sample app manifest for testing"""
        return AppManifest(
            name="test-app",
            type=AppType.SERVICE,
            description="Test application",
            version="1.0.0",
            author="Test Author",
            main_file="app.py"
        )
    
    def test_registry_entry_creation(self, sample_manifest, tmp_path):
        """Test registry entry creation"""
        entry = AppRegistryEntry(
            app_id="test-app-1",
            name="test-app",
            type=AppType.SERVICE,
            description="Test application",
            version="1.0.0",
            status=AppStatus.DISCOVERED,
            path=tmp_path,
            manifest=sample_manifest
        )
        
        assert entry.app_id == "test-app-1"
        assert entry.type == AppType.SERVICE
        assert entry.status == AppStatus.DISCOVERED
        assert entry.path == tmp_path
    
    def test_registry_entry_serialization(self, sample_manifest, tmp_path):
        """Test registry entry serialization"""
        entry = AppRegistryEntry(
            app_id="test-app-1",
            name="test-app",
            type=AppType.SERVICE,
            description="Test application",
            version="1.0.0",
            status=AppStatus.DISCOVERED,
            path=tmp_path,
            manifest=sample_manifest
        )
        
        # Test serialization
        data = entry.to_dict()
        assert isinstance(data['path'], str)
        assert isinstance(data['discovered_at'], str)
        assert data['type'] == 'service'
        
        # Test deserialization
        restored = AppRegistryEntry.from_dict(data)
        assert restored.app_id == entry.app_id
        assert restored.type == entry.type
        assert isinstance(restored.path, Path)


class TestAppRegistry:
    """Test cases for AppRegistry"""
    
    @pytest.fixture
    def temp_config_dir(self):
        """Create temporary config directory"""
        with tempfile.TemporaryDirectory() as temp_dir:
            yield Path(temp_dir)
    
    @pytest.fixture
    def mock_config_manager(self, temp_config_dir):
        """Mock ConfigManager for testing"""
        mock_config_manager = Mock(spec=ConfigManager)
        mock_config_manager.get_data_dir.return_value = temp_config_dir
        return mock_config_manager
    
    @pytest.fixture
    def app_registry(self, mock_config_manager):
        """Create AppRegistry instance for testing"""
        return AppRegistry(mock_config_manager)
    
    @pytest.fixture
    def sample_entry(self, tmp_path):
        """Sample registry entry for testing"""
        manifest = AppManifest(
            name="test-app",
            type=AppType.SERVICE,
            description="Test application",
            version="1.0.0",
            author="Test Author",
            main_file="app.py"
        )
        
        return AppRegistryEntry(
            app_id="test-app-1",
            name="test-app",
            type=AppType.SERVICE,
            description="Test application",
            version="1.0.0",
            status=AppStatus.DISCOVERED,
            path=tmp_path,
            manifest=manifest
        )
    
    def test_registry_initialization(self, app_registry):
        """Test registry initialization"""
        assert len(app_registry.apps) == 0
        assert app_registry.registry_dir.exists()
    
    def test_register_app(self, app_registry, sample_entry):
        """Test app registration"""
        result = app_registry.register_app(sample_entry)
        
        assert result is True
        assert sample_entry.app_id in app_registry.apps
        assert app_registry.apps[sample_entry.app_id] == sample_entry
    
    def test_update_app(self, app_registry, sample_entry):
        """Test app update"""
        # Register app first
        app_registry.register_app(sample_entry)
        
        # Update app
        result = app_registry.update_app(sample_entry.app_id, status=AppStatus.READY)
        
        assert result is True
        assert app_registry.apps[sample_entry.app_id].status == AppStatus.READY
    
    def test_update_nonexistent_app(self, app_registry):
        """Test updating non-existent app"""
        result = app_registry.update_app("non-existent", status=AppStatus.READY)
        assert result is False
    
    def test_unregister_app(self, app_registry, sample_entry):
        """Test app unregistration"""
        # Register app first
        app_registry.register_app(sample_entry)
        assert sample_entry.app_id in app_registry.apps
        
        # Unregister app
        result = app_registry.unregister_app(sample_entry.app_id)
        
        assert result is True
        assert sample_entry.app_id not in app_registry.apps
    
    def test_get_app(self, app_registry, sample_entry):
        """Test getting app by ID"""
        # Non-existent app
        assert app_registry.get_app("non-existent") is None
        
        # Register and get app
        app_registry.register_app(sample_entry)
        retrieved = app_registry.get_app(sample_entry.app_id)
        
        assert retrieved == sample_entry
    
    def test_get_apps_by_type(self, app_registry, tmp_path):
        """Test getting apps by type"""
        # Create service app
        service_manifest = AppManifest(
            name="service-app", type=AppType.SERVICE, description="Service", 
            version="1.0.0", author="Service Author", main_file="app.py"
        )
        service_entry = AppRegistryEntry(
            app_id="service-1", name="service-app", type=AppType.SERVICE,
            description="Service", version="1.0.0", status=AppStatus.DISCOVERED,
            path=tmp_path, manifest=service_manifest
        )
        
        # Create Streamlit app
        streamlit_manifest = AppManifest(
            name="streamlit-app", type=AppType.STREAMLIT, description="Streamlit", 
            version="1.0.0", author="Streamlit Author", main_file="app.py"
        )
        streamlit_entry = AppRegistryEntry(
            app_id="streamlit-1", name="streamlit-app", type=AppType.STREAMLIT,
            description="Streamlit", version="1.0.0", status=AppStatus.DISCOVERED,
            path=tmp_path, manifest=streamlit_manifest
        )
        
        # Register both
        app_registry.register_app(service_entry)
        app_registry.register_app(streamlit_entry)
        
        # Test filtering by type
        service_apps = app_registry.get_apps_by_type(AppType.SERVICE)
        streamlit_apps = app_registry.get_apps_by_type(AppType.STREAMLIT)
        
        assert len(service_apps) == 1
        assert len(streamlit_apps) == 1
        assert service_apps[0].app_id == "service-1"
        assert streamlit_apps[0].app_id == "streamlit-1"
    
    def test_get_apps_by_status(self, app_registry, sample_entry):
        """Test getting apps by status"""
        app_registry.register_app(sample_entry)
        
        # Test filtering by status
        discovered_apps = app_registry.get_apps_by_status(AppStatus.DISCOVERED)
        ready_apps = app_registry.get_apps_by_status(AppStatus.READY)
        
        assert len(discovered_apps) == 1
        assert len(ready_apps) == 0
        assert discovered_apps[0].app_id == sample_entry.app_id
    
    def test_persistence_save_and_load(self, mock_config_manager, temp_config_dir, tmp_path):
        """Test registry persistence"""
        # Create first registry and add app
        registry1 = AppRegistry(mock_config_manager)
        
        manifest = AppManifest(
            name="test-app", type=AppType.SERVICE, description="Test",
            version="1.0.0", author="Test Author", main_file="app.py"
        )
        entry = AppRegistryEntry(
            app_id="test-1", name="test-app", type=AppType.SERVICE,
            description="Test", version="1.0.0", status=AppStatus.DISCOVERED,
            path=tmp_path, manifest=manifest
        )
        
        registry1.register_app(entry)
        
        # Create second registry (should load from disk)
        registry2 = AppRegistry(mock_config_manager)
        
        assert len(registry2.apps) == 1
        assert "test-1" in registry2.apps
        assert registry2.apps["test-1"].name == "test-app"


class TestAppManager:
    """Test cases for AppManager"""
    
    @pytest.fixture
    def temp_dirs(self):
        """Create temporary directories for testing"""
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            config_dir = temp_path / "config"
            apps_dir = temp_path / "apps"
            
            config_dir.mkdir()
            apps_dir.mkdir()
            
            yield {
                'base': temp_path,
                'config': config_dir,
                'apps': apps_dir
            }
    
    @pytest.fixture
    def mock_config_manager(self, temp_dirs):
        """Mock ConfigManager for testing"""
        mock_config = Mock()
        mock_config.process_manager.port_range.start = 8100
        mock_config.process_manager.port_range.end = 8105
        
        mock_config_manager = Mock(spec=ConfigManager)
        mock_config_manager.config = mock_config
        mock_config_manager.get_data_dir.return_value = temp_dirs['config']
        return mock_config_manager
    
    @pytest.fixture
    def mock_port_manager(self):
        """Mock PortManager for testing"""
        mock_port_manager = Mock(spec=PortManager)
        mock_port_manager.allocate_port.return_value = 8100
        return mock_port_manager
    
    @pytest.fixture
    def app_manager(self, mock_config_manager, mock_port_manager, temp_dirs):
        """Create AppManager instance for testing"""
        with patch('pathlib.Path.cwd', return_value=temp_dirs['base']):
            return AppManager(mock_config_manager, mock_port_manager)
    
    def test_app_manager_initialization(self, app_manager, temp_dirs):
        """Test AppManager initialization"""
        assert app_manager.apps_dir == temp_dirs['base'] / "apps"
        assert app_manager.apps_dir.exists()
        assert isinstance(app_manager.registry, AppRegistry)
    
    def test_discover_apps_no_apps(self, app_manager):
        """Test app discovery with no apps"""
        count = app_manager.discover_apps()
        assert count == 0
    
    def test_discover_apps_with_valid_app(self, app_manager, temp_dirs):
        """Test discovering valid app"""
        # Create test app directory with manifest
        app_dir = temp_dirs['apps'] / "test-service"
        app_dir.mkdir()
        
        # Create manifest file
        manifest_data = {
            "name": "test-service",
            "type": "service",
            "description": "Test service application",
            "version": "1.0.0",
            "author": "Test Author",
            "main_file": "app.py"
        }
        
        manifest_file = app_dir / "homehelper.json"
        with open(manifest_file, 'w') as f:
            json.dump(manifest_data, f)
        
        # Create main file
        main_file = app_dir / "app.py"
        main_file.write_text("# Test main file")
        
        # Discover apps
        count = app_manager.discover_apps()
        
        assert count == 1
        apps = app_manager.registry.get_all_apps()
        assert len(apps) == 1
        assert apps[0].name == "test-service"
        assert apps[0].type == AppType.SERVICE
    
    def test_discover_apps_invalid_manifest(self, app_manager, temp_dirs):
        """Test discovering app with invalid manifest"""
        # Create test app directory with invalid manifest
        app_dir = temp_dirs['apps'] / "invalid-app"
        app_dir.mkdir()
        
        # Create invalid manifest (missing required fields)
        manifest_data = {
            "name": "invalid-app"
            # Missing type, description, version, author, main_file
        }
        
        manifest_file = app_dir / "homehelper.json"
        with open(manifest_file, 'w') as f:
            json.dump(manifest_data, f)
        
        # Discover apps
        count = app_manager.discover_apps()
        
        assert count == 0
        assert len(app_manager.registry.get_all_apps()) == 0
    
    def test_discover_apps_missing_main_file(self, app_manager, temp_dirs):
        """Test discovering app with missing main file"""
        # Create test app directory
        app_dir = temp_dirs['apps'] / "missing-main"
        app_dir.mkdir()
        
        # Create manifest with non-existent main file
        manifest_data = {
            "name": "missing-main",
            "type": "service",
            "description": "App with missing main file",
            "version": "1.0.0",
            "author": "Test Author",
            "main_file": "nonexistent.py"
        }
        
        manifest_file = app_dir / "homehelper.json"
        with open(manifest_file, 'w') as f:
            json.dump(manifest_data, f)
        
        # Discover apps
        count = app_manager.discover_apps()
        
        assert count == 0
        assert len(app_manager.registry.get_all_apps()) == 0
    
    @patch('subprocess.run')
    def test_install_app_dependencies_success(self, mock_subprocess, app_manager, temp_dirs):
        """Test successful dependency installation"""
        # Create test app
        app_dir = temp_dirs['apps'] / "test-app"
        app_dir.mkdir()
        
        # Create manifest and files
        manifest_data = {
            "name": "test-app",
            "type": "service",
            "description": "Test app",
            "version": "1.0.0",
            "author": "Test Author",
            "main_file": "app.py",
            "requirements": "requirements.txt"
        }
        
        (app_dir / "homehelper.json").write_text(json.dumps(manifest_data))
        (app_dir / "main.py").write_text("# Main file")
        (app_dir / "requirements.txt").write_text("requests==2.28.0")
{{ ... }}
        # Discover app
        app_manager.discover_apps()
        apps = app_manager.registry.get_all_apps()
        app_id = apps[0].app_id
        
        # Mock successful subprocess
        mock_subprocess.return_value.returncode = 0
        mock_subprocess.return_value.stderr = ""
        
        # Install dependencies
        result = app_manager.install_app_dependencies(app_id)
        
        assert result is True
        app = app_manager.registry.get_app(app_id)
        assert app.status == AppStatus.READY
    
    @patch('subprocess.run')
    def test_install_app_dependencies_failure(self, mock_subprocess, app_manager, temp_dirs):
        """Test failed dependency installation"""
        # Create test app (similar setup as success test)
        app_dir = temp_dirs['apps'] / "test-app"
        app_dir.mkdir()
        
        manifest_data = {
            "name": "test-app",
            "type": "service",
            "description": "Test app", 
            "version": "1.0.0",
            "author": "Test Author",
            "main_file": "app.py"
        }
        
        (app_dir / "homehelper.json").write_text(json.dumps(manifest_data))
        (app_dir / "main.py").write_text("# Main file")
        (app_dir / "requirements.txt").write_text("nonexistent-package==999.999.999")
        
        # Discover app
        app_manager.discover_apps()
        apps = app_manager.registry.get_all_apps()
        app_id = apps[0].app_id
        
        # Mock failed subprocess
        mock_subprocess.return_value.returncode = 1
        mock_subprocess.return_value.stderr = "Package not found"
        
        # Install dependencies
        result = app_manager.install_app_dependencies(app_id)
        
        assert result is False
        app = app_manager.registry.get_app(app_id)
        assert app.status == AppStatus.ERROR
        assert "Package not found" in app.runtime_info.error_message
    
    def test_prepare_app_service_success(self, app_manager, temp_dirs, mock_port_manager):
        """Test successful service app preparation"""
        # Create test service app
        app_dir = temp_dirs['apps'] / "test-service"
        app_dir.mkdir()
        
        manifest_data = {
            "name": "test-service",
            "type": "service",
            "description": "Test service",
            "version": "1.0.0", 
            "author": "Test Author",
            "main_file": "app.py"
        }
        
        (app_dir / "homehelper.json").write_text(json.dumps(manifest_data))
        (app_dir / "main.py").write_text("# Main file")
        
        # Discover app
        app_manager.discover_apps()
        apps = app_manager.registry.get_all_apps()
        app_id = apps[0].app_id
        
        with patch.object(app_manager, 'install_app_dependencies', return_value=True), \
             patch.object(app_manager, 'run_setup_commands', return_value=True):
            
            # Prepare app
            result = app_manager.prepare_app(app_id)
            
            assert result is True
            app = app_manager.registry.get_app(app_id)
            assert app.status == AppStatus.READY
            assert app.runtime_info.assigned_port == 8100  # From mock
            
            # Verify port allocation was called
            mock_port_manager.allocate_port.assert_called_once_with(app_id, "service")
    
    def test_get_app_statistics(self, app_manager, temp_dirs):
        """Test app statistics generation"""
        # Initially no apps
        stats = app_manager.get_app_statistics()
        assert stats['total_apps'] == 0
        
        # Create and discover some apps
        for i, app_type in enumerate(['service', 'streamlit']):
            app_dir = temp_dirs['apps'] / f"test-{app_type}"
            app_dir.mkdir()
            
            manifest_data = {
                "name": f"test-{app_type}",
                "type": app_type,
                "description": f"Test {app_type} app",
                "version": "1.0.0",
                "author": "Test Author",
                "main_file": "app.py"
            }
            
            (app_dir / "homehelper.json").write_text(json.dumps(manifest_data))
            (app_dir / "app.py").write_text("# Main")
        
        app_manager.discover_apps()
        
        # Get updated stats
        stats = app_manager.get_app_statistics()
        assert stats['total_apps'] == 2
        assert stats['type_breakdown']['service'] == 1
        assert stats['type_breakdown']['streamlit'] == 1
        assert stats['status_breakdown']['discovered'] == 2
