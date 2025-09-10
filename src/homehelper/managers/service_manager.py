"""
Service Manager for HomeHelper

Handles systemd service integration, lifecycle management, and health monitoring.
Provides systemd service template generation and process monitoring capabilities.
"""

import json
import logging
import subprocess
import tempfile
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass, asdict
from datetime import datetime, timedelta
from enum import Enum

from ..core.config import ConfigManager
from .app_manager import AppManager, AppType, AppStatus


class ServiceStatus(str, Enum):
    """Service status values from systemd"""
    ACTIVE = "active"
    INACTIVE = "inactive"
    FAILED = "failed"
    ACTIVATING = "activating"
    DEACTIVATING = "deactivating"
    UNKNOWN = "unknown"


class ServiceState(str, Enum):
    """Service state values from systemd"""
    RUNNING = "running"
    EXITED = "exited"
    FAILED = "failed"
    DEAD = "dead"
    UNKNOWN = "unknown"


@dataclass
class ServiceInfo:
    """Information about a systemd service"""
    service_name: str
    status: ServiceStatus
    state: ServiceState
    pid: Optional[int] = None
    memory_usage: Optional[int] = None  # in bytes
    cpu_percent: Optional[float] = None
    uptime: Optional[timedelta] = None
    restart_count: int = 0
    last_restart: Optional[datetime] = None
    error_message: Optional[str] = None
    
    def to_dict(self) -> dict:
        """Convert to dictionary for JSON serialization"""
        data = asdict(self)
        if self.uptime:
            data['uptime'] = str(self.uptime)
        if self.last_restart:
            data['last_restart'] = self.last_restart.isoformat()
        return data
    
    @classmethod
    def from_dict(cls, data: dict) -> 'ServiceInfo':
        """Create from dictionary"""
        if 'uptime' in data and data['uptime']:
            # Parse uptime string back to timedelta
            parts = data['uptime'].split(':')
            if len(parts) == 3:
                hours, minutes, seconds = map(float, parts)
                data['uptime'] = timedelta(hours=hours, minutes=minutes, seconds=seconds)
        if 'last_restart' in data and data['last_restart']:
            data['last_restart'] = datetime.fromisoformat(data['last_restart'])
        return cls(**data)


class ServiceManager:
    """Main service manager for systemd integration"""
    
    def __init__(self, config_manager: ConfigManager, app_manager: AppManager):
        self.config_manager = config_manager
        self.app_manager = app_manager
        self.logger = logging.getLogger("homehelper.service_manager")
        
        # Service tracking
        self.services: Dict[str, ServiceInfo] = {}
        
        # systemd paths
        self.systemd_user_dir = Path.home() / ".config" / "systemd" / "user"
        self.systemd_user_dir.mkdir(parents=True, exist_ok=True)
        
        # Service name prefix
        self.service_prefix = "homehelper-"
    
    def generate_service_template(self, app_id: str) -> Optional[str]:
        """
        Generate systemd service template for an application
        
        Args:
            app_id: Application identifier
            
        Returns:
            Service template content or None if failed
        """
        app = self.app_manager.registry.get_app(app_id)
        if not app or app.type != AppType.SERVICE:
            self.logger.error(f"App {app_id} not found or not a service app")
            return None
        
        if not app.runtime_info.assigned_port:
            self.logger.error(f"App {app_id} has no assigned port")
            return None
        
        # Build command arguments
        cmd_args = [
            "python", app.manifest.main_file,
            "--port", str(app.runtime_info.assigned_port)
        ]
        
        # Add optional arguments based on config
        if app.manifest.config and app.manifest.config.data_dir:
            data_dir = Path(self.config_manager.get_data_dir()) / app_id
            data_dir.mkdir(parents=True, exist_ok=True)
            cmd_args.extend(["--data-dir", str(data_dir)])
        
        if app.manifest.config and app.manifest.config.logs_dir:
            logs_dir = Path(self.config_manager.get_logs_dir()) / app_id
            logs_dir.mkdir(parents=True, exist_ok=True)
            cmd_args.extend(["--logs-dir", str(logs_dir)])
        
        # Environment variables
        env_vars = []
        if app.manifest.config and app.manifest.config.redis_required:
            redis_config = self.config_manager.config.redis
            env_vars.append(f"REDIS_HOST={redis_config.host}")
            env_vars.append(f"REDIS_PORT={redis_config.port}")
            if redis_config.password:
                env_vars.append(f"REDIS_PASSWORD={redis_config.password}")
        
        # Add custom environment variables from manifest
        if hasattr(app.manifest, 'environment') and app.manifest.environment:
            for key, value in app.manifest.environment.items():
                env_vars.append(f"{key}={value}")
        
        # Restart policy
        restart_policy = "always"
        if app.manifest.config and app.manifest.config.restart_policy:
            restart_policy = app.manifest.config.restart_policy
        
        # Generate service template
        service_template = f"""[Unit]
Description=HomeHelper Service - {app.manifest.name}
After=network.target
Wants=network.target

[Service]
Type=simple
User={Path.home().owner()}
WorkingDirectory={app.path}
ExecStart={' '.join(cmd_args)}
Restart={restart_policy}
RestartSec=5
StandardOutput=journal
StandardError=journal
SyslogIdentifier={self.service_prefix}{app_id}
"""
        
        # Add environment variables
        if env_vars:
            for env_var in env_vars:
                service_template += f"Environment={env_var}\n"
        
        service_template += "\n[Install]\nWantedBy=default.target\n"
        
        return service_template
    
    def create_service_file(self, app_id: str) -> bool:
        """
        Create systemd service file for an application
        
        Args:
            app_id: Application identifier
            
        Returns:
            True if service file created successfully
        """
        try:
            template = self.generate_service_template(app_id)
            if not template:
                return False
            
            service_name = f"{self.service_prefix}{app_id}.service"
            service_file = self.systemd_user_dir / service_name
            
            # Write service file
            with open(service_file, 'w') as f:
                f.write(template)
            
            # Reload systemd daemon
            result = subprocess.run(
                ["systemctl", "--user", "daemon-reload"],
                capture_output=True,
                text=True
            )
            
            if result.returncode != 0:
                self.logger.error(f"Failed to reload systemd daemon: {result.stderr}")
                return False
            
            self.logger.info(f"Created service file for app {app_id}: {service_file}")
            return True
            
        except Exception as e:
            self.logger.error(f"Failed to create service file for app {app_id}: {e}")
            return False
    
    def start_service(self, app_id: str) -> bool:
        """
        Start a systemd service for an application
        
        Args:
            app_id: Application identifier
            
        Returns:
            True if service started successfully
        """
        try:
            service_name = f"{self.service_prefix}{app_id}.service"
            
            result = subprocess.run(
                ["systemctl", "--user", "start", service_name],
                capture_output=True,
                text=True
            )
            
            if result.returncode == 0:
                self.logger.info(f"Started service for app {app_id}")
                # Update app status
                self.app_manager.registry.update_app(app_id, status=AppStatus.RUNNING)
                return True
            else:
                error_msg = f"Failed to start service: {result.stderr}"
                self.logger.error(f"Failed to start service for app {app_id}: {error_msg}")
                # Update app with error
                app = self.app_manager.registry.get_app(app_id)
                if app:
                    app.runtime_info.error_message = error_msg
                    self.app_manager.registry.update_app(
                        app_id, 
                        status=AppStatus.ERROR,
                        runtime_info=app.runtime_info
                    )
                return False
                
        except Exception as e:
            error_msg = f"Exception starting service: {str(e)}"
            self.logger.error(f"Failed to start service for app {app_id}: {error_msg}")
            # Update app with error
            app = self.app_manager.registry.get_app(app_id)
            if app:
                app.runtime_info.error_message = error_msg
                self.app_manager.registry.update_app(
                    app_id,
                    status=AppStatus.ERROR,
                    runtime_info=app.runtime_info
                )
            return False
    
    def stop_service(self, app_id: str) -> bool:
        """
        Stop a systemd service for an application
        
        Args:
            app_id: Application identifier
            
        Returns:
            True if service stopped successfully
        """
        try:
            service_name = f"{self.service_prefix}{app_id}.service"
            
            result = subprocess.run(
                ["systemctl", "--user", "stop", service_name],
                capture_output=True,
                text=True
            )
            
            if result.returncode == 0:
                self.logger.info(f"Stopped service for app {app_id}")
                # Update app status
                self.app_manager.registry.update_app(app_id, status=AppStatus.STOPPED)
                return True
            else:
                self.logger.error(f"Failed to stop service for app {app_id}: {result.stderr}")
                return False
                
        except Exception as e:
            self.logger.error(f"Failed to stop service for app {app_id}: {e}")
            return False
    
    def restart_service(self, app_id: str) -> bool:
        """
        Restart a systemd service for an application
        
        Args:
            app_id: Application identifier
            
        Returns:
            True if service restarted successfully
        """
        try:
            service_name = f"{self.service_prefix}{app_id}.service"
            
            result = subprocess.run(
                ["systemctl", "--user", "restart", service_name],
                capture_output=True,
                text=True
            )
            
            if result.returncode == 0:
                self.logger.info(f"Restarted service for app {app_id}")
                # Update restart tracking
                if app_id in self.services:
                    self.services[app_id].restart_count += 1
                    self.services[app_id].last_restart = datetime.now()
                # Update app status
                self.app_manager.registry.update_app(app_id, status=AppStatus.RUNNING)
                return True
            else:
                self.logger.error(f"Failed to restart service for app {app_id}: {result.stderr}")
                return False
                
        except Exception as e:
            self.logger.error(f"Failed to restart service for app {app_id}: {e}")
            return False
    
    def get_service_status(self, app_id: str) -> Optional[ServiceInfo]:
        """
        Get detailed status information for a service
        
        Args:
            app_id: Application identifier
            
        Returns:
            ServiceInfo object or None if failed
        """
        try:
            service_name = f"{self.service_prefix}{app_id}.service"
            
            # Get basic status
            result = subprocess.run(
                ["systemctl", "--user", "show", service_name, 
                 "--property=ActiveState,SubState,MainPID"],
                capture_output=True,
                text=True
            )
            
            if result.returncode != 0:
                return None
            
            # Parse systemctl output
            properties = {}
            for line in result.stdout.strip().split('\n'):
                if '=' in line:
                    key, value = line.split('=', 1)
                    properties[key] = value
            
            # Map systemd states to our enums
            status_map = {
                'active': ServiceStatus.ACTIVE,
                'inactive': ServiceStatus.INACTIVE,
                'failed': ServiceStatus.FAILED,
                'activating': ServiceStatus.ACTIVATING,
                'deactivating': ServiceStatus.DEACTIVATING
            }
            
            state_map = {
                'running': ServiceState.RUNNING,
                'exited': ServiceState.EXITED,
                'failed': ServiceState.FAILED,
                'dead': ServiceState.DEAD
            }
            
            status = status_map.get(properties.get('ActiveState', ''), ServiceStatus.UNKNOWN)
            state = state_map.get(properties.get('SubState', ''), ServiceState.UNKNOWN)
            
            # Get PID if running
            pid = None
            if properties.get('MainPID', '0') != '0':
                pid = int(properties['MainPID'])
            
            service_info = ServiceInfo(
                service_name=service_name,
                status=status,
                state=state,
                pid=pid
            )
            
            # Get additional metrics if service is running
            if pid and status == ServiceStatus.ACTIVE:
                service_info = self._get_process_metrics(service_info, pid)
            
            # Update tracking
            self.services[app_id] = service_info
            
            return service_info
            
        except Exception as e:
            self.logger.error(f"Failed to get service status for app {app_id}: {e}")
            return None
    
    def _get_process_metrics(self, service_info: ServiceInfo, pid: int) -> ServiceInfo:
        """
        Get process metrics for a running service
        
        Args:
            service_info: ServiceInfo object to update
            pid: Process ID
            
        Returns:
            Updated ServiceInfo object
        """
        try:
            # Get memory usage from /proc/pid/status
            status_file = Path(f"/proc/{pid}/status")
            if status_file.exists():
                with open(status_file, 'r') as f:
                    for line in f:
                        if line.startswith('VmRSS:'):
                            # Memory in kB, convert to bytes
                            memory_kb = int(line.split()[1])
                            service_info.memory_usage = memory_kb * 1024
                            break
            
            # Get CPU usage (simplified - would need sampling for accurate measurement)
            stat_file = Path(f"/proc/{pid}/stat")
            if stat_file.exists():
                with open(stat_file, 'r') as f:
                    stat_data = f.read().split()
                    # This is a simplified CPU calculation
                    # In production, you'd want to sample over time
                    utime = int(stat_data[13])  # User time
                    stime = int(stat_data[14])  # System time
                    # For now, just store raw values
                    service_info.cpu_percent = 0.0  # Placeholder
            
            # Get uptime from process start time
            stat_file = Path(f"/proc/{pid}/stat")
            if stat_file.exists():
                with open(stat_file, 'r') as f:
                    stat_data = f.read().split()
                    starttime = int(stat_data[21])  # Process start time in clock ticks
                    # Convert to uptime (simplified)
                    # In production, you'd calculate this properly
                    service_info.uptime = timedelta(seconds=0)  # Placeholder
            
        except Exception as e:
            self.logger.debug(f"Failed to get process metrics for PID {pid}: {e}")
        
        return service_info
    
    def get_service_logs(self, app_id: str, lines: int = 50) -> List[str]:
        """
        Get recent log entries for a service via journalctl
        
        Args:
            app_id: Application identifier
            lines: Number of recent lines to retrieve
            
        Returns:
            List of log lines
        """
        try:
            service_name = f"{self.service_prefix}{app_id}.service"
            
            result = subprocess.run(
                ["journalctl", "--user", "-u", service_name, "-n", str(lines), "--no-pager"],
                capture_output=True,
                text=True
            )
            
            if result.returncode == 0:
                return result.stdout.strip().split('\n') if result.stdout.strip() else []
            else:
                self.logger.error(f"Failed to get logs for app {app_id}: {result.stderr}")
                return []
                
        except Exception as e:
            self.logger.error(f"Failed to get logs for app {app_id}: {e}")
            return []
    
    def enable_service(self, app_id: str) -> bool:
        """
        Enable a service to start automatically
        
        Args:
            app_id: Application identifier
            
        Returns:
            True if service enabled successfully
        """
        try:
            service_name = f"{self.service_prefix}{app_id}.service"
            
            result = subprocess.run(
                ["systemctl", "--user", "enable", service_name],
                capture_output=True,
                text=True
            )
            
            if result.returncode == 0:
                self.logger.info(f"Enabled service for app {app_id}")
                return True
            else:
                self.logger.error(f"Failed to enable service for app {app_id}: {result.stderr}")
                return False
                
        except Exception as e:
            self.logger.error(f"Failed to enable service for app {app_id}: {e}")
            return False
    
    def disable_service(self, app_id: str) -> bool:
        """
        Disable a service from starting automatically
        
        Args:
            app_id: Application identifier
            
        Returns:
            True if service disabled successfully
        """
        try:
            service_name = f"{self.service_prefix}{app_id}.service"
            
            result = subprocess.run(
                ["systemctl", "--user", "disable", service_name],
                capture_output=True,
                text=True
            )
            
            if result.returncode == 0:
                self.logger.info(f"Disabled service for app {app_id}")
                return True
            else:
                self.logger.error(f"Failed to disable service for app {app_id}: {result.stderr}")
                return False
                
        except Exception as e:
            self.logger.error(f"Failed to disable service for app {app_id}: {e}")
            return False
    
    def remove_service(self, app_id: str) -> bool:
        """
        Remove service file and stop service
        
        Args:
            app_id: Application identifier
            
        Returns:
            True if service removed successfully
        """
        try:
            service_name = f"{self.service_prefix}{app_id}.service"
            service_file = self.systemd_user_dir / service_name
            
            # Stop and disable service first
            self.stop_service(app_id)
            self.disable_service(app_id)
            
            # Remove service file
            if service_file.exists():
                service_file.unlink()
                self.logger.info(f"Removed service file for app {app_id}")
            
            # Reload systemd daemon
            subprocess.run(
                ["systemctl", "--user", "daemon-reload"],
                capture_output=True,
                text=True
            )
            
            # Remove from tracking
            if app_id in self.services:
                del self.services[app_id]
            
            return True
            
        except Exception as e:
            self.logger.error(f"Failed to remove service for app {app_id}: {e}")
            return False
    
    def get_all_service_statuses(self) -> Dict[str, ServiceInfo]:
        """
        Get status for all managed services
        
        Returns:
            Dictionary mapping app_id to ServiceInfo
        """
        statuses = {}
        
        # Get all service apps from registry
        service_apps = self.app_manager.registry.get_apps_by_type(AppType.SERVICE)
        
        for app in service_apps:
            if app.status in [AppStatus.READY, AppStatus.RUNNING, AppStatus.STOPPED]:
                status = self.get_service_status(app.app_id)
                if status:
                    statuses[app.app_id] = status
        
        return statuses
    
    def get_service_statistics(self) -> dict:
        """
        Get service management statistics
        
        Returns:
            Dictionary with service statistics
        """
        statuses = self.get_all_service_statuses()
        
        status_counts = {}
        total_memory = 0
        running_services = 0
        
        for service_info in statuses.values():
            status_counts[service_info.status] = status_counts.get(service_info.status, 0) + 1
            
            if service_info.status == ServiceStatus.ACTIVE:
                running_services += 1
                if service_info.memory_usage:
                    total_memory += service_info.memory_usage
        
        return {
            'total_services': len(statuses),
            'running_services': running_services,
            'status_breakdown': status_counts,
            'total_memory_usage': total_memory,
            'average_memory_per_service': total_memory / running_services if running_services > 0 else 0
        }
