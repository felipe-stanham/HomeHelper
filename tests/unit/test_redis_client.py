"""
Unit tests for Redis message bus client
"""
import pytest
import json
import time
from unittest.mock import patch, MagicMock
import redis

from homehelper.core.redis_client import RedisMessageBusClient, RedisHealthMonitor


class TestRedisMessageBusClient:
    """Test Redis message bus client functionality"""
    
    def setup_method(self):
        """Setup test instance"""
        self.client = RedisMessageBusClient("test_app", "redis://localhost:6379/0")
    
    @patch('redis.from_url')
    def test_connect_success(self, mock_redis):
        """Test successful Redis connection"""
        mock_redis_instance = MagicMock()
        mock_redis_instance.ping.return_value = True
        mock_redis.return_value = mock_redis_instance
        
        result = self.client.connect()
        
        assert result is True
        assert self.client._connected is True
        mock_redis_instance.ping.assert_called_once()
    
    @patch('redis.from_url')
    def test_connect_failure(self, mock_redis):
        """Test Redis connection failure"""
        mock_redis.side_effect = redis.ConnectionError("Connection failed")
        
        result = self.client.connect()
        
        assert result is False
        assert self.client._connected is False
    
    def test_is_connected_true(self):
        """Test connection check when connected"""
        self.client._connected = True
        self.client.redis = MagicMock()
        self.client.redis.ping.return_value = True
        
        result = self.client.is_connected()
        
        assert result is True
    
    def test_is_connected_false_not_connected(self):
        """Test connection check when not connected"""
        self.client._connected = False
        
        result = self.client.is_connected()
        
        assert result is False
    
    def test_is_connected_false_ping_fails(self):
        """Test connection check when ping fails"""
        self.client._connected = True
        self.client.redis = MagicMock()
        self.client.redis.ping.side_effect = redis.ConnectionError()
        
        result = self.client.is_connected()
        
        assert result is False
        assert self.client._connected is False
    
    @patch('time.time')
    def test_publish_success(self, mock_time):
        """Test successful message publishing"""
        mock_time.return_value = 1234567890
        self.client._connected = True
        self.client.redis = MagicMock()
        self.client.redis.ping.return_value = True
        
        data = {"message": "Test event", "value": 42}
        result = self.client.publish("test_event", data, "info")
        
        assert result is True
        
        # Check that publish was called twice (specific channel + all events)
        assert self.client.redis.publish.call_count == 2
        
        # Check the message structure
        calls = self.client.redis.publish.call_args_list
        specific_channel_call = calls[0]
        all_events_call = calls[1]
        
        assert specific_channel_call[0][0] == "homehelper:events:test_event"
        assert all_events_call[0][0] == "homehelper:events:all"
        
        # Parse and check message content
        message_data = json.loads(specific_channel_call[0][1])
        assert message_data["timestamp"] == 1234567890
        assert message_data["source_app"] == "test_app"
        assert message_data["event_type"] == "test_event"
        assert message_data["severity"] == "info"
        assert message_data["data"] == data
    
    def test_publish_not_connected(self):
        """Test publishing when not connected"""
        self.client._connected = False
        
        result = self.client.publish("test_event", {})
        
        assert result is False
    
    def test_subscribe_success(self):
        """Test successful subscription"""
        self.client._connected = True
        self.client.redis = MagicMock()
        self.client.redis.ping.return_value = True
        self.client.pubsub = MagicMock()
        
        callback = MagicMock()
        result = self.client.subscribe("test_event", callback)
        
        assert result is True
        self.client.pubsub.subscribe.assert_called_once_with("homehelper:events:test_event")
        assert "homehelper:events:test_event" in self.client._subscriptions
    
    def test_subscribe_not_connected(self):
        """Test subscription when not connected"""
        self.client._connected = False
        
        callback = MagicMock()
        result = self.client.subscribe("test_event", callback)
        
        assert result is False
    
    def test_unsubscribe_success(self):
        """Test successful unsubscription"""
        self.client._connected = True
        self.client.redis = MagicMock()
        self.client.redis.ping.return_value = True
        self.client.pubsub = MagicMock()
        self.client._subscriptions["homehelper:events:test_event"] = MagicMock()
        
        result = self.client.unsubscribe("test_event")
        
        assert result is True
        self.client.pubsub.unsubscribe.assert_called_once_with("homehelper:events:test_event")
        assert "homehelper:events:test_event" not in self.client._subscriptions
    
    def test_get_health_connected(self):
        """Test health check when connected"""
        self.client._connected = True
        self.client.redis = MagicMock()
        self.client.redis.ping.return_value = True
        self.client.redis.info.return_value = {
            'used_memory': 10 * 1024 * 1024,  # 10MB
            'used_memory_peak': 20 * 1024 * 1024,  # 20MB
            'uptime_in_seconds': 3600,
            'total_commands_processed': 1000,
            'connected_clients': 5
        }
        self.client._subscriptions = {"test": MagicMock()}
        
        health = self.client.get_health()
        
        assert health["connected"] is True
        assert health["memory_used_mb"] == 10
        assert health["memory_peak_mb"] == 20
        assert health["uptime_seconds"] == 3600
        assert health["total_commands"] == 1000
        assert health["connected_clients"] == 5
        assert health["subscriptions"] == 1
    
    def test_get_health_not_connected(self):
        """Test health check when not connected"""
        self.client._connected = False
        
        health = self.client.get_health()
        
        assert health["connected"] is False
        assert "error" in health
    
    def test_disconnect(self):
        """Test disconnection cleanup"""
        self.client._connected = True
        self.client.pubsub = MagicMock()
        self.client.redis = MagicMock()
        self.client._listener_thread = MagicMock()
        self.client._listener_thread.is_alive.return_value = False
        
        self.client.disconnect()
        
        assert self.client._connected is False
        self.client.pubsub.close.assert_called_once()
        self.client.redis.close.assert_called_once()


class TestRedisHealthMonitor:
    """Test Redis health monitoring functionality"""
    
    def setup_method(self):
        """Setup test instance"""
        self.monitor = RedisHealthMonitor("redis://localhost:6379/0")
    
    @patch('redis.from_url')
    def test_get_redis_metrics_success(self, mock_redis):
        """Test successful Redis metrics collection"""
        mock_redis_instance = MagicMock()
        mock_redis_instance.ping.return_value = True
        mock_redis_instance.info.return_value = {
            'used_memory': 50 * 1024 * 1024,  # 50MB
            'used_memory_peak': 100 * 1024 * 1024,  # 100MB
            'used_memory_rss': 60 * 1024 * 1024,  # 60MB
            'total_commands_processed': 5000,
            'connected_clients': 10,
            'uptime_in_seconds': 7200,
            'keyspace_hits': 1000,
            'keyspace_misses': 100
        }
        mock_redis_instance.pubsub_channels.return_value = [
            b'homehelper:events:test1',
            b'homehelper:events:test2'
        ]
        mock_redis.return_value = mock_redis_instance
        
        metrics = self.monitor.get_redis_metrics()
        
        assert metrics["status"] == "connected"
        assert metrics["memory"]["used_mb"] == 50
        assert metrics["memory"]["peak_mb"] == 100
        assert metrics["memory"]["rss_mb"] == 60
        assert metrics["stats"]["total_commands"] == 5000
        assert metrics["stats"]["connected_clients"] == 10
        assert metrics["stats"]["uptime_seconds"] == 7200
        assert metrics["stats"]["keyspace_hits"] == 1000
        assert metrics["stats"]["keyspace_misses"] == 100
        assert len(metrics["channels"]) == 2
        assert "homehelper:events:test1" in metrics["channels"]
        assert "homehelper:events:test2" in metrics["channels"]
    
    @patch('redis.from_url')
    def test_get_redis_metrics_failure(self, mock_redis):
        """Test Redis metrics collection failure"""
        mock_redis.side_effect = redis.ConnectionError("Connection failed")
        
        metrics = self.monitor.get_redis_metrics()
        
        assert metrics["status"] == "error"
        assert "error" in metrics
        assert metrics["error"] == "Connection failed"
