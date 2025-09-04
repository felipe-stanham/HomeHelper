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
        return {
            "system": config.system.model_dump(),
            "process_manager": {
                "data_dir": str(config.process_manager.data_dir),
                "logs_dir": str(config.process_manager.logs_dir),
                "streamlit_port": config.process_manager.streamlit_port,
                "streamlit_ttl_seconds": config.process_manager.streamlit_ttl_seconds,
                "port_range": config.process_manager.port_range.model_dump()
            },
            "health_check_interval_seconds": config.health_check_interval_seconds,
            "redis": {
                "host": config.redis.host,
                "port": config.redis.port,
                "db": config.redis.db
            }
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
