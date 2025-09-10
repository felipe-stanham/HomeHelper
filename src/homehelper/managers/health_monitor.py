"""
Health Monitor for HomeHelper

Handles periodic health checks for service applications and tracks health status.
Provides configurable health check intervals and failure tracking.
"""

import asyncio
import logging
import aiohttp
from typing import Dict, List, Optional, Callable
from dataclasses import dataclass, asdict
from datetime import datetime, timedelta
from enum import Enum

from ..core.config import ConfigManager
from .app_manager import AppManager, AppType, AppStatus
from .service_manager import ServiceManager, ServiceStatus


class HealthStatus(str, Enum):
    """Health check status values"""
    GOOD = "good"
    WARNING = "warning"
    ERROR = "error"
    UNKNOWN = "unknown"


@dataclass
class HealthCheckResult:
    """Result of a health check"""
    app_id: str
    status: HealthStatus
    message: str
    response_time: Optional[float] = None  # in seconds
    extra_info: Optional[dict] = None
    timestamp: datetime = None
    
    def __post_init__(self):
        if self.timestamp is None:
            self.timestamp = datetime.now()
    
    def to_dict(self) -> dict:
        """Convert to dictionary for JSON serialization"""
        data = asdict(self)
        data['timestamp'] = self.timestamp.isoformat()
        return data
    
    @classmethod
    def from_dict(cls, data: dict) -> 'HealthCheckResult':
        """Create from dictionary"""
        if 'timestamp' in data and data['timestamp']:
            data['timestamp'] = datetime.fromisoformat(data['timestamp'])
        return cls(**data)


@dataclass
class HealthCheckConfig:
    """Configuration for health checks"""
    enabled: bool = True
    interval: int = 30  # seconds
    timeout: int = 5  # seconds
    max_failures: int = 3
    failure_threshold: int = 2  # consecutive failures before marking as unhealthy


class HealthMonitor:
    """Health monitoring system for service applications"""
    
    def __init__(self, config_manager: ConfigManager, app_manager: AppManager, service_manager: ServiceManager):
        self.config_manager = config_manager
        self.app_manager = app_manager
        self.service_manager = service_manager
        self.logger = logging.getLogger("homehelper.health_monitor")
        
        # Health check configuration
        self.config = HealthCheckConfig()
        
        # Health check tracking
        self.health_results: Dict[str, HealthCheckResult] = {}
        self.failure_counts: Dict[str, int] = {}
        self.last_check_times: Dict[str, datetime] = {}
        
        # Monitoring task
        self._monitoring_task: Optional[asyncio.Task] = None
        self._running = False
        
        # HTTP session for health checks
        self._session: Optional[aiohttp.ClientSession] = None
    
    async def start_monitoring(self):
        """Start the health monitoring system"""
        if self._running:
            self.logger.warning("Health monitoring is already running")
            return
        
        self._running = True
        self.logger.info("Starting health monitoring system")
        
        # Create HTTP session
        timeout = aiohttp.ClientTimeout(total=self.config.timeout)
        self._session = aiohttp.ClientSession(timeout=timeout)
        
        # Start monitoring task
        self._monitoring_task = asyncio.create_task(self._monitoring_loop())
    
    async def stop_monitoring(self):
        """Stop the health monitoring system"""
        if not self._running:
            return
        
        self._running = False
        self.logger.info("Stopping health monitoring system")
        
        # Cancel monitoring task
        if self._monitoring_task:
            self._monitoring_task.cancel()
            try:
                await self._monitoring_task
            except asyncio.CancelledError:
                pass
        
        # Close HTTP session
        if self._session:
            await self._session.close()
            self._session = None
    
    async def _monitoring_loop(self):
        """Main monitoring loop"""
        while self._running:
            try:
                await self._perform_health_checks()
                await asyncio.sleep(self.config.interval)
            except asyncio.CancelledError:
                break
            except Exception as e:
                self.logger.error(f"Error in health monitoring loop: {e}")
                await asyncio.sleep(self.config.interval)
    
    async def _perform_health_checks(self):
        """Perform health checks for all running service apps"""
        # Get all running service apps
        service_apps = self.app_manager.registry.get_apps_by_type(AppType.SERVICE)
        running_apps = [app for app in service_apps if app.status == AppStatus.RUNNING]
        
        if not running_apps:
            return
        
        # Perform health checks concurrently
        tasks = []
        for app in running_apps:
            # Check if app has UI endpoint (health check available)
            if app.manifest.config and app.manifest.config.has_UI:
                task = asyncio.create_task(self._check_app_health(app.app_id))
                tasks.append(task)
        
        if tasks:
            results = await asyncio.gather(*tasks, return_exceptions=True)
            
            # Process results
            for i, result in enumerate(results):
                if isinstance(result, Exception):
                    app_id = running_apps[i].app_id
                    self.logger.error(f"Health check failed for app {app_id}: {result}")
                    await self._handle_health_check_failure(app_id, str(result))
    
    async def _check_app_health(self, app_id: str) -> Optional[HealthCheckResult]:
        """
        Perform health check for a specific app
        
        Args:
            app_id: Application identifier
            
        Returns:
            HealthCheckResult or None if failed
        """
        app = self.app_manager.registry.get_app(app_id)
        if not app or not app.runtime_info.assigned_port:
            return None
        
        health_url = f"http://localhost:{app.runtime_info.assigned_port}/health"
        
        try:
            start_time = datetime.now()
            
            async with self._session.get(health_url) as response:
                response_time = (datetime.now() - start_time).total_seconds()
                
                if response.status == 200:
                    data = await response.json()
                    
                    # Parse health response according to spec
                    health_status = data.get('health', 'unknown')
                    message = data.get('message', 'No message provided')
                    extra_info = data.get('extra_info', {})
                    
                    # Map to our enum
                    status_map = {
                        'good': HealthStatus.GOOD,
                        'warning': HealthStatus.WARNING,
                        'error': HealthStatus.ERROR
                    }
                    status = status_map.get(health_status, HealthStatus.UNKNOWN)
                    
                    result = HealthCheckResult(
                        app_id=app_id,
                        status=status,
                        message=message,
                        response_time=response_time,
                        extra_info=extra_info
                    )
                    
                    # Update tracking
                    self.health_results[app_id] = result
                    self.last_check_times[app_id] = datetime.now()
                    
                    # Reset failure count on successful check
                    if status in [HealthStatus.GOOD, HealthStatus.WARNING]:
                        self.failure_counts[app_id] = 0
                    else:
                        await self._handle_health_check_failure(app_id, message)
                    
                    # Update app registry with health info
                    app.runtime_info.last_health_check = datetime.now()
                    self.app_manager.registry.update_app(app_id, runtime_info=app.runtime_info)
                    
                    return result
                    
                else:
                    error_msg = f"HTTP {response.status}: {await response.text()}"
                    await self._handle_health_check_failure(app_id, error_msg)
                    return None
                    
        except asyncio.TimeoutError:
            error_msg = f"Health check timeout after {self.config.timeout}s"
            await self._handle_health_check_failure(app_id, error_msg)
            return None
        except Exception as e:
            error_msg = f"Health check error: {str(e)}"
            await self._handle_health_check_failure(app_id, error_msg)
            return None
    
    async def _handle_health_check_failure(self, app_id: str, error_message: str):
        """
        Handle health check failure for an app
        
        Args:
            app_id: Application identifier
            error_message: Error message
        """
        # Increment failure count
        self.failure_counts[app_id] = self.failure_counts.get(app_id, 0) + 1
        
        # Create error result
        result = HealthCheckResult(
            app_id=app_id,
            status=HealthStatus.ERROR,
            message=error_message
        )
        
        self.health_results[app_id] = result
        self.last_check_times[app_id] = datetime.now()
        
        # Check if we should take action
        failure_count = self.failure_counts[app_id]
        
        if failure_count >= self.config.failure_threshold:
            self.logger.warning(f"App {app_id} has failed {failure_count} consecutive health checks")
            
            # Update app status to error
            app = self.app_manager.registry.get_app(app_id)
            if app:
                app.runtime_info.error_message = f"Health check failures: {error_message}"
                self.app_manager.registry.update_app(
                    app_id,
                    status=AppStatus.ERROR,
                    runtime_info=app.runtime_info
                )
            
            # Check if we should restart the service
            if failure_count >= self.config.max_failures:
                self.logger.error(f"App {app_id} has exceeded max failures ({self.config.max_failures}), attempting restart")
                await self._attempt_service_restart(app_id)
    
    async def _attempt_service_restart(self, app_id: str):
        """
        Attempt to restart a failed service
        
        Args:
            app_id: Application identifier
        """
        try:
            self.logger.info(f"Attempting to restart service for app {app_id}")
            
            # Use service manager to restart
            success = self.service_manager.restart_service(app_id)
            
            if success:
                self.logger.info(f"Successfully restarted service for app {app_id}")
                # Reset failure count
                self.failure_counts[app_id] = 0
                
                # Wait a bit before next health check
                await asyncio.sleep(10)
            else:
                self.logger.error(f"Failed to restart service for app {app_id}")
                
        except Exception as e:
            self.logger.error(f"Exception during service restart for app {app_id}: {e}")
    
    def get_health_status(self, app_id: str) -> Optional[HealthCheckResult]:
        """
        Get latest health status for an app
        
        Args:
            app_id: Application identifier
            
        Returns:
            Latest HealthCheckResult or None
        """
        return self.health_results.get(app_id)
    
    def get_all_health_statuses(self) -> Dict[str, HealthCheckResult]:
        """
        Get health status for all monitored apps
        
        Returns:
            Dictionary mapping app_id to HealthCheckResult
        """
        return self.health_results.copy()
    
    def get_health_statistics(self) -> dict:
        """
        Get health monitoring statistics
        
        Returns:
            Dictionary with health statistics
        """
        if not self.health_results:
            return {
                'total_apps': 0,
                'healthy_apps': 0,
                'warning_apps': 0,
                'error_apps': 0,
                'unknown_apps': 0,
                'average_response_time': 0.0,
                'total_failures': 0
            }
        
        status_counts = {
            HealthStatus.GOOD: 0,
            HealthStatus.WARNING: 0,
            HealthStatus.ERROR: 0,
            HealthStatus.UNKNOWN: 0
        }
        
        total_response_time = 0.0
        response_time_count = 0
        total_failures = sum(self.failure_counts.values())
        
        for result in self.health_results.values():
            status_counts[result.status] += 1
            
            if result.response_time is not None:
                total_response_time += result.response_time
                response_time_count += 1
        
        avg_response_time = total_response_time / response_time_count if response_time_count > 0 else 0.0
        
        return {
            'total_apps': len(self.health_results),
            'healthy_apps': status_counts[HealthStatus.GOOD],
            'warning_apps': status_counts[HealthStatus.WARNING],
            'error_apps': status_counts[HealthStatus.ERROR],
            'unknown_apps': status_counts[HealthStatus.UNKNOWN],
            'average_response_time': round(avg_response_time, 3),
            'total_failures': total_failures
        }
    
    def update_config(self, **kwargs):
        """
        Update health check configuration
        
        Args:
            **kwargs: Configuration parameters to update
        """
        for key, value in kwargs.items():
            if hasattr(self.config, key):
                setattr(self.config, key, value)
                self.logger.info(f"Updated health check config: {key} = {value}")
    
    def is_monitoring(self) -> bool:
        """
        Check if health monitoring is currently running
        
        Returns:
            True if monitoring is active
        """
        return self._running
