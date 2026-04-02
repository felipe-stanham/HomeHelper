# Regression Tests

Critical-path tests for Latarnia. Each test is declarative — Claude Code generates verification scripts on the fly.

## Core Infrastructure

- **test_config_load_from_json:** Create a temporary JSON config file with `{"redis": {"host": "testhost", "port": 6380}, "system": {"main_port": 9000}}`. Instantiate `ConfigManager` with that path and call `load_config()`. -> Config object has `redis.host == "testhost"`, `redis.port == 6380`, `system.main_port == 9000`.

- **test_config_defaults_on_missing_file:** Instantiate `ConfigManager` with a non-existent path `/tmp/nonexistent_hh_config.json` and call `load_config()`. -> Config uses defaults: `redis.host == "localhost"`, `redis.port == 6379`, `system.main_port == 8000`, `health_check_interval_seconds == 60`.

- **test_config_port_range_values:** Create `LatarniaConfig()` with defaults. -> `process_manager.port_range.start == 8100` and `process_manager.port_range.end == 8199`.

- **test_config_redis_url_generation:** Instantiate `ConfigManager()`, call `load_config()`, then `get_redis_url()`. -> Returns `"redis://localhost:6379/0"`.

- **test_redis_client_connect_success:** Create `RedisMessageBusClient("test", "redis://localhost:6379/0")`. Mock `redis.from_url` to return a mock that responds to `ping()` with `True`. Call `client.connect()`. -> Returns `True` and `client._connected is True`.

- **test_redis_client_connect_failure:** Create `RedisMessageBusClient("test", "redis://localhost:6379/0")`. Mock `redis.from_url` to raise `redis.ConnectionError`. Call `client.connect()`. -> Returns `False` and `client._connected is False`.

- **test_redis_health_monitor_connected:** Create `RedisHealthMonitor("redis://localhost:6379/0")`. Mock `redis.from_url` to return a mock with `ping() -> True` and `info()` returning `{"used_memory": 52428800, "used_memory_peak": 104857600, "used_memory_rss": 62914560, "total_commands_processed": 5000, "connected_clients": 10, "uptime_in_seconds": 7200, "keyspace_hits": 1000, "keyspace_misses": 100}`, and `pubsub_channels()` returning two channels. Call `get_redis_metrics()`. -> Returns dict with `status == "connected"`, `memory.used_mb == 50`, `stats.connected_clients == 10`.

- **test_redis_health_monitor_disconnected:** Create `RedisHealthMonitor("redis://localhost:6379/0")`. Mock `redis.from_url` to raise `redis.ConnectionError("Connection failed")`. Call `get_redis_metrics()`. -> Returns dict with `status == "error"` and `error == "Connection failed"`.

- **test_system_monitor_cpu_metrics:** Create `SystemMonitor()`. Mock `psutil.cpu_percent` to return `25.5`, `os.getloadavg` to return `(0.8, 0.6, 0.9)`, `psutil.cpu_count` to return `4`. Call `_get_cpu_metrics()`. -> Returns dict with `usage_percent == 25.5`, `core_count == 4`, `load_avg_1m == 0.8`.

- **test_system_monitor_memory_metrics:** Create `SystemMonitor()`. Mock `psutil.virtual_memory` to return `total=8GB, used=6GB, available=2GB, percent=75.0, free=1GB`. Call `_get_memory_metrics()`. -> Returns dict with `total_mb == 8192`, `used_mb == 6144`, `percent == 75.0`.

- **test_system_monitor_status_good:** Create `SystemMonitor()`. Call `_determine_system_status` with hardware metrics: `cpu.usage_percent=50, memory.percent=60, disk.percent=70, temperature.cpu_celsius=45` and empty processes list. -> Returns `"good"`.

- **test_system_monitor_status_warning:** Create `SystemMonitor()`. Call `_determine_system_status` with hardware metrics: `cpu.usage_percent=85, memory.percent=60, disk.percent=70, temperature.cpu_celsius=45` and empty processes list. -> Returns `"warning"`.

## App Management

- **test_app_discovery_valid_manifest:** Create a temp directory structure with `apps/test-service/latarnia.json` containing `{"name": "test-service", "type": "service", "description": "Test", "version": "1.0.0", "author": "Test", "main_file": "app.py"}` and an `apps/test-service/app.py` file. Create `AppManager` with mocked config pointing to that temp dir. Call `discover_apps()`. -> Returns `1`. `registry.get_all_apps()` returns one entry with `name == "test-service"` and `type == AppType.SERVICE`.

- **test_app_discovery_invalid_manifest:** Create a temp directory with `apps/bad-app/latarnia.json` containing `{"name": "bad-app"}` (missing required fields). Call `discover_apps()`. -> Returns `0`. Registry is empty.

- **test_app_discovery_missing_main_file:** Create a temp directory with valid manifest referencing `nonexistent.py` as `main_file`, but do not create that file. Call `discover_apps()`. -> Returns `0`. Registry is empty.

- **test_app_registry_register_and_get:** Create an `AppRegistry` with mocked config. Register an `AppRegistryEntry` with `app_id="app-1"`. Call `get_app("app-1")`. -> Returns the same entry. Call `get_app("nonexistent")`. -> Returns `None`.

- **test_app_registry_get_all_apps:** Register two apps (one service, one streamlit) into `AppRegistry`. Call `get_all_apps()`. -> Returns list of length 2.

- **test_app_registry_filter_by_type:** Register one service app and one streamlit app. Call `get_apps_by_type(AppType.SERVICE)`. -> Returns list of length 1 with the service app. Call `get_apps_by_type(AppType.STREAMLIT)`. -> Returns list of length 1 with the streamlit app.

- **test_app_registry_unregister:** Register an app with `app_id="app-1"`. Call `unregister_app("app-1")`. -> Returns `True`. `get_app("app-1")` returns `None`.

- **test_manifest_version_validation:** Attempt to create `AppManifest` with `version="1.0"` (invalid semver). -> Raises validation error (pydantic `ValidationError`).

## Service Management

- **test_service_template_generation:** Create `ServiceManager` with mocked dependencies. Mock `registry.get_app` to return a service app entry at path `/tmp/test-service` with `assigned_port=8100`, `main_file="app.py"`, `restart_policy="always"`, `redis_required=True`, `data_dir=True`, `logs_dir=True`. Call `generate_service_template("test-service")`. -> Returns a string containing `"Description=Latarnia Service - test-service"`, `"ExecStart=python app.py --port 8100"`, `"Restart=always"`, `"Environment=REDIS_HOST=localhost"`.

- **test_service_template_no_app:** Create `ServiceManager`. Mock `registry.get_app` to return `None`. Call `generate_service_template("nonexistent")`. -> Returns `None`.

- **test_service_start_success:** Create `ServiceManager`. Mock `subprocess.run` to return `returncode=0`. Mock `registry.get_app` to return a valid service entry. Call `start_service("test-service")`. -> Returns `True`. Verify `subprocess.run` was called with `["systemctl", "--user", "start", "latarnia-test-service.service"]`. Verify `registry.update_app` was called with `status=AppStatus.RUNNING`.

- **test_service_start_failure:** Create `ServiceManager`. Mock `subprocess.run` to return `returncode=1, stderr="Service failed"`. Call `start_service("test-service")`. -> Returns `False`. Verify `registry.update_app` was called with `status=AppStatus.ERROR`.

- **test_service_stop_success:** Create `ServiceManager`. Mock `subprocess.run` to return `returncode=0`. Call `stop_service("test-service")`. -> Returns `True`. Verify `subprocess.run` was called with `["systemctl", "--user", "stop", "latarnia-test-service.service"]`.

- **test_service_restart_success:** Create `ServiceManager`. Mock `subprocess.run` to return `returncode=0`. Call `restart_service("test-service")`. -> Returns `True`. Verify `subprocess.run` was called with `["systemctl", "--user", "restart", "latarnia-test-service.service"]`.

## Web Dashboard

- **test_health_endpoint:** Use `httpx.AsyncClient` with FastAPI `TestClient` or ASGI transport against the `app` from `latarnia.main`. Mock `system_monitor.get_hardware_metrics()` to return `{"cpu": {"usage_percent": 30}, "memory": {"percent": 50}, "disk": {"percent": 40}}`. Mock `redis_monitor.get_redis_metrics()` to return `{"status": "connected"}`. Send GET to `/health`. -> Response status 200. JSON body has `health == "good"`, `message == "System operational"`, and `extra_info.config_loaded == True`.

- **test_health_endpoint_redis_down:** Mock `redis_monitor.get_redis_metrics()` to return `{"status": "error"}`. Mock `system_monitor.get_hardware_metrics()` to return valid metrics. Send GET to `/health`. -> Response status 200. JSON body has `health == "error"` and `message` contains `"Redis connection failed"`.

- **test_root_endpoint:** Send GET to `/`. -> Response status 200. JSON body has `message == "Latarnia is running"` and `version == "0.1.0"`.

- **test_get_all_apps_endpoint:** Mock `app_manager.registry.get_all_apps()` to return a list with one app entry (mocked `to_dict()` returning `{"app_id": "test-1", "name": "test"}`). Send GET to `/api/apps`. -> Response status 200. JSON body has `total_count == 1` and `apps` is a list of length 1.

- **test_get_app_not_found:** Mock `app_manager.registry.get_app("nonexistent")` to return `None`. Send GET to `/api/apps/nonexistent`. -> Response status 404.

- **test_system_metrics_endpoint:** Mock `system_monitor.get_system_summary()` to return `{"status": "good", "cpu": 30}`. Send GET to `/api/system/metrics`. -> Response status 200. JSON body has `status == "good"`.

## UI Integration

- **test_streamlit_launch_non_streamlit_app:** Mock `app_manager.registry.get_app("svc-1")` to return an entry with `type == "service"`. Send POST to `/api/apps/svc-1/streamlit/launch`. -> Response status 400 with detail `"App is not a Streamlit app"`.

- **test_streamlit_launch_app_not_found:** Mock `app_manager.registry.get_app("nonexistent")` to return `None`. Send POST to `/api/apps/nonexistent/streamlit/launch`. -> Response status 404.

- **test_streamlit_touch_extends_ttl:** In `StreamlitManager`, add a process entry for `app_id="st-1"` with `last_accessed` set to 5 minutes ago. Call `touch_app("st-1")`. -> The `processes["st-1"]["last_accessed"]` is updated to approximately `datetime.now()` (within 2 seconds).

## Port Management

- **test_port_allocation_within_range:** Create `PortManager` with config `port_range.start=8100, port_range.end=8105`. Mock `socket.socket.bind` to succeed. Call `allocate_port("app-1", "service")`. -> Returns a port between 8100 and 8105 inclusive. `app_ports["app-1"]` equals the returned port.

- **test_port_allocation_exhausted:** Create `PortManager` with config `port_range.start=8100, port_range.end=8105`. Mock `socket.socket.bind` to raise `OSError` for all ports. Call `allocate_port("app-1", "service")`. -> Returns `None`.

- **test_port_release:** Allocate a port for `"app-1"`. Call `release_port("app-1")`. -> Returns `True`. `get_app_port("app-1")` returns `None`. The port is no longer in `allocations`.

- **test_port_reuse_for_same_app:** Allocate a port for `"app-1"`. Call `allocate_port("app-1", "service")` again. -> Returns the same port as the first allocation.

- **test_port_statistics:** Create `PortManager` with range 8100-8105 (6 ports). Allocate ports for `"app1"` (service) and `"app2"` (streamlit). Call `get_port_statistics()`. -> Returns `total_ports == 6`, `allocated_ports == 2`, `utilization_percent == 33.3`, `app_type_breakdown.service == 1`, `app_type_breakdown.streamlit == 1`.

- **test_stale_port_cleanup:** Allocate a port for `"app-1"`. Set `allocation.allocated_at` to 2 hours ago. Mock socket bind to succeed (port is actually free). Call `cleanup_stale_allocations()`. -> Returns `1`. `"app-1"` is no longer in `app_ports`.

## MCP Gateway

- **test_mcp_config_defaults:** Create `MCPConfig()` with no arguments. -> `enabled == False`, `transport == "sse"`, `gateway_path == "/mcp"`, `tool_sync_interval_seconds == 300`.

- **test_mcp_gateway_tool_index_build:** Create `MCPGateway` with a mock `app_manager` whose registry returns one healthy MCP-enabled app (`mcp_info.enabled=True`, `mcp_info.healthy=True`, `mcp_info.mcp_port=9001`). Mock `mcp.client.sse.sse_client` and `ClientSession` to return two tools (`get_time`, `echo`). Call `await gateway._build_tool_index()`. -> `gateway._tool_index` has 2 entries with keys `"app_name.get_time"` and `"app_name.echo"`.

- **test_mcp_gateway_tool_index_skips_unhealthy:** Create `MCPGateway` with a mock `app_manager` whose registry returns one MCP-enabled app with `mcp_info.healthy=False`. Call `await gateway._build_tool_index()`. -> `gateway._tool_index` is empty.

- **test_mcp_gateway_list_tools:** Populate `gateway._tool_index` with 3 entries from 2 apps. Call `gateway._handle_list_tools()`. -> Returns a list of 3 `mcp.types.Tool` objects with namespaced names.

- **test_mcp_gateway_call_tool_success:** Populate `gateway._tool_index` with `"crm.add_contact"` pointing to app `crm` on port 9001. Mock registry to return healthy app. Mock `sse_client` + `ClientSession.call_tool` to return `CallToolResult(content=[TextContent(type="text", text="id=42")])`. Call `await gateway._handle_call_tool("crm.add_contact", {"name": "Alice"})`. -> Returns content list with text `"id=42"`.

- **test_mcp_gateway_call_tool_unknown:** Call `await gateway._handle_call_tool("unknown.tool", {})` with empty index. -> Returns list with one `TextContent` containing `"Error: Unknown tool"`.

- **test_mcp_gateway_call_tool_unhealthy:** Populate index with `"crm.add_contact"`. Mock registry to return app with `mcp_info.healthy=False`. Call `await gateway._handle_call_tool("crm.add_contact", {})`. -> Returns list with one `TextContent` containing `"Error: App 'crm' is currently unavailable"`.

- **test_mcp_gateway_on_app_started:** Create gateway with mock app in registry. Mock `_fetch_tools_from_app` to return 2 entries. Call `await gateway.on_app_started("crm")`. -> `gateway._tool_index` has 2 entries. Registry `mcp_info.registered_tools` updated with the 2 tool names.

- **test_mcp_gateway_on_app_stopped:** Populate index with 2 tools for app `crm`. Call `await gateway.on_app_stopped("crm")`. -> `gateway._tool_index` is empty.

- **test_mcp_backward_compat_pass:** Call `MCPGateway.check_backward_compatibility(["search", "add", "delete"], ["search", "add", "delete", "export"])`. -> Returns `(True, [])`.

- **test_mcp_backward_compat_fail:** Call `MCPGateway.check_backward_compatibility(["search", "add", "delete"], ["search", "add"])`. -> Returns `(False, ["delete"])`.
