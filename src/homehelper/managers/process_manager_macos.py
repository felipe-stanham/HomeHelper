"""
macOS-compatible process manager for HomeHelper service apps.

This manager handles starting/stopping service apps as background processes
on macOS where systemd is not available.
"""
import logging
import subprocess
import signal
import psutil
from pathlib import Path
from typing import Optional, Dict
from datetime import datetime


class MacOSProcessManager:
    """Manages service app processes on macOS"""
    
    def __init__(self, config_manager, app_manager, port_manager):
        self.config_manager = config_manager
        self.app_manager = app_manager
        self.port_manager = port_manager
        self.logger = logging.getLogger("homehelper.process_manager_macos")
        
        # Track running processes: app_id -> process info
        self.processes: Dict[str, dict] = {}
    
    def start_app(self, app_id: str) -> bool:
        """Start a service app as a background process"""
        try:
            app = self.app_manager.registry.get_app(app_id)
            if not app:
                self.logger.error(f"App {app_id} not found")
                return False
            
            if app.type != "service":
                self.logger.error(f"App {app_id} is not a service app")
                return False
            
            # Check if already running
            if app_id in self.processes:
                pid = self.processes[app_id].get('pid')
                if pid and psutil.pid_exists(pid):
                    self.logger.info(f"App {app_id} is already running (PID: {pid})")
                    return True
            
            # Allocate port
            port = self.port_manager.allocate_port(app_id, app.type)
            if not port:
                self.logger.error(f"Failed to allocate port for app {app_id}")
                return False
            
            # Build command
            app_path = Path(app.path)
            main_file = app_path / app.manifest.main_file
            
            if not main_file.exists():
                self.logger.error(f"Main file not found: {main_file}")
                self.port_manager.release_port(app_id)
                return False
            
            # Build arguments
            cmd = ["python3", str(main_file), "--port", str(port)]
            
            # Add Redis URL if required
            if app.manifest.config.redis_required:
                redis_url = self.config_manager.get_redis_url()
                cmd.extend(["--redis-url", redis_url])
            
            # Add data dir if required
            if app.manifest.config.data_dir:
                data_dir = self.config_manager.get_data_dir(app_id)
                data_dir.mkdir(parents=True, exist_ok=True)
                cmd.extend(["--data-dir", str(data_dir)])
            
            # Add logs dir if required
            if app.manifest.config.logs_dir:
                logs_dir = self.config_manager.get_logs_dir()
                logs_dir.mkdir(parents=True, exist_ok=True)
                cmd.extend(["--logs-dir", str(logs_dir)])
            
            # Start process
            self.logger.info(f"Starting app {app_id} with command: {' '.join(cmd)}")
            
            # Redirect stdout/stderr to log file
            log_file = self.config_manager.get_logs_dir() / f"{app_id}.log"
            with open(log_file, 'a') as log:
                process = subprocess.Popen(
                    cmd,
                    cwd=str(app_path),
                    stdout=log,
                    stderr=subprocess.STDOUT,
                    start_new_session=True  # Detach from parent
                )
            
            # Track process
            self.processes[app_id] = {
                'pid': process.pid,
                'port': port,
                'started_at': datetime.now(),
                'command': ' '.join(cmd)
            }
            
            # Update app registry
            self.app_manager.registry.update_app(
                app_id,
                status='running',
                runtime_info=app.runtime_info
            )
            app.runtime_info.assigned_port = port
            app.runtime_info.process_id = str(process.pid)
            app.runtime_info.started_at = datetime.now()
            
            self.logger.info(f"Started app {app_id} (PID: {process.pid}, Port: {port})")
            return True
            
        except Exception as e:
            self.logger.error(f"Failed to start app {app_id}: {e}", exc_info=True)
            if app_id in self.processes:
                del self.processes[app_id]
            self.port_manager.release_port(app_id)
            return False
    
    def stop_app(self, app_id: str) -> bool:
        """Stop a running service app"""
        try:
            if app_id not in self.processes:
                self.logger.warning(f"App {app_id} is not tracked as running")
                return False
            
            pid = self.processes[app_id].get('pid')
            if not pid:
                self.logger.warning(f"No PID found for app {app_id}")
                return False
            
            # Try to terminate gracefully
            try:
                process = psutil.Process(pid)
                process.terminate()
                process.wait(timeout=5)
                self.logger.info(f"Stopped app {app_id} (PID: {pid})")
            except psutil.TimeoutExpired:
                # Force kill if graceful termination fails
                process.kill()
                self.logger.warning(f"Force killed app {app_id} (PID: {pid})")
            except psutil.NoSuchProcess:
                self.logger.warning(f"Process {pid} for app {app_id} not found")
            
            # Release port
            self.port_manager.release_port(app_id)
            
            # Update registry
            app = self.app_manager.registry.get_app(app_id)
            if app:
                self.app_manager.registry.update_app(app_id, status='stopped')
                app.runtime_info.process_id = None
                app.runtime_info.assigned_port = None
            
            # Remove from tracking
            del self.processes[app_id]
            
            return True
            
        except Exception as e:
            self.logger.error(f"Failed to stop app {app_id}: {e}", exc_info=True)
            return False
    
    def get_app_status(self, app_id: str) -> Optional[str]:
        """Get the status of an app"""
        if app_id not in self.processes:
            return "stopped"
        
        pid = self.processes[app_id].get('pid')
        if not pid:
            return "stopped"
        
        if psutil.pid_exists(pid):
            return "running"
        else:
            # Process died, clean up
            self.logger.warning(f"Process {pid} for app {app_id} died unexpectedly")
            del self.processes[app_id]
            self.port_manager.release_port(app_id)
            return "error"
    
    def get_process_info(self, app_id: str) -> Optional[dict]:
        """Get detailed process information including start time"""
        if app_id not in self.processes:
            return None
        
        process_info = self.processes[app_id].copy()
        
        # Calculate uptime if process is running
        if 'started_at' in process_info:
            uptime_seconds = (datetime.now() - process_info['started_at']).total_seconds()
            process_info['uptime_seconds'] = int(uptime_seconds)
            
            # Format uptime as human-readable string
            hours, remainder = divmod(int(uptime_seconds), 3600)
            minutes, seconds = divmod(remainder, 60)
            
            if hours > 0:
                process_info['uptime'] = f"{hours}h {minutes}m {seconds}s"
            elif minutes > 0:
                process_info['uptime'] = f"{minutes}m {seconds}s"
            else:
                process_info['uptime'] = f"{seconds}s"
            
            # Convert datetime to ISO string for JSON serialization
            process_info['started_at'] = process_info['started_at'].isoformat()
        
        return process_info
    
    def restart_app(self, app_id: str) -> bool:
        """Restart a service app"""
        self.logger.info(f"Restarting app {app_id}")
        self.stop_app(app_id)
        return self.start_app(app_id)
    
    def stop_all(self):
        """Stop all managed processes"""
        self.logger.info("Stopping all managed processes")
        for app_id in list(self.processes.keys()):
            self.stop_app(app_id)
