"""
Redis Event Subscriber for HomeHelper

Subscribes to Redis pub/sub channels and stores recent events for dashboard display.
"""
import json
import logging
import threading
import time
from typing import Optional

import redis


class RedisEventSubscriber:
    """Background subscriber that listens to Redis pub/sub channels"""
    
    def __init__(self, redis_url: str, max_events: int = 100):
        self.redis_url = redis_url
        self.max_events = max_events
        self.logger = logging.getLogger("homehelper.event_subscriber")
        
        self.redis_client: Optional[redis.Redis] = None
        self.pubsub: Optional[redis.client.PubSub] = None
        self.subscriber_thread: Optional[threading.Thread] = None
        self.shutdown_event = threading.Event()
        self.running = False
    
    def start(self):
        """Start the background subscriber thread"""
        if self.running:
            self.logger.warning("Event subscriber is already running")
            return
        
        try:
            # Connect to Redis
            self.redis_client = redis.from_url(self.redis_url, decode_responses=False)
            self.redis_client.ping()
            
            # Create pub/sub instance
            self.pubsub = self.redis_client.pubsub()
            
            # Subscribe to all homehelper event channels
            self.pubsub.psubscribe("homehelper:events:*")
            
            self.logger.info("Subscribed to homehelper:events:* channels")
            
            # Start background thread
            self.subscriber_thread = threading.Thread(
                target=self._subscriber_loop,
                daemon=True,
                name="RedisEventSubscriber"
            )
            self.subscriber_thread.start()
            self.running = True
            
            self.logger.info("Redis event subscriber started")
            
        except Exception as e:
            self.logger.error(f"Failed to start event subscriber: {e}")
            self.running = False
    
    def stop(self):
        """Stop the background subscriber thread"""
        if not self.running:
            return
        
        self.logger.info("Stopping Redis event subscriber...")
        self.shutdown_event.set()
        
        if self.subscriber_thread and self.subscriber_thread.is_alive():
            self.subscriber_thread.join(timeout=5)
        
        if self.pubsub:
            try:
                self.pubsub.close()
            except:
                pass
        
        if self.redis_client:
            try:
                self.redis_client.close()
            except:
                pass
        
        self.running = False
        self.logger.info("Redis event subscriber stopped")
    
    def _subscriber_loop(self):
        """Background loop that processes pub/sub messages"""
        self.logger.info("Event subscriber loop started")
        
        while not self.shutdown_event.is_set():
            try:
                # Get message with timeout
                message = self.pubsub.get_message(timeout=1.0)
                
                if message and message['type'] == 'pmessage':
                    # Process the event
                    self._process_event(message)
                
            except Exception as e:
                self.logger.error(f"Error in subscriber loop: {e}")
                time.sleep(1)
        
        self.logger.info("Event subscriber loop stopped")
    
    def _process_event(self, message):
        """Process a received pub/sub message and store it"""
        try:
            # Extract event data
            channel = message['channel'].decode('utf-8') if isinstance(message['channel'], bytes) else message['channel']
            data = message['data']
            
            if isinstance(data, bytes):
                data = data.decode('utf-8')
            
            # Parse JSON
            event_data = json.loads(data)
            
            # Store in recent events list
            events_key = "homehelper:events:recent"
            
            # Add to list
            self.redis_client.rpush(events_key, json.dumps(event_data))
            
            # Trim list to max size (keep only the most recent)
            self.redis_client.ltrim(events_key, -self.max_events, -1)
            
            self.logger.debug(f"Stored event from channel {channel}")
            
        except Exception as e:
            self.logger.error(f"Failed to process event: {e}")
