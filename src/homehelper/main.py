"""
Main FastAPI application for HomeHelper
"""
import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse
from pathlib import Path

from homehelper.core.config import config_manager
from homehelper.core.redis_client import RedisHealthMonitor
from homehelper.utils.system_monitor import SystemMonitor


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
    setup_logging()
    logger = logging.getLogger("homehelper.main")
    logger.info("Starting HomeHelper main application")
    
    # Ensure required directories exist
    config_manager.get_data_dir().mkdir(parents=True, exist_ok=True)
    config_manager.get_logs_dir().mkdir(parents=True, exist_ok=True)
    
    logger.info("HomeHelper main application started successfully")
    
    yield
    
    # Shutdown
    logger.info("Shutting down HomeHelper main application")


# Initialize components at module level for testing
system_monitor = SystemMonitor()
redis_monitor = RedisHealthMonitor(config_manager.get_redis_url())

# Initialize app management components
from .managers import AppManager, PortManager
port_manager = PortManager(config_manager)
app_manager = AppManager(config_manager, port_manager)


# Create FastAPI app
app = FastAPI(
    title="HomeHelper",
    description="Unified home automation platform for Raspberry Pi",
    version="0.1.0",
    lifespan=lifespan
)


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
        stats = port_manager.get_port_statistics()
        return stats
    except Exception as e:
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
