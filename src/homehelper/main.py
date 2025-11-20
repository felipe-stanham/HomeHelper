"""
Main FastAPI application for HomeHelper
"""
import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse

from homehelper.core.config import config_manager
from homehelper.core.redis_client import RedisHealthMonitor
from homehelper.utils.system_monitor import SystemMonitor
from homehelper.web.dashboard import router as dashboard_router


# Initialize logging
def setup_logging():
    """Setup logging configuration"""
    config = config_manager.config
    
    logging.basicConfig(
        level=getattr(logging, config.logging.level),
        format=config.logging.format,
        handlers=[
            logging.StreamHandler(),
            logging.FileHandler(
                config_manager.get_logs_dir() / "homehelper-main.log"
            )
        ]
    )


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan manager"""
    # Startup
    # Ensure required directories exist BEFORE logging setup
    config_manager.get_data_dir().mkdir(parents=True, exist_ok=True)
    config_manager.get_logs_dir().mkdir(parents=True, exist_ok=True)
    
    setup_logging()
    logger = logging.getLogger("homehelper.main")
    logger.info("Starting HomeHelper main application")
    
    # Auto-start Redis if not running
    logger.info("Checking Redis status...")
    redis_status = redis_monitor.get_redis_metrics()
    if redis_status.get("status") != "connected":
        logger.warning("Redis is not running, attempting to start...")
        try:
            import subprocess
            import platform
            if platform.system() == "Darwin":  # macOS
                subprocess.run(["brew", "services", "start", "redis"], 
                             capture_output=True, check=False)
                logger.info("Started Redis via brew services")
            else:  # Linux
                subprocess.run(["sudo", "systemctl", "start", "redis"], 
                             capture_output=True, check=False)
                logger.info("Started Redis via systemctl")
        except Exception as e:
            logger.error(f"Failed to auto-start Redis: {e}")
    else:
        logger.info("Redis is already running")
    
    # Discover apps on startup
    logger.info("Discovering applications...")
    discovered_count = app_manager.discover_apps()
    logger.info(f"Discovered {discovered_count} applications")
    
    # Auto-start service apps with auto_start=true
    logger.info("Auto-starting service apps...")
    auto_start_count = 0
    for app_entry in app_manager.registry.get_all_apps():
        if app_entry.type == "service" and app_entry.manifest.config.auto_start:
            logger.info(f"Auto-starting service app: {app_entry.name} ({app_entry.app_id})")
            if macos_process_manager.start_app(app_entry.app_id):
                auto_start_count += 1
                logger.info(f"Successfully started {app_entry.name}")
            else:
                logger.error(f"Failed to start {app_entry.name}")
    logger.info(f"Auto-started {auto_start_count} service apps")
    
    logger.info("HomeHelper main application started successfully")
    
    yield
    
    # Shutdown
    logger.info("Shutting down HomeHelper main application")
    logger.info("Stopping all managed service apps...")
    macos_process_manager.stop_all()
    logger.info("Stopping all Streamlit apps...")
    streamlit_manager.stop_all()
    logger.info("Shutdown complete")


# Initialize components at module level for testing
system_monitor = SystemMonitor()
redis_monitor = RedisHealthMonitor(config_manager.get_redis_url())

# Initialize app management components
from .managers import AppManager, PortManager, ServiceManager
from .managers.health_monitor import HealthMonitor
from .managers.process_manager_macos import MacOSProcessManager
from .managers.streamlit_manager import StreamlitManager

port_manager = PortManager(config_manager)
app_manager = AppManager(config_manager, port_manager)
service_manager = ServiceManager(config_manager, app_manager)
health_monitor = HealthMonitor(config_manager, app_manager, service_manager)
macos_process_manager = MacOSProcessManager(config_manager, app_manager, port_manager)
streamlit_manager = StreamlitManager(config_manager, app_manager, port_manager)


# Create FastAPI app
app = FastAPI(
    title="HomeHelper",
    description="Unified home automation platform for Raspberry Pi",
    version="0.1.0",
    lifespan=lifespan
)

# Include web dashboard routes
app.include_router(dashboard_router)


@app.get("/")
async def root():
    """Root endpoint"""
    return {"message": "HomeHelper is running", "version": "0.1.0"}


@app.get("/health")
async def health_check():
    """Main application health check"""
    try:
        config = config_manager.config
        
        # Get system metrics
        hardware_metrics = system_monitor.get_hardware_metrics()
        redis_metrics = redis_monitor.get_redis_metrics()
        
        # Determine overall health
        health_status = "good"
        issues = []
        
        # Check hardware thresholds
        if "error" in hardware_metrics:
            health_status = "error"
            issues.append("Hardware monitoring failed")
        else:
            cpu_usage = hardware_metrics.get("cpu", {}).get("usage_percent", 0)
            memory_usage = hardware_metrics.get("memory", {}).get("percent", 0)
            disk_usage = hardware_metrics.get("disk", {}).get("percent", 0)
            
            if cpu_usage > 80:
                health_status = "warning"
                issues.append(f"High CPU usage: {cpu_usage}%")
            if memory_usage > 85:
                health_status = "warning"
                issues.append(f"High memory usage: {memory_usage}%")
            if disk_usage > 90:
                health_status = "warning"
                issues.append(f"High disk usage: {disk_usage}%")
        
        # Check Redis connection
        if redis_metrics.get("status") != "connected":
            health_status = "error"
            issues.append("Redis connection failed")
        
        return {
            "health": health_status,
            "message": "System operational" if not issues else "; ".join(issues),
            "extra_info": {
                "hardware": hardware_metrics,
                "redis": redis_metrics,
                "config_loaded": config is not None,
                "data_dir_exists": config_manager.get_data_dir().exists(),
                "logs_dir_exists": config_manager.get_logs_dir().exists()
            }
        }
        
    except Exception as e:
        logging.getLogger("homehelper.main").error(f"Health check failed: {e}")
        return JSONResponse(
            status_code=500,
            content={
                "health": "error",
                "message": f"Health check failed: {str(e)}"
            }
        )


@app.get("/api/system/metrics")
async def get_system_metrics():
    """Get detailed system metrics"""
    try:
        return system_monitor.get_system_summary()
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/system/redis")
async def get_redis_metrics():
    """Get Redis metrics and status"""
    try:
        return redis_monitor.get_redis_metrics()
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/config")
async def get_config():
    """Get current configuration (sanitized)"""
    try:
        config = config_manager.config
        
        # Return sanitized config (no sensitive data)
        return {
            "redis": {
                "host": config.redis.host,
                "port": config.redis.port,
                "db": config.redis.db
            },
            "logging": {
                "level": config.logging.level,
                "format": config.logging.format
            },
            "process_manager": {
                "data_dir": config.process_manager.data_dir,
                "logs_dir": config.process_manager.logs_dir,
                "streamlit_port": config.process_manager.streamlit_port,
                "streamlit_ttl_seconds": config.process_manager.streamlit_ttl_seconds,
                "port_range": {
                    "start": config.process_manager.port_range.start,
                    "end": config.process_manager.port_range.end
                }
            },
            "health_check_interval_seconds": config.health_check_interval_seconds,
            "system": {
                "main_port": config.system.main_port,
                "host": config.system.host
            }
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# App Management API Endpoints

@app.post("/api/apps/discover")
async def discover_apps():
    """Discover applications in the apps directory"""
    try:
        count = app_manager.discover_apps()
        return {
            "discovered_count": count,
            "message": f"Discovered {count} new applications"
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/apps")
async def get_all_apps():
    """Get all registered applications"""
    try:
        apps = app_manager.registry.get_all_apps()
        return {
            "apps": [app.to_dict() for app in apps],
            "total_count": len(apps)
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/apps/{app_id}")
async def get_app(app_id: str):
    """Get a specific application by ID"""
    try:
        app = app_manager.registry.get_app(app_id)
        if not app:
            raise HTTPException(status_code=404, detail=f"App {app_id} not found")
        
        return app.to_dict()
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/apps/type/{app_type}")
async def get_apps_by_type(app_type: str):
    """Get applications by type (service or streamlit)"""
    try:
        from .managers.app_manager import AppType
        
        if app_type not in [AppType.SERVICE, AppType.STREAMLIT]:
            raise HTTPException(status_code=400, detail=f"Invalid app type: {app_type}")
        
        apps = app_manager.registry.get_apps_by_type(AppType(app_type))
        return {
            "apps": [app.to_dict() for app in apps],
            "type": app_type,
            "count": len(apps)
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/apps/status/{status}")
async def get_apps_by_status(status: str):
    """Get applications by status"""
    try:
        from .managers.app_manager import AppStatus
        
        valid_statuses = [s.value for s in AppStatus]
        if status not in valid_statuses:
            raise HTTPException(status_code=400, detail=f"Invalid status: {status}. Valid statuses: {valid_statuses}")
        
        apps = app_manager.registry.get_apps_by_status(AppStatus(status))
        return {
            "apps": [app.to_dict() for app in apps],
            "status": status,
            "count": len(apps)
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/apps/{app_id}/prepare")
async def prepare_app(app_id: str):
    """Prepare an application (install dependencies, run setup)"""
    try:
        app = app_manager.registry.get_app(app_id)
        if not app:
            raise HTTPException(status_code=404, detail=f"App {app_id} not found")
        
        success = app_manager.prepare_app(app_id)
        if success:
            updated_app = app_manager.registry.get_app(app_id)
            return {
                "success": True,
                "message": f"App {app_id} prepared successfully",
                "app": updated_app.to_dict()
            }
        else:
            updated_app = app_manager.registry.get_app(app_id)
            error_msg = updated_app.runtime_info.error_message if updated_app.runtime_info.error_message else "Unknown error"
            return {
                "success": False,
                "message": f"Failed to prepare app {app_id}: {error_msg}",
                "app": updated_app.to_dict()
            }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.delete("/api/apps/{app_id}")
async def unregister_app(app_id: str):
    """Unregister an application"""
    try:
        app = app_manager.registry.get_app(app_id)
        if not app:
            raise HTTPException(status_code=404, detail=f"App {app_id} not found")
        
        # Release port if allocated
        if app.runtime_info.assigned_port:
            port_manager.release_port(app_id)
        
        success = app_manager.registry.unregister_app(app_id)
        if success:
            return {
                "success": True,
                "message": f"App {app_id} unregistered successfully"
            }
        else:
            raise HTTPException(status_code=500, detail=f"Failed to unregister app {app_id}")
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/apps/statistics")
async def get_app_statistics():
    """Get application statistics"""
    try:
        stats = app_manager.get_app_statistics()
        return stats
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# Port Management API Endpoints

@app.get("/api/ports")
async def get_port_allocations():
    """Get all port allocations"""
    try:
        allocations = port_manager.get_allocated_ports()
        return {
            "allocations": [alloc.to_dict() for alloc in allocations],
            "count": len(allocations)
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/ports/available")
async def get_available_ports():
    """Get available ports"""
    try:
        available = port_manager.get_available_ports()
        return {
            "available_ports": available,
            "count": len(available)
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/ports/statistics")
async def get_port_statistics():
    """Get port allocation statistics"""
    try:
        stats = port_manager.get_statistics()
        return {"success": True, "data": stats}
    except Exception as e:
        logger.error(f"Failed to get port statistics: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# Service Management API Endpoints

@app.post("/api/services/{app_id}/create")
async def create_service(app_id: str):
    """Create systemd service file for an app"""
    try:
        success = service_manager.create_service_file(app_id)
        if success:
            return {"success": True, "message": f"Service file created for app {app_id}"}
        else:
            raise HTTPException(status_code=400, detail=f"Failed to create service file for app {app_id}")
    except Exception as e:
        logger.error(f"Failed to create service for app {app_id}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/services/{app_id}/start")
async def start_service(app_id: str):
    """Start systemd service for an app"""
    try:
        success = service_manager.start_service(app_id)
        if success:
            return {"success": True, "message": f"Service started for app {app_id}"}
        else:
            raise HTTPException(status_code=400, detail=f"Failed to start service for app {app_id}")
    except Exception as e:
        logger.error(f"Failed to start service for app {app_id}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/services/{app_id}/stop")
async def stop_service(app_id: str):
    """Stop systemd service for an app"""
    try:
        success = service_manager.stop_service(app_id)
        if success:
            return {"success": True, "message": f"Service stopped for app {app_id}"}
        else:
            raise HTTPException(status_code=400, detail=f"Failed to stop service for app {app_id}")
    except Exception as e:
        logger.error(f"Failed to stop service for app {app_id}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/services/{app_id}/restart")
async def restart_service(app_id: str):
    """Restart systemd service for an app"""
    try:
        success = service_manager.restart_service(app_id)
        if success:
            return {"success": True, "message": f"Service restarted for app {app_id}"}
        else:
            raise HTTPException(status_code=400, detail=f"Failed to restart service for app {app_id}")
    except Exception as e:
        logger.error(f"Failed to restart service for app {app_id}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/services/{app_id}/status")
async def get_service_status(app_id: str):
    """Get detailed service status for an app"""
    try:
        status = service_manager.get_service_status(app_id)
        if status:
            return {"success": True, "data": status.to_dict()}
        else:
            raise HTTPException(status_code=404, detail=f"Service status not found for app {app_id}")
    except Exception as e:
        logger.error(f"Failed to get service status for app {app_id}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/services/{app_id}/logs")
async def get_service_logs(app_id: str, lines: int = 50):
    """Get recent service logs for an app (systemd-based)"""
    try:
        logs = service_manager.get_service_logs(app_id, lines)
        return {"success": True, "data": {"logs": logs, "lines": len(logs)}}
    except Exception as e:
        logger.error(f"Failed to get service logs for app {app_id}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/apps/{app_id}/logs")
async def get_app_logs(app_id: str, lines: int = 100):
    """Get recent logs for an app from log files (cross-platform)"""
    try:
        from pathlib import Path
        
        # Check for app-specific log file
        logs_dir = config_manager.get_logs_dir()
        
        # Try different log file patterns
        log_files = [
            logs_dir / f"{app_id}.log",
            logs_dir / f"{app_id}-streamlit.log",
            logs_dir / f"homehelper-{app_id}.log"
        ]
        
        log_lines = []
        for log_file in log_files:
            if log_file.exists():
                try:
                    with open(log_file, 'r') as f:
                        all_lines = f.readlines()
                        # Get last N lines
                        log_lines = all_lines[-lines:] if len(all_lines) > lines else all_lines
                        # Strip newlines
                        log_lines = [line.rstrip('\n') for line in log_lines]
                        break
                except Exception as e:
                    logger.error(f"Failed to read log file {log_file}: {e}")
        
        if not log_lines:
            # No log file found, return empty
            return {"success": True, "data": {"logs": [], "lines": 0, "message": "No log file found"}}
        
        return {"success": True, "data": {"logs": log_lines, "lines": len(log_lines)}}
        
    except Exception as e:
        logger.error(f"Failed to get logs for app {app_id}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/logs/homehelper")
async def get_homehelper_logs(lines: int = 100):
    """Get recent HomeHelper main application logs"""
    try:
        from pathlib import Path
        
        log_file = config_manager.get_logs_dir() / "homehelper-main.log"
        
        if not log_file.exists():
            return {"success": True, "data": {"logs": [], "lines": 0, "message": "Log file not found"}}
        
        try:
            with open(log_file, 'r') as f:
                all_lines = f.readlines()
                # Get last N lines
                log_lines = all_lines[-lines:] if len(all_lines) > lines else all_lines
                # Strip newlines
                log_lines = [line.rstrip('\n') for line in log_lines]
            
            return {"success": True, "data": {"logs": log_lines, "lines": len(log_lines)}}
            
        except Exception as e:
            logger.error(f"Failed to read HomeHelper log file: {e}")
            raise HTTPException(status_code=500, detail=str(e))
        
    except Exception as e:
        logger.error(f"Failed to get HomeHelper logs: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/activity/recent")
async def get_recent_activity(limit: int = 10):
    """Get recent activity from Redis (published messages)"""
    try:
        import redis
        import json
        from datetime import datetime
        
        # Connect to Redis
        redis_client = redis.from_url(config_manager.get_redis_url())
        
        # Get recent messages from a list (if apps are publishing to one)
        # For now, return activity from logs as a fallback
        activities = []
        
        # Try to get from Redis list (if it exists)
        try:
            # Check if there's a recent events list
            events_key = "homehelper:events:recent"
            events = redis_client.lrange(events_key, 0, limit - 1)
            
            for event in events:
                try:
                    event_data = json.loads(event)
                    activities.append(event_data)
                except:
                    pass
        except:
            pass
        
        # If no Redis events, parse from logs
        if not activities:
            log_file = config_manager.get_logs_dir() / "homehelper-main.log"
            if log_file.exists():
                with open(log_file, 'r') as f:
                    lines = f.readlines()[-50:]  # Last 50 lines
                    
                    for line in lines:
                        # Parse log lines for interesting events
                        if any(keyword in line for keyword in ['Started', 'Stopped', 'Auto-starting', 'Successfully', 'Failed']):
                            # Extract timestamp and message
                            parts = line.split(' - ', 2)
                            if len(parts) >= 3:
                                timestamp = parts[0]
                                level = parts[1]
                                message = parts[2].strip()
                                
                                activities.append({
                                    'timestamp': timestamp,
                                    'level': level,
                                    'message': message
                                })
                    
                    # Limit to most recent
                    activities = activities[-limit:]
        
        return {"success": True, "data": {"activities": activities, "count": len(activities)}}
        
    except Exception as e:
        logger.error(f"Failed to get recent activity: {e}")
        return {"success": True, "data": {"activities": [], "count": 0, "error": str(e)}}


@app.post("/api/services/{app_id}/enable")
async def enable_service(app_id: str):
    """Enable service to start automatically"""
    try:
        success = service_manager.enable_service(app_id)
        if success:
            return {"success": True, "message": f"Service enabled for app {app_id}"}
        else:
            raise HTTPException(status_code=400, detail=f"Failed to enable service for app {app_id}")
    except Exception as e:
        logger.error(f"Failed to enable service for app {app_id}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/services/{app_id}/disable")
async def disable_service(app_id: str):
    """Disable service from starting automatically"""
    try:
        success = service_manager.disable_service(app_id)
        if success:
            return {"success": True, "message": f"Service disabled for app {app_id}"}
        else:
            raise HTTPException(status_code=400, detail=f"Failed to disable service for app {app_id}")
    except Exception as e:
        logger.error(f"Failed to disable service for app {app_id}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.delete("/api/services/{app_id}")
async def remove_service(app_id: str):
    """Remove service file and stop service"""
    try:
        success = service_manager.remove_service(app_id)
        if success:
            return {"success": True, "message": f"Service removed for app {app_id}"}
        else:
            raise HTTPException(status_code=400, detail=f"Failed to remove service for app {app_id}")
    except Exception as e:
        logger.error(f"Failed to remove service for app {app_id}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/services")
async def get_all_service_statuses():
    """Get status for all managed services"""
    try:
        statuses = service_manager.get_all_service_statuses()
        return {"success": True, "data": {app_id: status.to_dict() for app_id, status in statuses.items()}}
    except Exception as e:
        logger.error(f"Failed to get all service statuses: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/services/statistics")
async def get_service_statistics():
    """Get service management statistics"""
    try:
        stats = service_manager.get_service_statistics()
        return {"success": True, "data": stats}
    except Exception as e:
        logger.error(f"Failed to get service statistics: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# Health Monitoring API Endpoints

@app.post("/api/health/start")
async def start_health_monitoring():
    """Start health monitoring system"""
    try:
        await health_monitor.start_monitoring()
        return {"success": True, "message": "Health monitoring started"}
    except Exception as e:
        logger.error(f"Failed to start health monitoring: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/health/stop")
async def stop_health_monitoring():
    """Stop health monitoring system"""
    try:
        await health_monitor.stop_monitoring()
        return {"success": True, "message": "Health monitoring stopped"}
    except Exception as e:
        logger.error(f"Failed to stop health monitoring: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/health/{app_id}")
async def get_app_health(app_id: str):
    """Get health status for a specific app"""
    try:
        health = health_monitor.get_health_status(app_id)
        if health:
            return {"success": True, "data": health.to_dict()}
        else:
            raise HTTPException(status_code=404, detail=f"Health status not found for app {app_id}")
    except Exception as e:
        logger.error(f"Failed to get health status for app {app_id}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/health")
async def get_all_health_statuses():
    """Get health status for all monitored apps"""
    try:
        statuses = health_monitor.get_all_health_statuses()
        return {"success": True, "data": {app_id: status.to_dict() for app_id, status in statuses.items()}}
    except Exception as e:
        logger.error(f"Failed to get all health statuses: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/health/statistics")
async def get_health_statistics():
    """Get health monitoring statistics"""
    try:
        stats = health_monitor.get_health_statistics()
        return {"success": True, "data": stats}
    except Exception as e:
        logger.error(f"Failed to get health statistics: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.put("/api/health/config")
async def update_health_config(config: dict):
    """Update health monitoring configuration"""
    try:
        health_monitor.update_config(**config)
        return {"success": True, "message": "Health monitoring configuration updated"}
    except Exception as e:
        logger.error(f"Failed to update health config: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/health/status")
async def get_health_monitoring_status():
    """Get health monitoring system status"""
    try:
        is_running = health_monitor.is_monitoring()
        return {"success": True, "data": {"monitoring": is_running}}
    except Exception as e:
        logger.error(f"Failed to get health monitoring status: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/ports/cleanup")
async def cleanup_stale_ports():
    """Clean up stale port allocations"""
    try:
        cleaned = port_manager.cleanup_stale_allocations()
        return {
            "cleaned_count": cleaned,
            "message": f"Cleaned up {cleaned} stale port allocations"
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# UI Integration Endpoints

@app.get("/api/apps/{app_id}/ui/resources")
async def get_app_ui_resources(app_id: str):
    """Discover UI resources available from a service app"""
    try:
        from .web.ui_renderer import ui_renderer
        
        app = app_manager.registry.get_app(app_id)
        if not app:
            raise HTTPException(status_code=404, detail=f"App {app_id} not found")
        
        if app.type != "service":
            raise HTTPException(status_code=400, detail="Only service apps can have UI resources")
        
        port = app.runtime_info.assigned_port
        if not port:
            raise HTTPException(status_code=400, detail="App is not running or has no assigned port")
        
        base_url = f"http://localhost:{port}"
        resources = await ui_renderer.discover_ui_resources(base_url)
        
        if resources is None:
            return {"has_ui": False, "resources": []}
        
        return {"has_ui": True, "resources": resources, "base_url": base_url}
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to discover UI resources for app {app_id}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/apps/{app_id}/ui/{resource}")
async def get_app_ui_resource(app_id: str, resource: str):
    """Fetch data for a specific UI resource"""
    try:
        from .web.ui_renderer import ui_renderer
        
        app = app_manager.registry.get_app(app_id)
        if not app:
            raise HTTPException(status_code=404, detail=f"App {app_id} not found")
        
        port = app.runtime_info.assigned_port
        if not port:
            raise HTTPException(status_code=400, detail="App is not running")
        
        base_url = f"http://localhost:{port}"
        data = await ui_renderer.fetch_resource_list(base_url, resource)
        
        if data is None:
            raise HTTPException(status_code=404, detail=f"Resource {resource} not found")
        
        # Render as HTML table
        html = ui_renderer.render_table_html(data, resource)
        
        return {
            "resource": resource,
            "data": data,
            "html": html,
            "count": len(data)
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to fetch UI resource {resource} for app {app_id}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# Streamlit App Management Endpoints

@app.post("/api/apps/{app_id}/streamlit/launch")
async def launch_streamlit_app(app_id: str):
    """Launch a Streamlit app (or return existing instance)"""
    try:
        app = app_manager.registry.get_app(app_id)
        if not app:
            raise HTTPException(status_code=404, detail=f"App {app_id} not found")
        
        if app.type != "streamlit":
            raise HTTPException(status_code=400, detail="App is not a Streamlit app")
        
        result = streamlit_manager.launch_streamlit_app(app_id)
        
        if result is None:
            raise HTTPException(status_code=500, detail="Failed to launch Streamlit app")
        
        return result
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to launch Streamlit app {app_id}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/apps/{app_id}/streamlit/stop")
async def stop_streamlit_app(app_id: str):
    """Stop a running Streamlit app"""
    try:
        success = streamlit_manager.stop_streamlit_app(app_id)
        
        if not success:
            raise HTTPException(status_code=404, detail="Streamlit app is not running")
        
        return {"message": f"Streamlit app {app_id} stopped successfully"}
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to stop Streamlit app {app_id}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/apps/{app_id}/streamlit/touch")
async def touch_streamlit_app(app_id: str):
    """Update last accessed time for a Streamlit app (extends TTL)"""
    try:
        streamlit_manager.touch_app(app_id)
        return {"message": "TTL extended"}
    except Exception as e:
        logger.error(f"Failed to touch Streamlit app {app_id}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/streamlit/running")
async def get_running_streamlit_apps():
    """Get list of currently running Streamlit apps"""
    try:
        return streamlit_manager.get_running_apps()
    except Exception as e:
        logger.error(f"Failed to get running Streamlit apps: {e}")
        raise HTTPException(status_code=500, detail=str(e))


if __name__ == "__main__":
    import uvicorn
    
    config = config_manager.config
    uvicorn.run(
        "homehelper.main:app",
        host=config.system.host,
        port=config.system.main_port,
        reload=True,
        log_level=config.logging.level.lower()
    )
