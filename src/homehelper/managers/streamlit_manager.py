"""
Streamlit App Manager with TTL-based process management

Manages Streamlit app processes with automatic cleanup after inactivity.
"""
import logging
import subprocess
import psutil
import time
from pathlib import Path
from typing import Optional, Dict
from datetime import datetime, timedelta
from threading import Thread, Lock


class StreamlitManager:
    """Manages Streamlit app processes with TTL-based cleanup"""
    
    def __init__(self, config_manager, app_manager, port_manager):
        self.config_manager = config_manager
        self.app_manager = app_manager
        self.port_manager = port_manager
        self.logger = logging.getLogger("homehelper.streamlit_manager")
        
        # Track running Streamlit processes: app_id -> process info
        self.processes: Dict[str, dict] = {}
        self.lock = Lock()
        
        # TTL configuration (in seconds)
        self.default_ttl = 300  # 5 minutes of inactivity
        
        # Start cleanup thread
        self.cleanup_thread = Thread(target=self._cleanup_loop, daemon=True)
        self.cleanup_thread.start()
        self.logger.info("Streamlit manager initialized with TTL cleanup")
    
    def launch_streamlit_app(self, app_id: str) -> Optional[dict]:
        """
        Launch a Streamlit app or return existing instance
        
        Args:
            app_id: ID of the Streamlit app to launch
            
        Returns:
            Dict with url, port, pid, or None on error
        """
        with self.lock:
            # Check if already running
            if app_id in self.processes:
                process_info = self.processes[app_id]
                pid = process_info['pid']
                
                # Verify process is still alive
                if psutil.pid_exists(pid):
                    # Update last accessed time
                    process_info['last_accessed'] = datetime.now()
                    self.logger.info(f"Streamlit app {app_id} already running (PID: {pid})")
                    return {
                        'url': f"http://localhost:{process_info['port']}",
                        'port': process_info['port'],
                        'pid': pid,
                        'status': 'running'
                    }
                else:
                    # Process died, clean up
                    self.logger.warning(f"Streamlit app {app_id} process died, cleaning up")
                    self._cleanup_app(app_id)
            
            # Launch new instance
            try:
                app = self.app_manager.registry.get_app(app_id)
                if not app:
                    self.logger.error(f"App {app_id} not found")
                    return None
                
                if app.type != "streamlit":
                    self.logger.error(f"App {app_id} is not a Streamlit app")
                    return None
                
                # Allocate port
                port = self.port_manager.allocate_port(app_id, app.type)
                if not port:
                    self.logger.error(f"Failed to allocate port for Streamlit app {app_id}")
                    return None
                
                # Build command
                app_path = Path(app.path)
                main_file = app_path / app.manifest.main_file
                
                if not main_file.exists():
                    self.logger.error(f"Main file not found: {main_file}")
                    self.port_manager.release_port(app_id)
                    return None
                
                # Streamlit command (use python3 -m streamlit for better compatibility)
                cmd = [
                    "python3", "-m", "streamlit", "run",
                    str(main_file),
                    "--server.port", str(port),
                    "--server.headless", "true",
                    "--browser.gatherUsageStats", "false",
                    "--server.fileWatcherType", "none"
                ]
                
                # Start process
                self.logger.info(f"Launching Streamlit app {app_id} on port {port}")
                
                # Redirect stdout/stderr to log file
                log_file = self.config_manager.get_logs_dir() / f"{app_id}-streamlit.log"
                with open(log_file, 'a') as log:
                    process = subprocess.Popen(
                        cmd,
                        cwd=str(app_path),
                        stdout=log,
                        stderr=subprocess.STDOUT,
                        start_new_session=True
                    )
                
                # Track process
                self.processes[app_id] = {
                    'pid': process.pid,
                    'port': port,
                    'started_at': datetime.now(),
                    'last_accessed': datetime.now(),
                    'command': ' '.join(cmd)
                }
                
                # Update app registry
                app.runtime_info.assigned_port = port
                app.runtime_info.process_id = str(process.pid)
                app.runtime_info.started_at = datetime.now()
                
                # Update app status to running
                self.app_manager.registry.update_app(
                    app_id,
                    status='running',
                    runtime_info=app.runtime_info
                )
                
                self.logger.info(f"Launched Streamlit app {app_id} (PID: {process.pid}, Port: {port})")
                
                # Give Streamlit a moment to start
                time.sleep(2)
                
                return {
                    'url': f"http://localhost:{port}",
                    'port': port,
                    'pid': process.pid,
                    'status': 'running'
                }
                
            except Exception as e:
                self.logger.error(f"Failed to launch Streamlit app {app_id}: {e}", exc_info=True)
                if app_id in self.processes:
                    del self.processes[app_id]
                self.port_manager.release_port(app_id)
                return None
    
    def stop_streamlit_app(self, app_id: str) -> bool:
        """Stop a running Streamlit app"""
        with self.lock:
            if app_id not in self.processes:
                self.logger.warning(f"Streamlit app {app_id} is not running")
                return False
            
            return self._cleanup_app(app_id)
    
    def _cleanup_app(self, app_id: str) -> bool:
        """Internal cleanup method (must be called with lock held)"""
        try:
            process_info = self.processes[app_id]
            pid = process_info['pid']
            
            # Try to terminate gracefully
            try:
                process = psutil.Process(pid)
                process.terminate()
                process.wait(timeout=5)
                self.logger.info(f"Stopped Streamlit app {app_id} (PID: {pid})")
            except psutil.TimeoutExpired:
                # Force kill if graceful termination fails
                process.kill()
                self.logger.warning(f"Force killed Streamlit app {app_id} (PID: {pid})")
            except psutil.NoSuchProcess:
                self.logger.warning(f"Process {pid} for Streamlit app {app_id} not found")
            
            # Release port
            self.port_manager.release_port(app_id)
            
            # Update registry
            app = self.app_manager.registry.get_app(app_id)
            if app:
                app.runtime_info.process_id = None
                app.runtime_info.assigned_port = None
                
                # Update app status to discovered (not running)
                self.app_manager.registry.update_app(
                    app_id,
                    status='discovered',
                    runtime_info=app.runtime_info
                )
            
            # Remove from tracking
            del self.processes[app_id]
            
            return True
            
        except Exception as e:
            self.logger.error(f"Failed to cleanup Streamlit app {app_id}: {e}", exc_info=True)
            return False
    
    def touch_app(self, app_id: str):
        """Update last accessed time for a Streamlit app"""
        with self.lock:
            if app_id in self.processes:
                self.processes[app_id]['last_accessed'] = datetime.now()
                self.logger.debug(f"Updated last accessed time for Streamlit app {app_id}")
    
    def _cleanup_loop(self):
        """Background thread that cleans up inactive Streamlit apps"""
        while True:
            try:
                time.sleep(30)  # Check every 30 seconds
                
                with self.lock:
                    now = datetime.now()
                    apps_to_cleanup = []
                    
                    for app_id, process_info in self.processes.items():
                        last_accessed = process_info['last_accessed']
                        idle_time = (now - last_accessed).total_seconds()
                        
                        if idle_time > self.default_ttl:
                            apps_to_cleanup.append(app_id)
                            self.logger.info(f"Streamlit app {app_id} idle for {idle_time:.0f}s, cleaning up")
                    
                    # Cleanup idle apps
                    for app_id in apps_to_cleanup:
                        self._cleanup_app(app_id)
                        
            except Exception as e:
                self.logger.error(f"Error in Streamlit cleanup loop: {e}", exc_info=True)
    
    def get_running_apps(self) -> Dict[str, dict]:
        """Get list of currently running Streamlit apps"""
        with self.lock:
            return {
                app_id: {
                    'port': info['port'],
                    'pid': info['pid'],
                    'started_at': info['started_at'].isoformat(),
                    'last_accessed': info['last_accessed'].isoformat(),
                    'idle_seconds': (datetime.now() - info['last_accessed']).total_seconds()
                }
                for app_id, info in self.processes.items()
            }
    
    def stop_all(self):
        """Stop all running Streamlit apps"""
        with self.lock:
            self.logger.info("Stopping all Streamlit apps")
            for app_id in list(self.processes.keys()):
                self._cleanup_app(app_id)
