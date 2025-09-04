# HomeHelper: Code Examples

## Enhanced Message Bus Client
```python
import redis
import json
import logging
import time
from typing import Dict, Any, Callable, Optional

class RedisMessageBusClient:
    def __init__(self, app_id: str, redis_host='localhost', redis_port=6379):
        self.app_id = app_id
        self.redis = redis.Redis(host=redis_host, port=redis_port, decode_responses=True)
        self.pubsub = self.redis.pubsub()
        self.logger = logging.getLogger(f"homehelper.{app_id}.message_bus")
        
    def publish(self, event_type: str, data: Dict[str, Any]):
        """Publish event to the message bus"""
        channel = f"homehelper:events:{event_type}"
        message = {
            "app_id": self.app_id,
            "event_type": event_type,
            "data": data,
            "timestamp": time.time()
        }
        
        try:
            self.redis.publish(channel, json.dumps(message))
            self.logger.debug(f"Published {event_type} to {channel}")
        except Exception as e:
            self.logger.error(f"Failed to publish {event_type}: {e}")
    
    def subscribe(self, event_type: str, callback: Callable[[Dict], None]):
        """Subscribe to an event type"""
        channel = f"homehelper:events:{event_type}"
        self.pubsub.subscribe(channel)
        self.logger.info(f"Subscribed to {event_type}")
        
        # Handle messages in background thread
        def message_handler():
            for message in self.pubsub.listen():
                if message['type'] == 'message':
                    try:
                        data = json.loads(message['data'])
                        callback(data)
                    except Exception as e:
                        self.logger.error(f"Error processing message: {e}")
        
        import threading
        handler_thread = threading.Thread(target=message_handler, daemon=True)
        handler_thread.start()

    def get_health(self) -> Dict[str, Any]:
        """Get Redis connection health"""
        try:
            self.redis.ping()
            info = self.redis.info()
            return {
                "connected": True,
                "memory_used": info.get('used_memory', 0),
                "memory_peak": info.get('used_memory_peak', 0),
                "uptime": info.get('uptime_in_seconds', 0)
            }
        except Exception as e:
            return {"connected": False, "error": str(e)}
```

## System Monitoring Module
```python
import psutil
import os
import json
from pathlib import Path
from typing import Dict, Any, Optional

class SystemMonitor:
    def get_hardware_metrics(self) -> Dict[str, Any]:
        """Get system-wide hardware metrics"""
        try:
            # CPU temperature (RPi specific)
            temp = self._get_cpu_temperature()
            
            return {
                "cpu": {
                    "usage_percent": psutil.cpu_percent(interval=1),
                    "temperature_c": temp,
                    "load_avg": os.getloadavg()
                },
                "memory": {
                    "total_mb": psutil.virtual_memory().total // (1024*1024),
                    "used_mb": psutil.virtual_memory().used // (1024*1024),
                    "percent": psutil.virtual_memory().percent
                },
                "disk": {
                    "total_gb": psutil.disk_usage('/').total // (1024*1024*1024),
                    "used_gb": psutil.disk_usage('/').used // (1024*1024*1024),
                    "free_gb": psutil.disk_usage('/').free // (1024*1024*1024),
                    "percent": psutil.disk_usage('/').percent
                }
            }
        except Exception as e:
            return {"error": f"Failed to get hardware metrics: {e}"}

    def get_process_metrics(self, pid: int) -> Optional[Dict[str, Any]]:
        """Get metrics for specific process"""
        try:
            process = psutil.Process(pid)
            return {
                "pid": pid,
                "name": process.name(),
                "status": process.status(),
                "cpu_percent": process.cpu_percent(),
                "memory_mb": process.memory_info().rss // (1024*1024),
                "uptime_seconds": time.time() - process.create_time(),
                "threads": process.num_threads()
            }
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            return None

    def get_redis_metrics(self, redis_client) -> Dict[str, Any]:
        """Get Redis-specific metrics"""
        try:
            info = redis_client.info()
            return {
                "connected": True,
                "memory_used_mb": info.get('used_memory', 0) // (1024*1024),
                "memory_peak_mb": info.get('used_memory_peak', 0) // (1024*1024),
                "total_commands": info.get('total_commands_processed', 0),
                "connected_clients": info.get('connected_clients', 0),
                "uptime_seconds": info.get('uptime_in_seconds', 0)
            }
        except Exception as e:
            return {"connected": False, "error": str(e)}

    def _get_cpu_temperature(self) -> Optional[float]:
        """Get CPU temperature from RPi thermal zone"""
        try:
            with open('/sys/class/thermal/thermal_zone0/temp', 'r') as f:
                temp_str = f.read().strip()
                return float(temp_str) / 1000.0  # Convert millidegrees to degrees
        except:
            return None
```

## Shared Logger
```python
import logging
import logging.handlers
from pathlib import Path

def get_logger(app_id: str, level: str = "INFO") -> logging.Logger:
    """
    Get a centralized logger for HomeHelper apps
    Writes to shared location for dashboard integration
    """
    logger = logging.getLogger(f"homehelper.{app_id}")
    
    if logger.handlers:
        return logger  # Already configured
    
    logger.setLevel(getattr(logging, level.upper()))
    
    # Ensure log directory exists
    log_dir = Path("/var/homehelper/logs")
    log_dir.mkdir(parents=True, exist_ok=True)
    
    # Rotating file handler
    log_file = log_dir / f"{app_id}.log"
    file_handler = logging.handlers.RotatingFileHandler(
        log_file, maxBytes=10*1024*1024, backupCount=5
    )
    
    # Consistent format for dashboard parsing
    formatter = logging.Formatter(
        '%(asctime)s - %(levelname)s - [%(name)s] - %(message)s'
    )
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)
    
    # Console for development
    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)
    
    return logger
```