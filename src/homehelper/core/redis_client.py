"""
Redis message bus client for HomeHelper
"""
import json
import logging
import time
import threading
from typing import Dict, Any, Callable, Optional, List
import redis
from redis.exceptions import RedisError, ConnectionError


class RedisMessageBusClient:
    """Enhanced Redis message bus client for HomeHelper apps"""
    
    def __init__(self, app_id: str, redis_url: str = "redis://localhost:6379/0"):
        self.app_id = app_id
        self.redis_url = redis_url
        self.redis: Optional[redis.Redis] = None
        self.pubsub: Optional[redis.client.PubSub] = None
        self.logger = logging.getLogger(f"homehelper.{app_id}.message_bus")
        self._connected = False
        self._subscriptions: Dict[str, Callable] = {}
        self._listener_thread: Optional[threading.Thread] = None
        self._stop_listening = threading.Event()
        
    def connect(self) -> bool:
        """Establish Redis connection"""
        try:
            self.redis = redis.from_url(self.redis_url, decode_responses=True)
            self.redis.ping()
            self.pubsub = self.redis.pubsub()
            self._connected = True
            self.logger.info(f"Connected to Redis at {self.redis_url}")
            return True
        except (RedisError, ConnectionError) as e:
            self.logger.error(f"Failed to connect to Redis: {e}")
            self._connected = False
            return False
    
    def disconnect(self) -> None:
        """Close Redis connection and stop listening"""
        self._stop_listening.set()
        
        if self._listener_thread and self._listener_thread.is_alive():
            self._listener_thread.join(timeout=5)
        
        if self.pubsub:
            self.pubsub.close()
            
        if self.redis:
            self.redis.close()
            
        self._connected = False
        self.logger.info("Disconnected from Redis")
    
    def is_connected(self) -> bool:
        """Check if Redis connection is active"""
        if not self._connected or not self.redis:
            return False
        
        try:
            self.redis.ping()
            return True
        except (RedisError, ConnectionError):
            self._connected = False
            return False
    
    def publish(self, event_type: str, data: Dict[str, Any], severity: str = "info") -> bool:
        """Publish event to the message bus"""
        if not self.is_connected():
            self.logger.error("Cannot publish: not connected to Redis")
            return False
        
        channel = f"homehelper:events:{event_type}"
        message = {
            "timestamp": int(time.time()),
            "source_app": self.app_id,
            "event_type": event_type,
            "severity": severity,
            "message": data.get("message", ""),
            "data": data
        }
        
        try:
            # Publish to specific event channel
            self.redis.publish(channel, json.dumps(message))
            # Also publish to general events channel for main app
            self.redis.publish("homehelper:events:all", json.dumps(message))
            
            self.logger.debug(f"Published {event_type} to {channel}")
            return True
        except (RedisError, ConnectionError) as e:
            self.logger.error(f"Failed to publish {event_type}: {e}")
            return False
    
    def subscribe(self, event_type: str, callback: Callable[[Dict], None]) -> bool:
        """Subscribe to an event type"""
        if not self.is_connected():
            self.logger.error("Cannot subscribe: not connected to Redis")
            return False
        
        channel = f"homehelper:events:{event_type}"
        self._subscriptions[channel] = callback
        
        try:
            self.pubsub.subscribe(channel)
            self.logger.info(f"Subscribed to {event_type}")
            
            # Start listener thread if not already running
            if not self._listener_thread or not self._listener_thread.is_alive():
                self._start_listener()
            
            return True
        except (RedisError, ConnectionError) as e:
            self.logger.error(f"Failed to subscribe to {event_type}: {e}")
            return False
    
    def unsubscribe(self, event_type: str) -> bool:
        """Unsubscribe from an event type"""
        if not self.is_connected():
            return False
        
        channel = f"homehelper:events:{event_type}"
        
        try:
            self.pubsub.unsubscribe(channel)
            if channel in self._subscriptions:
                del self._subscriptions[channel]
            self.logger.info(f"Unsubscribed from {event_type}")
            return True
        except (RedisError, ConnectionError) as e:
            self.logger.error(f"Failed to unsubscribe from {event_type}: {e}")
            return False
    
    def _start_listener(self) -> None:
        """Start background thread to handle incoming messages"""
        self._stop_listening.clear()
        self._listener_thread = threading.Thread(
            target=self._message_listener,
            daemon=True,
            name=f"redis-listener-{self.app_id}"
        )
        self._listener_thread.start()
        self.logger.debug("Started Redis message listener thread")
    
    def _message_listener(self) -> None:
        """Background thread to handle incoming Redis messages"""
        try:
            for message in self.pubsub.listen():
                if self._stop_listening.is_set():
                    break
                
                if message['type'] == 'message':
                    channel = message['channel']
                    if channel in self._subscriptions:
                        try:
                            data = json.loads(message['data'])
                            callback = self._subscriptions[channel]
                            callback(data)
                        except Exception as e:
                            self.logger.error(f"Error processing message from {channel}: {e}")
        except Exception as e:
            self.logger.error(f"Redis listener thread error: {e}")
        finally:
            self.logger.debug("Redis message listener thread stopped")
    
    def get_health(self) -> Dict[str, Any]:
        """Get Redis connection health information"""
        if not self.is_connected():
            return {
                "connected": False,
                "error": "Not connected to Redis"
            }
        
        try:
            info = self.redis.info()
            return {
                "connected": True,
                "memory_used_mb": info.get('used_memory', 0) // (1024 * 1024),
                "memory_peak_mb": info.get('used_memory_peak', 0) // (1024 * 1024),
                "uptime_seconds": info.get('uptime_in_seconds', 0),
                "total_commands": info.get('total_commands_processed', 0),
                "connected_clients": info.get('connected_clients', 0),
                "subscriptions": len(self._subscriptions)
            }
        except (RedisError, ConnectionError) as e:
            return {
                "connected": False,
                "error": str(e)
            }
    
    def get_active_channels(self) -> List[str]:
        """Get list of active Redis channels"""
        if not self.is_connected():
            return []
        
        try:
            channels = self.redis.pubsub_channels("homehelper:events:*")
            return [ch.decode() if isinstance(ch, bytes) else ch for ch in channels]
        except (RedisError, ConnectionError):
            return []


class RedisHealthMonitor:
    """Monitor Redis health for the main application"""
    
    def __init__(self, redis_url: str = "redis://localhost:6379/0"):
        self.redis_url = redis_url
        self.logger = logging.getLogger("homehelper.redis_health")
    
    def get_redis_metrics(self) -> Dict[str, Any]:
        """Get comprehensive Redis metrics"""
        try:
            redis_client = redis.from_url(self.redis_url, decode_responses=True)
            redis_client.ping()
            
            info = redis_client.info()
            
            return {
                "status": "connected",
                "memory": {
                    "used_mb": info.get('used_memory', 0) // (1024 * 1024),
                    "peak_mb": info.get('used_memory_peak', 0) // (1024 * 1024),
                    "rss_mb": info.get('used_memory_rss', 0) // (1024 * 1024)
                },
                "stats": {
                    "total_commands": info.get('total_commands_processed', 0),
                    "connected_clients": info.get('connected_clients', 0),
                    "uptime_seconds": info.get('uptime_in_seconds', 0),
                    "keyspace_hits": info.get('keyspace_hits', 0),
                    "keyspace_misses": info.get('keyspace_misses', 0)
                },
                "channels": self._get_active_channels(redis_client)
            }
        except Exception as e:
            return {
                "status": "error",
                "error": str(e)
            }
    
    def _get_active_channels(self, redis_client: redis.Redis) -> List[str]:
        """Get list of active HomeHelper channels"""
        try:
            channels = redis_client.pubsub_channels("homehelper:events:*")
            return [ch.decode() if isinstance(ch, bytes) else ch for ch in channels]
        except Exception:
            return []
