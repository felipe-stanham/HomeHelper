"""
Integration test: two apps with publish/subscribe relationship.

Verifies streams and consumer groups are created correctly in a real Redis.
Skip if Redis is not available.
"""
import pytest
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "src"))

import redis as redis_lib
from redis.exceptions import ConnectionError as RedisConnectionError

from latarnia.core.config import ConfigManager
from latarnia.managers.stream_manager import (
    StreamManager,
    PublisherCollisionError,
    STREAM_PREFIX,
)


def _redis_available() -> bool:
    """Check if a local Redis server is running."""
    try:
        r = redis_lib.Redis(host="localhost", port=6379, db=15, decode_responses=True)
        r.ping()
        r.close()
        return True
    except (RedisConnectionError, OSError):
        return False


# Use DB 15 to avoid conflicts with development data
REDIS_TEST_URL = "redis://localhost:6379/15"

pytestmark = pytest.mark.skipif(
    not _redis_available(), reason="Redis not available on localhost:6379"
)


@pytest.fixture
def redis_client():
    """Provide a Redis connection on DB 15, flush it before and after the test."""
    r = redis_lib.Redis(host="localhost", port=6379, db=15, decode_responses=True)
    r.flushdb()
    yield r
    r.flushdb()
    r.close()


@pytest.fixture
def mock_config_manager():
    cm = ConfigManager.__new__(ConfigManager)
    cm._config = None
    cm.logger = __import__("logging").getLogger("test")
    cm.config_path = Path("/dev/null")
    # Override get_redis_url
    cm.get_redis_url = lambda: REDIS_TEST_URL
    return cm


@pytest.fixture
def stream_manager(mock_config_manager, redis_client):
    return StreamManager(mock_config_manager, redis_client=redis_client)


class TestTwoAppPublishSubscribe:
    """Integration: CRM publishes, Dashboard subscribes."""

    def test_full_lifecycle(self, stream_manager, redis_client):
        # --- Step 1: Register CRM as publisher ---
        result_crm = stream_manager.setup_streams(
            "crm", "crm-app", ["crm.contacts.created"], []
        )
        assert result_crm.success is True

        # Verify stream exists in Redis
        key = f"{STREAM_PREFIX}crm.contacts.created"
        assert redis_client.exists(key) == 1
        stream_info = redis_client.xinfo_stream(key)
        assert stream_info is not None

        # --- Step 2: Register Dashboard as subscriber ---
        result_dash = stream_manager.setup_streams(
            "dashboard", "dashboard-app", [], ["crm.contacts.created"]
        )
        assert result_dash.success is True
        assert result_dash.consumer_groups == ["dashboard-app"]

        # Verify consumer group exists
        groups = redis_client.xinfo_groups(key)
        group_names = [g["name"] for g in groups]
        assert "dashboard-app" in group_names

        # --- Step 3: Verify publisher collision ---
        with pytest.raises(PublisherCollisionError):
            stream_manager.setup_streams(
                "other", "other-app", ["crm.contacts.created"], []
            )

        # --- Step 4: Verify XADD works ---
        entry_id = redis_client.xadd(key, {"contact_id": "123", "action": "created"})
        assert entry_id is not None

        # --- Step 5: Verify XREADGROUP works ---
        messages = redis_client.xreadgroup(
            "dashboard-app", "consumer-1", {key: ">"}, count=10
        )
        assert len(messages) == 1
        stream_key, entries = messages[0]
        assert len(entries) == 1
        msg_id, msg_data = entries[0]
        assert msg_data["contact_id"] == "123"

        # --- Step 6: Verify XACK works ---
        ack_count = redis_client.xack(key, "dashboard-app", msg_id)
        assert ack_count == 1

        # --- Step 7: Unregister dashboard, verify group destroyed ---
        stream_manager.cleanup_app("dashboard-app")
        groups_after = redis_client.xinfo_groups(key)
        group_names_after = [g["name"] for g in groups_after]
        assert "dashboard-app" not in group_names_after

        # Stream still exists (not deleted)
        assert redis_client.exists(key) == 1

        # --- Step 8: Unregister CRM, verify ownership released ---
        stream_manager.cleanup_app("crm-app")
        assert stream_manager.get_publisher_map() == {}

        # Stream still exists
        assert redis_client.exists(key) == 1

    def test_multiple_subscribers(self, stream_manager, redis_client):
        """Multiple apps can subscribe to the same stream."""
        stream_manager.setup_streams(
            "crm", "crm-app", ["crm.contacts.created"], []
        )

        result_a = stream_manager.setup_streams(
            "app-a", "app-a-id", [], ["crm.contacts.created"]
        )
        result_b = stream_manager.setup_streams(
            "app-b", "app-b-id", [], ["crm.contacts.created"]
        )

        assert result_a.success is True
        assert result_b.success is True

        key = f"{STREAM_PREFIX}crm.contacts.created"
        groups = redis_client.xinfo_groups(key)
        group_names = {g["name"] for g in groups}
        assert "app-a-id" in group_names
        assert "app-b-id" in group_names

    def test_subscriber_before_publisher(self, stream_manager, redis_client):
        """A subscriber can register before any publisher — stream is created."""
        result = stream_manager.setup_streams(
            "dashboard", "dashboard-app", [], ["future.events"]
        )

        assert result.success is True
        key = f"{STREAM_PREFIX}future.events"
        assert redis_client.exists(key) == 1
