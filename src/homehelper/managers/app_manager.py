"""
App Manager for HomeHelper

Handles application discovery, manifest parsing, and registry management.
Provides the core functionality for managing HomeHelper applications.
"""

import json
import logging
import subprocess
import sys
from pathlib import Path
from typing import Dict, List, Optional, Set
from dataclasses import dataclass, asdict, field
from datetime import datetime
from enum import Enum

from pydantic import BaseModel, Field, ValidationError

from ..core.config import ConfigManager
from .port_manager import PortManager


class AppType(str, Enum):
    """Application types supported by HomeHelper"""
    SERVICE = "service"
    STREAMLIT = "streamlit"


class AppStatus(str, Enum):
    """Application status values"""
    DISCOVERED = "discovered"
    INSTALLING = "installing"
    READY = "ready"
    STARTING = "starting"
    RUNNING = "running"
    STOPPING = "stopping"
    STOPPED = "stopped"
    ERROR = "error"


class AppConfig(BaseModel):
    """Application configuration options"""
    has_UI: bool = False
    redis_required: bool = False
    logs_dir: bool = False
    data_dir: bool = False
    auto_start: bool = False
    restart_policy: str = Field(default="always", pattern=r'^(always|on-failure|never)$')


class AppInstall(BaseModel):
    """Application installation configuration"""
    setup_commands: Optional[List[str]] = None


class AppManifest(BaseModel):
    """Application manifest schema (homehelper.json)"""
    name: str = Field(..., min_length=1, max_length=50)
    type: AppType
    description: str = Field(..., min_length=1, max_length=200)
    version: str = Field(..., pattern=r'^\d+\.\d+\.\d+$')
    author: str = Field(..., min_length=1, max_length=100)
    main_file: str = Field(..., min_length=1)
    config: Optional[AppConfig] = Field(default_factory=AppConfig)
    install: Optional[AppInstall] = Field(default_factory=AppInstall)
    
    class Config:
        use_enum_values = True


@dataclass
class AppRuntimeInfo:
    """Runtime information for an application"""
    assigned_port: Optional[int] = None
    process_id: Optional[str] = None
    service_name: Optional[str] = None
    started_at: Optional[datetime] = None
    last_health_check: Optional[datetime] = None
    resource_usage: Optional[Dict[str, float]] = None
    error_message: Optional[str] = None
    
    def to_dict(self) -> dict:
        """Convert to dictionary for JSON serialization"""
        data = asdict(self)
        if self.started_at:
            data['started_at'] = self.started_at.isoformat()
        if self.last_health_check:
            data['last_health_check'] = self.last_health_check.isoformat()
        return data
    
    @classmethod
    def from_dict(cls, data: dict) -> 'AppRuntimeInfo':
        """Create from dictionary"""
        if 'started_at' in data and data['started_at']:
            data['started_at'] = datetime.fromisoformat(data['started_at'])
        if 'last_health_check' in data and data['last_health_check']:
            data['last_health_check'] = datetime.fromisoformat(data['last_health_check'])
        return cls(**data)


@dataclass
class AppRegistryEntry:
    """Registry entry for a discovered application"""
    app_id: str
    name: str
    type: AppType
    description: str
    version: str
    status: AppStatus
    path: Path
    manifest: AppManifest
    runtime_info: AppRuntimeInfo = field(default_factory=AppRuntimeInfo)
    discovered_at: datetime = field(default_factory=datetime.now)
    last_updated: datetime = field(default_factory=datetime.now)
    
    def to_dict(self) -> dict:
        """Convert to dictionary for JSON serialization"""
        data = asdict(self)
        data['path'] = str(self.path)
        data['manifest'] = self.manifest.model_dump()
        data['runtime_info'] = self.runtime_info.to_dict()
        data['discovered_at'] = self.discovered_at.isoformat()
        data['last_updated'] = self.last_updated.isoformat()
        data['type'] = self.type if isinstance(self.type, str) else self.type.value
        data['status'] = self.status if isinstance(self.status, str) else self.status.value
        return data
    
    @classmethod
    def from_dict(cls, data: dict) -> 'AppRegistryEntry':
        """Create from dictionary"""
        data['path'] = Path(data['path'])
        data['manifest'] = AppManifest(**data['manifest'])
        data['runtime_info'] = AppRuntimeInfo.from_dict(data['runtime_info'])
        data['discovered_at'] = datetime.fromisoformat(data['discovered_at'])
        data['last_updated'] = datetime.fromisoformat(data['last_updated'])
        data['type'] = AppType(data['type'])
        data['status'] = AppStatus(data['status'])
        return cls(**data)


class AppRegistry:
    """In-memory application registry with persistence"""
    
    def __init__(self, config_manager: ConfigManager):
        self.config_manager = config_manager
        self.logger = logging.getLogger("homehelper.app_registry")
        
        # Registry storage
        self.apps: Dict[str, AppRegistryEntry] = {}
        
        # Persistence
        self.registry_dir = Path(config_manager.get_data_dir()) / "registry"
        self.registry_dir.mkdir(parents=True, exist_ok=True)
        self.registry_file = self.registry_dir / "apps.json"
        
        # Load existing registry
        self._load_registry()
    
    def _load_registry(self) -> None:
        """Load app registry from disk"""
        try:
            if self.registry_file.exists():
                with open(self.registry_file, 'r') as f:
                    data = json.load(f)
                
                for app_id, app_data in data.get('apps', {}).items():
                    try:
                        entry = AppRegistryEntry.from_dict(app_data)
                        self.apps[app_id] = entry
                    except Exception as e:
                        self.logger.error(f"Failed to load app {app_id}: {e}")
                
                self.logger.info(f"Loaded {len(self.apps)} apps from registry")
            else:
                self.logger.info("No existing app registry found")
                
        except Exception as e:
            self.logger.error(f"Failed to load app registry: {e}")
            self.apps = {}
    
    def _save_registry(self) -> None:
        """Save app registry to disk"""
        try:
            data = {
                'apps': {app_id: app.to_dict() for app_id, app in self.apps.items()},
                'last_updated': datetime.now().isoformat(),
                'version': '1.0'
            }
            
            # Atomic write
            temp_file = self.registry_file.with_suffix('.tmp')
            with open(temp_file, 'w') as f:
                json.dump(data, f, indent=2)
            
            temp_file.replace(self.registry_file)
            self.logger.debug("App registry saved to disk")
            
        except Exception as e:
            self.logger.error(f"Failed to save app registry: {e}")
    
    def register_app(self, entry: AppRegistryEntry) -> bool:
        """Register a new application"""
        try:
            self.apps[entry.app_id] = entry
            self._save_registry()
            self.logger.info(f"Registered app {entry.app_id} ({entry.name})")
            return True
        except Exception as e:
            self.logger.error(f"Failed to register app {entry.app_id}: {e}")
            return False
    
    def update_app(self, app_id: str, **kwargs) -> bool:
        """Update an existing application"""
        if app_id not in self.apps:
            return False
        
        try:
            entry = self.apps[app_id]
            for key, value in kwargs.items():
                if hasattr(entry, key):
                    setattr(entry, key, value)
            
            entry.last_updated = datetime.now()
            self._save_registry()
            self.logger.debug(f"Updated app {app_id}")
            return True
        except Exception as e:
            self.logger.error(f"Failed to update app {app_id}: {e}")
            return False
    
    def unregister_app(self, app_id: str) -> bool:
        """Unregister an application"""
        if app_id in self.apps:
            del self.apps[app_id]
            self._save_registry()
            self.logger.info(f"Unregistered app {app_id}")
            return True
        return False
    
    def get_app(self, app_id: str) -> Optional[AppRegistryEntry]:
        """Get an application by ID"""
        return self.apps.get(app_id)
    
    def get_all_apps(self) -> List[AppRegistryEntry]:
        """Get all registered applications"""
        return list(self.apps.values())
    
    def get_apps_by_type(self, app_type: AppType) -> List[AppRegistryEntry]:
        """Get applications by type"""
        return [app for app in self.apps.values() if app.type == app_type]
    
    def get_apps_by_status(self, status: AppStatus) -> List[AppRegistryEntry]:
        """Get applications by status"""
        return [app for app in self.apps.values() if app.status == status]


class AppManager:
    """Main application manager for discovery and lifecycle management"""
    
    def __init__(self, config_manager: ConfigManager, port_manager: PortManager):
        self.config_manager = config_manager
        self.port_manager = port_manager
        self.registry = AppRegistry(config_manager)
        self.logger = logging.getLogger("homehelper.app_manager")
        
        # Apps directory
        self.apps_dir = Path.cwd() / "apps"
        self.apps_dir.mkdir(exist_ok=True)
    
    def discover_apps(self) -> int:
        """
        Discover applications in the apps directory
        
        Returns:
            Number of apps discovered
        """
        discovered_count = 0
        
        try:
            self.logger.info(f"Scanning for apps in {self.apps_dir}")
            
            # Scan for app directories
            for app_path in self.apps_dir.iterdir():
                if not app_path.is_dir():
                    continue
                
                manifest_file = app_path / "homehelper.json"
                if not manifest_file.exists():
                    self.logger.debug(f"No manifest found in {app_path.name}")
                    continue
                
                try:
                    # Parse manifest
                    manifest = self._parse_manifest(manifest_file)
                    if not manifest:
                        continue
                    
                    # Generate app ID
                    app_id = self._generate_app_id(manifest.name, app_path.name)
                    
                    # Check if app is already registered
                    existing_app = self.registry.get_app(app_id)
                    if existing_app:
                        # Update if path or version changed
                        if existing_app.path != app_path or existing_app.version != manifest.version:
                            self._update_existing_app(existing_app, manifest, app_path)
                        continue
                    
                    # Create new registry entry
                    entry = AppRegistryEntry(
                        app_id=app_id,
                        name=manifest.name,
                        type=manifest.type,
                        description=manifest.description,
                        version=manifest.version,
                        status=AppStatus.DISCOVERED,
                        path=app_path,
                        manifest=manifest
                    )
                    
                    # Register the app
                    if self.registry.register_app(entry):
                        discovered_count += 1
                        self.logger.info(f"Discovered new app: {manifest.name} ({app_id})")
                    
                except Exception as e:
                    self.logger.error(f"Failed to process app in {app_path}: {e}")
                    continue
            
            self.logger.info(f"Discovery complete: {discovered_count} new apps found")
            return discovered_count
            
        except Exception as e:
            self.logger.error(f"App discovery failed: {e}")
            return 0
    
    def _parse_manifest(self, manifest_file: Path) -> Optional[AppManifest]:
        """Parse and validate application manifest"""
        try:
            with open(manifest_file, 'r') as f:
                data = json.load(f)
            
            # Validate with Pydantic
            manifest = AppManifest(**data)
            
            # Additional validation
            app_path = manifest_file.parent
            main_file = app_path / manifest.main_file
            if not main_file.exists():
                self.logger.error(f"Main file {manifest.main_file} not found in {app_path}")
                return None
            
            # Check for requirements.txt (default if not specified)
            req_file = app_path / "requirements.txt"
            if not req_file.exists():
                self.logger.warning(f"Requirements file requirements.txt not found in {app_path}")
            
            return manifest
            
        except ValidationError as e:
            self.logger.error(f"Invalid manifest in {manifest_file}: {e}")
            return None
        except Exception as e:
            self.logger.error(f"Failed to parse manifest {manifest_file}: {e}")
            return None
    
    def _generate_app_id(self, app_name: str, dir_name: str) -> str:
        """Generate unique app ID from name and directory"""
        # Use directory name as base, fallback to app name
        base_id = dir_name.lower().replace(' ', '-').replace('_', '-')
        
        # Ensure uniqueness
        app_id = base_id
        counter = 1
        while self.registry.get_app(app_id):
            app_id = f"{base_id}-{counter}"
            counter += 1
        
        return app_id
    
    def _update_existing_app(self, existing_app: AppRegistryEntry, manifest: AppManifest, app_path: Path) -> None:
        """Update an existing app with new manifest or path"""
        self.registry.update_app(
            existing_app.app_id,
            manifest=manifest,
            path=app_path,
            version=manifest.version,
            description=manifest.description,
            status=AppStatus.DISCOVERED
        )
        self.logger.info(f"Updated existing app: {existing_app.app_id}")
    
    def install_app_dependencies(self, app_id: str) -> bool:
        """
        Install Python dependencies for an application
        
        Args:
            app_id: Application identifier
            
        Returns:
            True if installation successful
        """
        app = self.registry.get_app(app_id)
        if not app:
            self.logger.error(f"App {app_id} not found")
            return False
        
        if not app.manifest.requirements:
            self.logger.info(f"No requirements file specified for app {app_id}")
            return True
        
        requirements_file = app.path / app.manifest.requirements
        if not requirements_file.exists():
            self.logger.error(f"Requirements file not found: {requirements_file}")
            return False
        
        try:
            self.registry.update_app(app_id, status=AppStatus.INSTALLING)
            self.logger.info(f"Installing dependencies for app {app_id}")
            
            # Install dependencies using pip
            cmd = [
                sys.executable, "-m", "pip", "install", 
                "-r", str(requirements_file),
                "--user"  # Install to user directory
            ]
            
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                cwd=app.path,
                timeout=300  # 5 minute timeout
            )
            
            if result.returncode == 0:
                self.registry.update_app(app_id, status=AppStatus.READY)
                self.logger.info(f"Dependencies installed successfully for app {app_id}")
                return True
            else:
                error_msg = f"Dependency installation failed: {result.stderr}"
                self.registry.update_app(app_id, status=AppStatus.ERROR)
                self.registry.apps[app_id].runtime_info.error_message = error_msg
                self.logger.error(f"Failed to install dependencies for app {app_id}: {error_msg}")
                return False
                
        except subprocess.TimeoutExpired:
            error_msg = "Dependency installation timed out"
            self.registry.update_app(app_id, status=AppStatus.ERROR)
            self.registry.apps[app_id].runtime_info.error_message = error_msg
            self.logger.error(f"Dependency installation timed out for app {app_id}")
            return False
        except Exception as e:
            error_msg = f"Dependency installation error: {str(e)}"
            self.registry.update_app(app_id, status=AppStatus.ERROR)
            self.registry.apps[app_id].runtime_info.error_message = error_msg
            self.logger.error(f"Failed to install dependencies for app {app_id}: {e}")
            return False
    
    def run_setup_commands(self, app_id: str) -> bool:
        """
        Run setup commands for an application
        
        Args:
            app_id: Application identifier
            
        Returns:
            True if setup successful
        """
        app = self.registry.get_app(app_id)
        if not app or not app.manifest.install or not app.manifest.install.setup_commands:
            return True
        
        try:
            self.logger.info(f"Running setup commands for app {app_id}")
            
            for command in app.manifest.install.setup_commands:
                self.logger.debug(f"Running setup command: {command}")
                
                result = subprocess.run(
                    command,
                    shell=True,
                    capture_output=True,
                    text=True,
                    cwd=app.path,
                    timeout=60  # 1 minute timeout per command
                )
                
                if result.returncode != 0:
                    error_msg = f"Setup command failed: {command}\n{result.stderr}"
                    self.registry.apps[app_id].runtime_info.error_message = error_msg
                    self.logger.error(f"Setup command failed for app {app_id}: {error_msg}")
                    return False
            
            self.logger.info(f"Setup commands completed successfully for app {app_id}")
            return True
            
        except Exception as e:
            error_msg = f"Setup command error: {str(e)}"
            self.registry.apps[app_id].runtime_info.error_message = error_msg
            self.logger.error(f"Failed to run setup commands for app {app_id}: {e}")
            return False
    
    def prepare_app(self, app_id: str) -> bool:
        """
        Prepare an application for running (install dependencies, run setup)
        
        Args:
            app_id: Application identifier
            
        Returns:
            True if preparation successful
        """
        app = self.registry.get_app(app_id)
        if not app:
            return False
        
        if app.status == AppStatus.READY:
            return True
        
        # Install dependencies
        if not self.install_app_dependencies(app_id):
            return False
        
        # Run setup commands
        if not self.run_setup_commands(app_id):
            self.registry.update_app(app_id, status=AppStatus.ERROR)
            return False
        
        # Allocate port for service apps
        if app.type == AppType.SERVICE:
            port = self.port_manager.allocate_port(app_id, app.type)
            if port:
                app.runtime_info.assigned_port = port
                self.registry.update_app(app_id, runtime_info=app.runtime_info)
            else:
                error_msg = "Failed to allocate port"
                app.runtime_info.error_message = error_msg
                self.registry.update_app(app_id, status=AppStatus.ERROR, runtime_info=app.runtime_info)
                return False
        
        self.registry.update_app(app_id, status=AppStatus.READY)
        return True
    
    def get_app_statistics(self) -> dict:
        """Get application statistics"""
        all_apps = self.registry.get_all_apps()
        
        status_counts = {}
        type_counts = {}
        
        for app in all_apps:
            status_counts[app.status] = status_counts.get(app.status, 0) + 1
            type_counts[app.type] = type_counts.get(app.type, 0) + 1
        
        return {
            'total_apps': len(all_apps),
            'status_breakdown': status_counts,
            'type_breakdown': type_counts,
            'ready_apps': len(self.registry.get_apps_by_status(AppStatus.READY)),
            'running_apps': len(self.registry.get_apps_by_status(AppStatus.RUNNING)),
            'error_apps': len(self.registry.get_apps_by_status(AppStatus.ERROR))
        }
