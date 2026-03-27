"""
Unit tests for StreamManager — mocks Redis.
"""
import pytest
from unittest.mock import Mock, patch, MagicMock, call
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "src"))

from redis.exceptions import ResponseError

from latarnia.core.config import ConfigManager
from latarnia.managers.stream_manager import (
    StreamManager,
    PublisherCollisionError,
    StreamSetupResult,
    STREAM_PREFIX,
)


@pytest.fixture
def mock_config_manager():
    cm = Mock(spec=ConfigManager)
    cm.get_redis_url.return_value = "redis://localhost:6379/0"
    return cm


@pytest.fixture
def mock_redis():
    r = MagicMock()
    # xinfo_stream raises ResponseError when stream doesn't exist
    r.xinfo_stream.side_effect = ResponseError("no such key")
    r.xadd.return_value = "1234567890-0"
    return r


@pytest.fixture
def stream_manager(mock_config_manager, mock_redis):
    sm = StreamManager(mock_config_manager, redis_client=mock_redis)
    return sm


class TestStreamKey:

    def test_stream_key_format(self):
        assert StreamManager.stream_key("crm.contacts.created") == (
            "latarnia:streams:crm.contacts.created"
        )

    def test_stream_key_simple(self):
        assert StreamManager.stream_key("events") == "latarnia:streams:events"


class TestSetupPublishStreams:

    def test_publish_stream_creates_stream(self, stream_manager, mock_redis):
        result = stream_manager.setup_streams(
            "crm", "crm-app", ["crm.contacts.created"], []
        )

        assert result.success is True
        # Stream should be created via xadd + xdel
        key = f"{STREAM_PREFIX}crm.contacts.created"
        mock_redis.xadd.assert_called_once_with(key, {"__init__": "1"})
        mock_redis.xdel.assert_called_once_with(key, "1234567890-0")

    def test_publish_stream_records_publisher(self, stream_manager, mock_redis):
        stream_manager.setup_streams(
            "crm", "crm-app", ["crm.contacts.created"], []
        )

        pub_map = stream_manager.get_publisher_map()
        key = f"{STREAM_PREFIX}crm.contacts.created"
        assert pub_map[key] == "crm-app"

    def test_publish_stream_existing_stream(self, stream_manager, mock_redis):
        """When stream already exists, xinfo_stream succeeds and no xadd is needed."""
        mock_redis.xinfo_stream.side_effect = None
        mock_redis.xinfo_stream.return_value = {"length": 0}

        result = stream_manager.setup_streams(
            "crm", "crm-app", ["crm.contacts.created"], []
        )

        assert result.success is True
        mock_redis.xadd.assert_not_called()

    def test_publisher_collision_error(self, stream_manager, mock_redis):
        """Second app trying to publish to same stream raises collision."""
        stream_manager.setup_streams(
            "crm", "crm-app", ["crm.contacts.created"], []
        )

        with pytest.raises(PublisherCollisionError) as exc_info:
            stream_manager.setup_streams(
                "other", "other-app", ["crm.contacts.created"], []
            )

        assert exc_info.value.stream_name == "crm.contacts.created"
        assert exc_info.value.existing_app_id == "crm-app"
        assert exc_info.value.new_app_id == "other-app"

    def test_same_app_re_register_no_collision(self, stream_manager, mock_redis):
        """Re-registering the same app for the same stream is idempotent."""
        stream_manager.setup_streams(
            "crm", "crm-app", ["crm.contacts.created"], []
        )

        # Same app_id should not raise
        result = stream_manager.setup_streams(
            "crm", "crm-app", ["crm.contacts.created"], []
        )
        assert result.success is True

    def test_multiple_publish_streams(self, stream_manager, mock_redis):
        result = stream_manager.setup_streams(
            "crm", "crm-app",
            ["crm.contacts.created", "crm.contacts.updated"],
            [],
        )

        assert result.success is True
        pub_map = stream_manager.get_publisher_map()
        assert len(pub_map) == 2
        assert pub_map[f"{STREAM_PREFIX}crm.contacts.created"] == "crm-app"
        assert pub_map[f"{STREAM_PREFIX}crm.contacts.updated"] == "crm-app"


class TestSetupSubscribeStreams:

    def test_subscribe_creates_consumer_group(self, stream_manager, mock_redis):
        result = stream_manager.setup_streams(
            "dashboard", "dashboard-app", [], ["crm.contacts.created"]
        )

        assert result.success is True
        assert result.consumer_groups == ["dashboard-app"]

        key = f"{STREAM_PREFIX}crm.contacts.created"
        mock_redis.xgroup_create.assert_called_once_with(
            key, "dashboard-app", id="0", mkstream=True
        )

    def test_subscribe_existing_group_idempotent(self, stream_manager, mock_redis):
        """BUSYGROUP error is handled gracefully."""
        mock_redis.xgroup_create.side_effect = ResponseError(
            "BUSYGROUP Consumer Group name already exists"
        )

        result = stream_manager.setup_streams(
            "dashboard", "dashboard-app", [], ["crm.contacts.created"]
        )

        assert result.success is True
        assert result.consumer_groups == ["dashboard-app"]

    def test_subscribe_non_busygroup_error_fails(self, stream_manager, mock_redis):
        """Non-BUSYGROUP ResponseError propagates as failure."""
        mock_redis.xgroup_create.side_effect = ResponseError("some other error")

        result = stream_manager.setup_streams(
            "dashboard", "dashboard-app", [], ["crm.contacts.created"]
        )

        assert result.success is False
        assert "some other error" in result.error_message

    def test_multiple_subscribe_streams(self, stream_manager, mock_redis):
        result = stream_manager.setup_streams(
            "dashboard", "dashboard-app",
            [],
            ["crm.contacts.created", "crm.contacts.updated"],
        )

        assert result.success is True
        assert result.consumer_groups == ["dashboard-app", "dashboard-app"]
        assert mock_redis.xgroup_create.call_count == 2


class TestSetupMixed:

    def test_publish_and_subscribe(self, stream_manager, mock_redis):
        """App can both publish and subscribe to different streams."""
        result = stream_manager.setup_streams(
            "crm", "crm-app",
            ["crm.contacts.created"],
            ["notifications.send"],
        )

        assert result.success is True
        assert result.consumer_groups == ["crm-app"]
        pub_map = stream_manager.get_publisher_map()
        assert f"{STREAM_PREFIX}crm.contacts.created" in pub_map


class TestCleanupApp:

    def test_cleanup_removes_consumer_groups(self, stream_manager, mock_redis):
        # Setup subscriptions first
        stream_manager.setup_streams(
            "dashboard", "dashboard-app", [], ["crm.contacts.created"]
        )

        stream_manager.cleanup_app("dashboard-app")

        key = f"{STREAM_PREFIX}crm.contacts.created"
        mock_redis.xgroup_destroy.assert_called_once_with(key, "dashboard-app")

    def test_cleanup_removes_publisher_ownership(self, stream_manager, mock_redis):
        stream_manager.setup_streams(
            "crm", "crm-app", ["crm.contacts.created"], []
        )

        stream_manager.cleanup_app("crm-app")

        assert stream_manager.get_publisher_map() == {}

    def test_cleanup_does_not_delete_stream(self, stream_manager, mock_redis):
        """Cleanup must NOT delete the stream itself."""
        stream_manager.setup_streams(
            "crm", "crm-app", ["crm.contacts.created"], []
        )

        stream_manager.cleanup_app("crm-app")

        mock_redis.delete.assert_not_called()

    def test_cleanup_unknown_app_is_noop(self, stream_manager, mock_redis):
        """Cleaning up an app with no stream resources is a no-op."""
        stream_manager.cleanup_app("nonexistent-app")

        mock_redis.xgroup_destroy.assert_not_called()

    def test_cleanup_handles_group_already_removed(self, stream_manager, mock_redis):
        """If the consumer group was already deleted externally, cleanup warns but succeeds."""
        stream_manager.setup_streams(
            "dashboard", "dashboard-app", [], ["crm.contacts.created"]
        )
        mock_redis.xgroup_destroy.side_effect = ResponseError("no such group")

        # Should not raise
        stream_manager.cleanup_app("dashboard-app")

    def test_cleanup_publisher_allows_new_publisher(self, stream_manager, mock_redis):
        """After cleaning up a publisher, another app can claim the stream."""
        stream_manager.setup_streams(
            "crm", "crm-app", ["crm.contacts.created"], []
        )
        stream_manager.cleanup_app("crm-app")

        # New app should be able to publish
        result = stream_manager.setup_streams(
            "crm2", "crm2-app", ["crm.contacts.created"], []
        )
        assert result.success is True
        assert stream_manager.get_publisher_map()[
            f"{STREAM_PREFIX}crm.contacts.created"
        ] == "crm2-app"

    def test_cleanup_mixed_app(self, stream_manager, mock_redis):
        """App with both publish and subscribe streams is fully cleaned up."""
        stream_manager.setup_streams(
            "crm", "crm-app",
            ["crm.contacts.created"],
            ["notifications.send"],
        )

        stream_manager.cleanup_app("crm-app")

        assert stream_manager.get_publisher_map() == {}
        mock_redis.xgroup_destroy.assert_called_once()


class TestRedisConnectionLazy:

    def test_uses_injected_redis(self, mock_config_manager):
        """When redis_client is injected, it's used directly."""
        mock_redis = MagicMock()
        sm = StreamManager(mock_config_manager, redis_client=mock_redis)
        assert sm._get_redis() is mock_redis

    def test_creates_redis_from_config(self, mock_config_manager):
        """When no redis_client injected, one is created from config."""
        sm = StreamManager(mock_config_manager)
        with patch("latarnia.managers.stream_manager.redis.from_url") as mock_from_url:
            mock_from_url.return_value = MagicMock()
            client = sm._get_redis()
            mock_from_url.assert_called_once_with(
                "redis://localhost:6379/0", decode_responses=True
            )
