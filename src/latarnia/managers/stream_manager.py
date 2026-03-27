"""
Stream Manager for Latarnia

Handles Redis Streams setup: creating streams for publishers, consumer groups
for subscribers, publisher collision detection, and cleanup on app unregistration.
"""

import logging
from typing import Dict, List, Optional

import redis
from redis.exceptions import RedisError, ResponseError

from ..core.config import ConfigManager


STREAM_PREFIX = "latarnia:streams:"


class PublisherCollisionError(Exception):
    """Raised when two apps try to publish to the same stream."""

    def __init__(self, stream_name: str, existing_app_id: str, new_app_id: str):
        self.stream_name = stream_name
        self.existing_app_id = existing_app_id
        self.new_app_id = new_app_id
        super().__init__(
            f"Publisher collision on stream '{stream_name}': "
            f"already owned by '{existing_app_id}', "
            f"cannot assign to '{new_app_id}'"
        )


class StreamSetupResult:
    """Result of setting up streams for an app."""

    def __init__(
        self,
        success: bool,
        consumer_groups: Optional[List[str]] = None,
        error_message: Optional[str] = None,
    ):
        self.success = success
        self.consumer_groups = consumer_groups or []
        self.error_message = error_message


class StreamManager:
    """Manages Redis Streams lifecycle for Latarnia apps.

    Responsibilities:
    - Create streams for publishers (with collision detection)
    - Create streams and consumer groups for subscribers
    - Track publisher ownership (stream_name -> app_id)
    - Clean up consumer groups when an app is unregistered
    """

    def __init__(self, config_manager: ConfigManager, redis_client: Optional[redis.Redis] = None):
        self.config_manager = config_manager
        self.logger = logging.getLogger("latarnia.stream_manager")

        # Publisher ownership map: stream_key -> app_id
        self._publisher_map: Dict[str, str] = {}

        # Subscriber tracking: app_id -> list of (stream_key, group_name)
        self._subscriber_groups: Dict[str, List[tuple]] = {}

        # Redis connection
        if redis_client is not None:
            self._redis = redis_client
        else:
            self._redis = None

    def _get_redis(self) -> redis.Redis:
        """Get or create a Redis connection."""
        if self._redis is None:
            redis_url = self.config_manager.get_redis_url()
            self._redis = redis.from_url(redis_url, decode_responses=True)
        return self._redis

    @staticmethod
    def stream_key(declared_name: str) -> str:
        """Convert a declared stream name to the full Redis key."""
        return f"{STREAM_PREFIX}{declared_name}"

    def setup_streams(
        self,
        app_name: str,
        app_id: str,
        publish_streams: List[str],
        subscribe_streams: List[str],
    ) -> StreamSetupResult:
        """Set up Redis streams for an app during discovery.

        For publish streams:
        - Check publisher collision (only one app may own a stream)
        - Create the stream via XGROUP CREATE ... MKSTREAM

        For subscribe streams:
        - Create stream if it doesn't exist
        - Create a consumer group named after the subscribing app_id

        Returns a StreamSetupResult with the list of consumer groups created.
        """
        r = self._get_redis()
        consumer_groups: List[str] = []

        try:
            # --- Publish streams ---
            for stream_name in publish_streams:
                key = self.stream_key(stream_name)

                # Check for publisher collision
                existing_owner = self._publisher_map.get(key)
                if existing_owner is not None and existing_owner != app_id:
                    raise PublisherCollisionError(stream_name, existing_owner, app_id)

                # Create the stream (XGROUP CREATE with MKSTREAM creates the
                # stream if it doesn't exist). We use a temporary internal group
                # just to trigger MKSTREAM; we delete it right after.
                self._ensure_stream_exists(r, key)

                # Record publisher ownership
                self._publisher_map[key] = app_id
                self.logger.info(
                    f"Registered publisher '{app_id}' for stream '{stream_name}' (key={key})"
                )

            # --- Subscribe streams ---
            for stream_name in subscribe_streams:
                key = self.stream_key(stream_name)

                # Ensure the stream exists
                self._ensure_stream_exists(r, key)

                # Create consumer group named after the subscribing app
                group_name = app_id
                try:
                    r.xgroup_create(key, group_name, id="0", mkstream=True)
                    self.logger.info(
                        f"Created consumer group '{group_name}' on stream '{stream_name}' (key={key})"
                    )
                except ResponseError as e:
                    if "BUSYGROUP" in str(e):
                        # Consumer group already exists — idempotent
                        self.logger.debug(
                            f"Consumer group '{group_name}' already exists on '{key}'"
                        )
                    else:
                        raise

                consumer_groups.append(group_name)

                # Track for cleanup
                if app_id not in self._subscriber_groups:
                    self._subscriber_groups[app_id] = []
                self._subscriber_groups[app_id].append((key, group_name))

            return StreamSetupResult(success=True, consumer_groups=consumer_groups)

        except PublisherCollisionError:
            raise
        except Exception as e:
            error_msg = f"Stream setup failed for app '{app_name}' ({app_id}): {e}"
            self.logger.error(error_msg)
            return StreamSetupResult(success=False, error_message=error_msg)

    def cleanup_app(self, app_id: str) -> None:
        """Clean up stream resources when an app is unregistered.

        - Destroy consumer groups owned by this app
        - Remove publisher ownership entries for this app
        - Does NOT delete streams (other consumers may exist)
        """
        r = self._get_redis()

        # Remove consumer groups for subscriptions
        groups = self._subscriber_groups.pop(app_id, [])
        for stream_key, group_name in groups:
            try:
                r.xgroup_destroy(stream_key, group_name)
                self.logger.info(
                    f"Destroyed consumer group '{group_name}' on stream '{stream_key}'"
                )
            except ResponseError as e:
                # Group may have been removed externally — not fatal
                self.logger.warning(
                    f"Could not destroy consumer group '{group_name}' on '{stream_key}': {e}"
                )

        # Remove publisher ownership
        keys_to_remove = [
            key for key, owner in self._publisher_map.items() if owner == app_id
        ]
        for key in keys_to_remove:
            del self._publisher_map[key]
            self.logger.info(f"Removed publisher ownership for '{key}' (app_id={app_id})")

    def get_publisher_map(self) -> Dict[str, str]:
        """Return a copy of the publisher ownership map."""
        return dict(self._publisher_map)

    def _ensure_stream_exists(self, r: redis.Redis, key: str) -> None:
        """Ensure a stream exists in Redis by adding a sentinel entry if needed."""
        try:
            stream_info = r.xinfo_stream(key)
            # Stream already exists
            self.logger.debug(f"Stream '{key}' already exists")
        except ResponseError:
            # Stream doesn't exist — create it by adding and deleting a sentinel
            entry_id = r.xadd(key, {"__init__": "1"})
            r.xdel(key, entry_id)
            self.logger.debug(f"Created stream '{key}'")
