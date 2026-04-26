# Latarnia: App Specification

## Overview

This specification defines the requirements for apps that integrate with the Latarnia system. Apps can be of two types: **Service Apps** and **Streamlit Apps**.

## App Types

### Service Apps
- **Lifecycle**: On Linux, launched as a per-app systemd user unit (`latarnia-{env}-{app}.service`); on macOS dev, launched as a subprocess child of the platform. The choice is made by the platform (P-0005); apps are unaware.
- **Port Assignment**: Dynamically assigned by main app via `--port` parameter
- **Requirements**: Must implement required API endpoints, handle SIGTERM cleanly, and write logs to stdout/stderr (Latarnia routes them to journald on Linux).
- **Startup Command**: `python app.py --port {assigned_port} [--mcp-port {mcp_port}]`
- **Crash recovery**: systemd respawns failed processes per the unit's `Restart=` policy (default `on-failure`, configurable via `config.restart_policy`).
- **Log location**: `journalctl --user -u latarnia-{env}-{app}.service` on Linux. The dashboard's logs panel queries this automatically.

### Streamlit Apps
- **Lifecycle**: Started on-demand when user opens UI, single instance only
- **Port Assignment**: Fixed port assigned by the main app
- **TTL**: Automatically killed after configured timeout
- **Startup Command**: `streamlit run app.py --server.port {configured_port}`

## Common Requirements

All apps must have the following files in their root directory:
- **latarnia.json**: App manifest file
- **requirements.txt**: Python dependencies
- **app.py**: Main entry point for service apps

### App Manifest (latarnia.json)

Each app must include a `latarnia.json` file in its root directory:

```json
{
  "name": "Camera Detection",
  "version": "1.0.0",
  "description": "Detects motion in camera feeds and publishes events",
  "type": "service",
  "author": "Your Name",
  "main_file": "app.py",
  "config": {
    "has_UI": true,
    "has_web_ui": false,
    "redis_required": true,
    "database": true,
    "mcp_server": true,
    "data_dir": true,
    "auto_start": true,
    "restart_policy": "always",
    "redis_streams_publish": ["camera.motion.detected"],
    "redis_streams_subscribe": []
  },
  "install": {
    "setup_commands": [
      "mkdir -p /opt/latarnia/data/camera_detection"
    ]
  },
  "requires": [
    {"app": "knowledge_base", "min_version": "1.0.0"}
  ]
}
```
> **Note:** All fields under `config` except `restart_policy` are optional and default to `false`/`null`/`[]`. The `requires` field is also optional and defaults to `[]`. Existing apps without these fields continue to work unchanged.

#### Manifest Field Definitions

##### Required Fields
- **name**: Display name for the app
- **version**: Semantic version (x.y.z)
- **description**: Brief description of app functionality
- **type**: `"service"` or `"streamlit"`
- **author**: App developer name
- **main_file**: Entry point file name

##### Optional Fields
- **config.has_UI**: Boolean, if app has a UI (default: false, Streamlit apps always have UI)
- **config.has_web_ui**: Boolean, if app serves its own web UI via HTTP on its assigned port (default: false). When true, the platform can reverse-proxy requests under `/apps/{app_name}/`.
- **config.redis_required**: Boolean, if app needs Redis (default: false)
- **config.database**: Boolean, if app needs a dedicated Postgres database (default: false). When true, the platform provisions an isolated database and passes `--db-url` at launch.
- **config.mcp_server**: Boolean, if app exposes an MCP server (default: false). The platform dynamically allocates an MCP port and passes it via `--mcp-port` at launch. The app must accept this CLI argument and start its MCP server on the given port.
- **config.logs_dir**: *Deprecated as of P-0005 Scope 4.* The field still parses for backward compat but is ignored — no `--logs-dir` CLI argument is passed. Apps should log to stdout/stderr; the platform routes that to journald (Linux) or to a subprocess log file (Darwin dev).
- **config.data_dir**: Boolean, if app receives the data_dir argument (default: false)
- **config.auto_start**: Boolean, start on main app startup (default: false)
- **config.restart_policy**: `"always"`, `"on-failure"`, `"never"` (default: "always")
- **config.redis_streams_publish**: Array of stream names this app publishes to (default: []). Each stream can have at most one publisher.
- **config.redis_streams_subscribe**: Array of stream names this app subscribes to (default: []). Consumer groups are created per subscribing app.
- **install.setup_commands**: Shell commands to run during installation
- **events.publishes**: Array of event types this app publishes (see Redis Events section)
- **events.subscribes**: Array of event types this app subscribes to (see Redis Events section)
- **requires**: Array of dependency objects. Each declares a required app and minimum version. If any dependency is unmet at discovery time, the app will not be registered.

##### Dependency Declaration (requires)
```json
{
  "requires": [
    {"app": "knowledge_base", "min_version": "1.2.0"}
  ]
}
```
- **app**: Name of the required app (must match the `name` field in the dependency's manifest)
- **min_version**: Minimum semantic version required (inclusive)
- Dependencies are checked at discovery time. If a required app is not registered or its version is below `min_version`, the dependent app is skipped with an error log.
- Only direct dependencies are checked — no transitive resolution.

## Service App Requirements

### Required API Endpoints

#### Health Endpoint
**Path**: `GET /health`

**Response Format**:
```json
{
  "health": "good|warning|error",
  "message": "Human readable status description", 
  "extra_info": {
    "custom_metric_1": "value1",
    "custom_metric_2": 42,
    "last_activity": "2024-01-01 10:30:00"
  }
}
```

**Response Rules**:
- **health**: Must be one of: `"good"`, `"warning"`, `"error"`
- **message**: Short status description (max 100 characters)
- **extra_info**: Optional object with key-value pairs for dashboard display

#### UI Endpoint (Optional)
**Path**: `GET /ui`

**Response Format**:
```json
["messages", "statistics", "logs", "config"]
```

**Response Rules**:
- Returns array of available resource names
- Each resource must have corresponding REST API endpoint
- Resource names should be plural nouns

### REST API Endpoints (Optional)

If app exposes `/ui`, it must implement corresponding REST endpoints:

**Pattern**: `/api/{resource}` and `/api/{resource}/{id}`

#### Resource Collection Endpoint
**Path**: `GET /api/{resource}`

**Response Format**:
```json
[
  {
    "id": 1,
    "name": "First Item",
    "date_created": 1704067200,
    "status": "active"
  },
  {
    "id": 2, 
    "name": "Second Item",
    "date_created": 1704070800,
    "status": "inactive"
  }
]
```

#### Single Resource Endpoint
**Path**: `GET /api/{resource}/{id}`

**Response Format**:
```json
{
  "id": 123,
  "title": "Resource Title",
  "description": "Detailed description",
  "img_thumbnail": "data:image/jpeg;base64,/9j/4AAQ...",
  "date_created": 1704067200,
  "date_modified": 1704070800,
  "tags": ["tag1", "tag2"],
  "metadata": {
    "key1": "value1",
    "key2": "value2"
  }
}
```

### Data Field Conventions

#### Mandatory Fields
- **id**: Integer, unique identifier for the resource

#### Optional Field Prefixes
- **img_**: Base64 encoded image data
  - Format: `"data:image/{format};base64,{data}"`
  - Example: 
  ```json
  "img_photo": "data:image/jpeg;base64,/9j/4AAQ..."`
  ```

- **date_**: Unix timestamp (integer)
  - Example: 
  ```json
  "date_created": 1704067200
  ```

- **mermaid_**: Mermaid diagram markdown
  - Example: 
```json
"mermaid_graph": 
"xychart
    title \"energy consumption\"
    x-axis [jan, feb, mar, apr]
    y-axis \"KWh\" 1000 --> 5000
    line [900, 1200, 1900, 4800]"
```
  
#### Other Field Types
- **Arrays/Lists**: Rendered as tables
- **Objects**: Rendered as nested forms
- **Strings/Numbers**: Rendered as text fields

### Error Response Format

All endpoints must return standard HTTP status codes with JSON error responses:

```json
{
  "error": "Error type",
  "message": "Human readable error description",
  "details": {
    "additional": "context information"
  }
}
```

**Common HTTP Status Codes**:
- `200`: Success
- `400`: Bad Request
- `404`: Resource Not Found
- `500`: Internal Server Error

## Redis Integration

### Overview
Latarnia uses Redis as a message bus for inter-app communication and event publishing. Apps can publish events and subscribe to events from other apps.

### Connection
Apps receive Redis connection via `--redis-url` parameter when `redis_required: true` in manifest.

### Message Format
All Redis messages follow this standard format:

```json
{
  "source": "app_name",
  "event_type": "event.category.action",
  "timestamp": 1704067200,
  "data": {
    "key1": "value1",
    "key2": "value2"
  }
}
```

### Publishing Events
**Channel Pattern**: `latarnia:events:{event_type}`

**Example Event Types**:
- `motion.detected` - Motion sensor triggered
- `camera.recording.started` - Camera started recording
- `door.opened` - Door sensor triggered
- `temperature.threshold.exceeded` - Temperature alert

**Python Example**:
```python
import redis
import json
from datetime import datetime

r = redis.from_url(redis_url)

event = {
    "source": "camera_detection",
    "event_type": "motion.detected",
    "timestamp": int(datetime.now().timestamp()),
    "data": {
        "camera_id": "front_door",
        "confidence": 0.95,
        "location": "entrance"
    }
}

r.publish("latarnia:events:motion.detected", json.dumps(event))
```

### Subscribing to Events
**Channel Pattern**: `latarnia:events:*` or `latarnia:events:{specific_event}`

**Python Example**:
```python
import redis
import json

r = redis.from_url(redis_url)
pubsub = r.pubsub()

# Subscribe to all events
pubsub.subscribe("latarnia:events:*")

# Or subscribe to specific events
pubsub.subscribe("latarnia:events:motion.detected")

for message in pubsub.listen():
    if message['type'] == 'message':
        event = json.loads(message['data'])
        print(f"Received: {event['event_type']} from {event['source']}")
        # Handle event...
```

### Event Declaration in Manifest

Apps should declare the events they publish and subscribe to in their `latarnia.json` manifest. This provides self-documentation, enables validation, and helps with debugging.

**Example**:
```json
{
  "name": "Camera Detection",
  "events": {
    "publishes": [
      {
        "type": "motion.detected",
        "description": "Triggered when motion is detected in camera feed",
        "schema": {
          "camera_id": "string",
          "confidence": "float",
          "location": "string",
          "image_url": "string (optional)"
        }
      },
      {
        "type": "camera.recording.started",
        "description": "Camera started recording",
        "schema": {
          "camera_id": "string",
          "duration": "integer",
          "reason": "string"
        }
      }
    ],
    "subscribes": [
      {
        "type": "door.opened",
        "description": "Listen for door events to trigger camera",
        "handler": "on_door_opened"
      },
      {
        "type": "alarm.triggered",
        "description": "Start recording on alarm",
        "handler": "on_alarm_triggered"
      }
    ]
  }
}
```

**Event Declaration Fields**:

For **publishes**:
- `type`: Event type using dot notation (required)
- `description`: Human-readable description of when this event is published (required)
- `schema`: Object describing the data fields and their types (required)

For **subscribes**:
- `type`: Event type to subscribe to, supports wildcards (e.g., "motion.*") (required)
- `description`: Why the app subscribes to this event (required)
- `handler`: Name of the handler function in your code (optional, for documentation)

### Best Practices

#### Event Naming Convention
- Use dot notation: `category.subcategory.action`
- Use lowercase with underscores for multi-word components
- Examples:
  - ✅ `motion.detected`
  - ✅ `camera.recording.started`
  - ✅ `temperature.threshold.exceeded`
  - ❌ `MotionDetected`
  - ❌ `camera-recording-started`

#### Event Declaration
- **Always declare events in manifest**: This enables discovery and validation
- **Keep schemas simple**: Only include essential data fields
- **Document optional fields**: Mark optional fields in schema description
- **Version your events**: If schema changes, consider using `motion.detected.v2`

#### Event Publishing
- **Include all required fields**: Always include `source`, `event_type`, `timestamp`, and `data`
- **Validate before publishing**: Ensure data matches declared schema
- **Don't publish too frequently**: Batch events or use debouncing for high-frequency events
- **Use appropriate data types**: Timestamps as integers, booleans as booleans, etc.
- **Keep payload small**: Avoid large data in events, use references instead

#### Event Subscribing
- **Use specific subscriptions**: Subscribe to specific events when possible, not wildcards
- **Handle events asynchronously**: Don't block the subscriber thread
- **Implement error handling**: Events may have unexpected formats
- **Validate received data**: Don't trust event data blindly
- **Log subscription errors**: Help with debugging integration issues

#### Performance Considerations
- **Batch events**: If publishing many events, consider batching
- **Use TTL for transient data**: Don't store events indefinitely
- **Monitor queue depth**: Watch for subscriber backlog
- **Implement circuit breakers**: Stop processing if downstream is failing

#### Security
- **No sensitive data**: Don't include passwords, tokens, or PII in events
- **Validate event source**: Verify events come from expected apps
- **Sanitize data**: Clean user input before publishing
- **Use encryption**: For sensitive operational data, encrypt the payload

#### Error Handling
- **Graceful degradation**: App should work if Redis is unavailable
- **Reconnection logic**: Automatically reconnect on connection loss
- **Dead letter handling**: Log events that fail to process
- **Idempotency**: Handle duplicate events gracefully

## Data and Logs Directories

### Overview
Latarnia provides dedicated directories for each app to store persistent data and logs. These directories are managed by the main system and backed up automatically.

### Data Directory (`--data-dir`)
**Purpose**: Store persistent application data that needs to survive app restarts

**Path Format**: `/opt/latarnia/data/{app_name}/`

**Use Cases**:
- Database files (SQLite, JSON, etc.)
- Configuration files
- Cached data
- User-uploaded files
- Model weights or training data
- State persistence

**Python Example**:
```python
import argparse
import json
from pathlib import Path

parser = argparse.ArgumentParser()
parser.add_argument('--data-dir', type=str, required=True)
args = parser.parse_args()

data_dir = Path(args.data_dir) / "camera_detection"
data_dir.mkdir(parents=True, exist_ok=True)

# Save persistent data
config_file = data_dir / "config.json"
with open(config_file, 'w') as f:
    json.dump({"setting": "value"}, f)

# Load persistent data
with open(config_file, 'r') as f:
    config = json.load(f)
```

### Logs (no `--logs-dir`; log to stdout/stderr)

As of **P-0005 Scope 4**, apps no longer receive a `--logs-dir` argument. Apps log to **stdout/stderr** and the platform routes the streams:

- **Linux** (per-app systemd user units): stdout/stderr → journald. Query with `journalctl --user -u latarnia-{env}-{app}.service`.
- **macOS dev** (subprocess fallback): stdout/stderr → file at `/opt/latarnia/{env}/logs/{app_id}.log` (managed by `SubprocessLauncher`; the app does nothing).

The dashboard's log panel queries `/api/apps/{app_id}/logs`, which dispatches to the right source automatically — apps don't need to know which OS they're on.

**Python Example**:
```python
import argparse
import logging

parser = argparse.ArgumentParser()
parser.add_argument('--port', type=int, required=True)
args = parser.parse_args()

# Stdout-only logging. Latarnia handles capture.
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[logging.StreamHandler()],
)
logger = logging.getLogger(__name__)
logger.info("Application started on port %d", args.port)
```

### Directory Management
- The data directory is created by Latarnia and passed via `--data-dir`.
- Apps should create subdirectories under it as needed.
- Apps must handle missing directories gracefully.
- Do not hardcode paths — always use provided arguments.
- Do not implement file-based log rotation; journald handles retention by size/time.

## Configuration Integration

### Configuration sent via run parameters
The main app will ALWAYS send the port to the app:
- `port` or `server.port`: Integer, port number

If enabled in the manifest config, the following are also passed:

- `redis-url`: Redis connection string (when `redis_required: true`)
- `mcp-port`: MCP server port (when `mcp_server: true`)
- `data-dir`: Data directory path (when `data_dir: true`)
- `db-url`: Database connection URL (when `database: true`)

> **Removed**: `--logs-dir` (deprecated in P-0005 Scope 4). Log to stdout/stderr.

**Example Service app use**:
```bash
python main.py --port 8101 --redis-url redis://localhost:6379 --data-dir /opt/latarnia/{env}/data/{app_id}
```

**Example Streamlit app use**:
```bash
streamlit run app.py --server.port 8501 --redis-url redis://localhost:6379 --data-dir /opt/latarnia/{env}/data/{app_id}
```

## Environment Variables

Apps can access these environment variables set by Latarnia:

- `LATARNIA_APP_NAME`: The app's name from manifest
- `LATARNIA_APP_VERSION`: The app's version
- `LATARNIA_CONFIG_PATH`: Path to main Latarnia config (read-only)
- `REDIS_HOST`: Redis server host (if redis_required: true)
- `REDIS_PORT`: Redis server port (if redis_required: true)
- `REDIS_PASSWORD`: Redis password if configured (if redis_required: true)

**Note**: Prefer using command-line arguments over environment variables for configuration.

## Installation Process

1. **Discovery**: Main app scans `./apps/` for `latarnia.json` files
2. **Validation**: Validates manifest format and required fields
3. **Dependencies**: Installs Python packages from requirements.txt
4. **Setup**: Runs setup commands from manifest
5. **Service Creation**: Creates systemd service file (Service apps only)
6. **Registration**: Adds app to main app registry

## Service Management

### Systemd Service Template (Service Apps)
```ini
[Unit]
Description=Latarnia - {app_name}
After=latarnia-main.service
Requires=latarnia-main.service  
PartOf=latarnia-main.service

[Service]
Type=simple
User=latarnia
WorkingDirectory=/opt/latarnia/apps/{app_name}
ExecStart=/usr/bin/python3 main.py --port {assigned_port}
Restart={restart_policy}
Environment=LATARNIA_CONFIG_PATH=/etc/latarnia/config.yaml
Environment=REDIS_URL=redis://localhost:6379

[Install]
WantedBy=latarnia-main.service
```

### Lifecycle Management
- **Start**: `systemctl start latarnia-{app_name}`
- **Stop**: `systemctl stop latarnia-{app_name}`
- **Status**: `systemctl status latarnia-{app_name}`
- **Logs**: `journalctl -u latarnia-{app_name} -f`

## Complete Working Example

### Minimal Service App
Here's a complete, minimal service app that demonstrates all core concepts:

**Directory Structure**:
```
my_sensor_app/
├── latarnia.json
├── requirements.txt
└── app.py
```

**latarnia.json**:
```json
{
  "name": "Temperature Monitor",
  "version": "1.0.0",
  "description": "Monitors temperature and publishes alerts",
  "type": "service",
  "author": "Developer Name",
  "main_file": "app.py",
  "config": {
    "has_UI": true,
    "redis_required": true,
    "logs_dir": true,
    "data_dir": true,
    "auto_start": true,
    "restart_policy": "always"
  },
  "events": {
    "publishes": [
      {
        "type": "temperature.reading",
        "description": "Published every time a temperature reading is taken",
        "schema": {
          "sensor": "string",
          "temperature": "float",
          "humidity": "float",
          "timestamp": "integer"
        }
      },
      {
        "type": "temperature.threshold.exceeded",
        "description": "Published when temperature exceeds configured threshold",
        "schema": {
          "sensor": "string",
          "temperature": "float",
          "threshold": "float",
          "severity": "string"
        }
      }
    ],
    "subscribes": [
      {
        "type": "system.config.updated",
        "description": "Listen for configuration changes to update thresholds",
        "handler": "on_config_updated"
      }
    ]
  },
  "install": {
    "setup_commands": []
  }
}
```

**requirements.txt**:
```
fastapi==0.104.1
uvicorn==0.24.0
redis==5.0.1
```

**app.py**:
```python
import argparse
import json
import logging
from pathlib import Path
from datetime import datetime
from fastapi import FastAPI
from fastapi.responses import JSONResponse
import redis
import uvicorn

# Parse command line arguments
parser = argparse.ArgumentParser()
parser.add_argument('--port', type=int, required=True)
parser.add_argument('--redis-url', type=str, required=False)
parser.add_argument('--data-dir', type=str, required=False)
parser.add_argument('--logs-dir', type=str, required=False)
args = parser.parse_args()

# Setup logging
if args.logs_dir:
    logs_dir = Path(args.logs_dir) / "temperature_monitor"
    logs_dir.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(levelname)s - %(message)s',
        handlers=[
            logging.FileHandler(logs_dir / f"app_{datetime.now().strftime('%Y%m%d')}.log"),
            logging.StreamHandler()
        ]
    )
else:
    logging.basicConfig(level=logging.INFO)

logger = logging.getLogger(__name__)

# Setup Redis
redis_client = None
if args.redis_url:
    redis_client = redis.from_url(args.redis_url)
    logger.info(f"Connected to Redis: {args.redis_url}")

# Setup data directory
data_dir = None
if args.data_dir:
    data_dir = Path(args.data_dir) / "temperature_monitor"
    data_dir.mkdir(parents=True, exist_ok=True)
    logger.info(f"Data directory: {data_dir}")

# Create FastAPI app
app = FastAPI()

# Health endpoint (REQUIRED)
@app.get("/health")
async def health():
    return {
        "health": "good",
        "message": "Temperature monitor is running",
        "extra_info": {
            "last_check": datetime.now().isoformat(),
            "sensors_active": 3
        }
    }

# UI endpoint (OPTIONAL)
@app.get("/ui")
async def ui():
    return ["readings", "alerts"]

# REST API endpoints (OPTIONAL - if /ui is implemented)
@app.get("/api/readings")
async def get_readings():
    return [
        {
            "id": 1,
            "sensor": "living_room",
            "temperature": 22.5,
            "date_recorded": int(datetime.now().timestamp())
        },
        {
            "id": 2,
            "sensor": "bedroom",
            "temperature": 20.1,
            "date_recorded": int(datetime.now().timestamp())
        }
    ]

@app.get("/api/readings/{reading_id}")
async def get_reading(reading_id: int):
    return {
        "id": reading_id,
        "sensor": "living_room",
        "temperature": 22.5,
        "humidity": 45.2,
        "date_recorded": int(datetime.now().timestamp())
    }

# Example: Publishing to Redis
def publish_temperature_reading(sensor: str, temperature: float, humidity: float):
    """Publish regular temperature reading event"""
    if redis_client:
        event = {
            "source": "temperature_monitor",
            "event_type": "temperature.reading",
            "timestamp": int(datetime.now().timestamp()),
            "data": {
                "sensor": sensor,
                "temperature": temperature,
                "humidity": humidity,
                "timestamp": int(datetime.now().timestamp())
            }
        }
        redis_client.publish(
            "latarnia:events:temperature.reading",
            json.dumps(event)
        )
        logger.debug(f"Published reading for {sensor}: {temperature}°C")

def publish_temperature_alert(sensor: str, temperature: float, threshold: float):
    """Publish temperature threshold exceeded event"""
    if redis_client:
        event = {
            "source": "temperature_monitor",
            "event_type": "temperature.threshold.exceeded",
            "timestamp": int(datetime.now().timestamp()),
            "data": {
                "sensor": sensor,
                "temperature": temperature,
                "threshold": threshold,
                "severity": "high" if temperature > threshold + 5 else "medium"
            }
        }
        redis_client.publish(
            "latarnia:events:temperature.threshold.exceeded",
            json.dumps(event)
        )
        logger.warning(f"Published alert for {sensor}: {temperature}°C (threshold: {threshold}°C)")

# Example: Subscribing to Redis events
def start_event_subscriber():
    """Start listening to subscribed events in background thread"""
    if not redis_client:
        return
    
    import threading
    
    def event_listener():
        pubsub = redis_client.pubsub()
        pubsub.subscribe("latarnia:events:system.config.updated")
        logger.info("Started event subscriber")
        
        for message in pubsub.listen():
            if message['type'] == 'message':
                try:
                    event = json.loads(message['data'])
                    event_type = event.get('event_type')
                    
                    if event_type == 'system.config.updated':
                        on_config_updated(event)
                    
                except Exception as e:
                    logger.error(f"Error processing event: {e}")
    
    # Start subscriber in background thread
    thread = threading.Thread(target=event_listener, daemon=True)
    thread.start()

def on_config_updated(event):
    """Handler for system.config.updated events"""
    logger.info(f"Configuration updated: {event.get('data', {})}")
    # Reload configuration or update thresholds here

# Start the server
if __name__ == "__main__":
    logger.info(f"Starting Temperature Monitor on port {args.port}")
    
    # Start event subscriber if Redis is available
    start_event_subscriber()
    
    uvicorn.run(app, host="0.0.0.0", port=args.port)
```

## Testing Your App

### Local Testing
Before deploying to Latarnia, test your app locally:

```bash
# Install dependencies
pip install -r requirements.txt

# Run with test parameters
python app.py --port 8100 --redis-url redis://localhost:6379 --data-dir ./test_data --logs-dir ./test_logs

# Test health endpoint
curl http://localhost:8100/health

# Test UI endpoint (if implemented)
curl http://localhost:8100/ui

# Test API endpoints
curl http://localhost:8100/api/readings
curl http://localhost:8100/api/readings/1
```

### Validation Checklist
- [ ] Health endpoint returns valid JSON with required fields (`health`, `message`)
- [ ] App starts successfully with all required arguments
- [ ] Logs are written to logs directory (if `logs_dir: true`)
- [ ] Data persists in data directory across restarts (if `data_dir: true`)
- [ ] Redis events are published correctly (if `redis_required: true`)
- [ ] Published events match declared schema in manifest
- [ ] Event subscriptions work and handlers are called
- [ ] All REST API endpoints return valid responses (if `/ui` implemented)
- [ ] Error handling returns proper HTTP status codes
- [ ] App handles missing optional arguments gracefully
- [ ] latarnia.json manifest is valid JSON with all required fields
- [ ] Event declarations in manifest match actual implementation
- [ ] requirements.txt includes all necessary dependencies

### Common Issues
- **Port already in use**: Choose a different port for testing
- **Redis connection failed**: Ensure Redis is running locally (`redis-server`)
- **Permission denied on directories**: Use local test directories with write permissions
- **Import errors**: Verify all dependencies are in requirements.txt
- **Health endpoint returns wrong format**: Ensure `health` field is exactly "good", "warning", or "error"

## MCP Server Contract

### Overview

Service apps can optionally expose an **MCP (Model Context Protocol) server** to provide tools that external AI clients (or the Latarnia MCP gateway) can discover and invoke. The app owns its MCP server entirely — the platform does not implement MCP for the app.

### Manifest Declaration

To enable MCP, set `mcp_server` to `true` in the `config` section of your `latarnia.json` manifest:

```json
{
  "name": "My MCP App",
  "version": "1.0.0",
  "type": "service",
  "config": {
    "mcp_server": true
  }
}
```

- **`mcp_server`** (bool): Set to `true` to declare that this app runs an MCP server.
- The platform dynamically allocates an MCP port from the configured range (default 9001–9099) and passes it to the app via `--mcp-port` at launch.
- **Do not** declare `mcp_port` in the manifest — manifests containing `mcp_port` are rejected at validation.

### Protocol Requirements

Apps that declare `mcp_server: true` must:

1. **Accept `--mcp-port` CLI argument** — the platform passes the dynamically allocated MCP port at launch. The app must start its MCP server on this port.
2. **Run an HTTP-based MCP server** on the allocated port. The server must use HTTP transport (`sse` or `streamable-http`). **stdio transport is not supported** by the platform.
3. **Respond to MCP `tools/list`** — return a list of tools the app provides, following the MCP protocol specification.
4. **Respond to MCP `tools/call`** — execute a tool invocation and return the result, following the MCP protocol specification.
5. **Be ready to receive MCP requests after `/health` returns `good`** — the platform health monitor will probe the MCP port only after the standard `/health` check passes.

### Platform Health Probe

After the standard `/health` endpoint returns `good` or `warning`, the platform performs an MCP liveness probe:

- The probe sends a basic HTTP GET to `http://localhost:{mcp_port}/sse`, `/mcp`, or `/` (tried in order).
- If any probe returns a 2xx HTTP status, the MCP server is considered healthy.
- The result is stored in the app's `MCPInfo.healthy` field in the registry.
- If the probe fails, a warning is logged. The app's REST health status is **not** affected — only `MCPInfo.healthy` is set to `false`.

### Recommended Implementation

Use the `mcp` Python SDK for your MCP server. Example with SSE transport:

```python
from mcp.server import Server
from mcp.server.sse import SseServerTransport
from starlette.applications import Starlette
from starlette.routing import Route, Mount
import uvicorn

# Create the MCP server
server = Server("my-app-mcp")

@server.list_tools()
async def list_tools():
    return [
        {
            "name": "get_status",
            "description": "Get the current status of the app",
            "inputSchema": {
                "type": "object",
                "properties": {},
                "required": []
            }
        }
    ]

@server.call_tool()
async def call_tool(name: str, arguments: dict):
    if name == "get_status":
        return [{"type": "text", "text": "App is running normally"}]
    raise ValueError(f"Unknown tool: {name}")

# Create SSE transport
sse = SseServerTransport("/messages/")

async def handle_sse(scope, receive, send):
    async with sse.connect_sse(scope, receive, send) as streams:
        await server.run(streams[0], streams[1], server.create_initialization_options())

# Bypass Starlette's request-response wrapping by setting .app directly
sse_route = Route("/sse", endpoint=lambda _: None)
sse_route.app = handle_sse

routes = [
    sse_route,
    Mount("/messages/", app=sse.handle_post_message),
]

app = Starlette(routes=routes)

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=9001)
```

### What the Platform Does NOT Do

- The platform does **not** implement the MCP server for the app.
- The platform does **not** validate MCP tool schemas or responses.
- The platform does **not** support stdio-based MCP transport.
- The platform does **not** proxy MCP requests to the app (that is the MCP gateway's responsibility in a separate scope).

### Testing Your MCP Server

```bash
# Start your app (REST + MCP)
python app.py --port 8100

# Verify the REST health endpoint
curl http://localhost:8100/health

# Verify MCP server is responding (SSE transport)
curl -N http://localhost:9001/sse
# Should return an SSE stream or a valid HTTP response
```

## Database & Migrations

### Overview
Apps that declare `database: true` in their manifest receive an isolated Postgres database provisioned by the platform. The connection string is passed via `--db-url` at launch.

### What the Platform Provides
- A dedicated database named `latarnia_{app_name}`
- A dedicated role `latarnia_{app_name}_role` with LOGIN and CONNECT privileges
- Automatic migration execution on first discovery and version bumps
- A `schema_versions` table in the app database tracking applied migrations

### Migration File Conventions
Place SQL migration files in a `migrations/` directory at the app root:

```
my_app/
├── latarnia.json
├── app.py
└── migrations/
    ├── 001_initial.sql
    ├── 002_add_tags.sql
    └── 003_add_status.sql
```

**Rules:**
- Files must be named with a numeric prefix (e.g., `001_`, `002_`) for ordering
- Migrations run in numeric order during a single transaction
- Each migration runs exactly once — the platform tracks applied migrations via checksums
- On failure: the transaction rolls back, the database is dropped and recreated, and the app is NOT started
- Migrations are forward-only — there is no rollback automation

### App Responsibilities
- Use the `--db-url` connection string for all database access
- Do NOT create databases or roles — the platform handles this
- Ship all schema changes as migration files
- Test migrations locally before deploying

---

## Redis Streams (App-to-App Communication)

### Overview
Redis Streams provide guaranteed-delivery, ordered messaging between apps. Unlike Redis Pub/Sub (used for platform events), Streams persist messages and support consumer groups.

### Declaration
Apps declare their streams in the manifest:

```json
{
  "config": {
    "redis_streams_publish": ["myapp.events.created"],
    "redis_streams_subscribe": ["other_app.commands.process"]
  }
}
```

### Stream Naming
- Declared names are prefixed by the platform: `latarnia:streams:{declared_name}`
- Example: `"myapp.events.created"` becomes `latarnia:streams:myapp.events.created`

### Publishing
Each stream has exactly ONE publisher app (enforced at registration). Use `XADD`:

```python
import redis, json
from datetime import datetime

r = redis.from_url(redis_url)
r.xadd("latarnia:streams:myapp.events.created", {
    "source": "my_app",
    "timestamp": str(int(datetime.now().timestamp())),
    "version": "1.0",
    "data": json.dumps({"item_id": 42, "action": "created"}),
})
```

### Subscribing
The platform creates a consumer group per subscribing app. Use `XREADGROUP` and `XACK`:

```python
r = redis.from_url(redis_url)
group = "my_app"  # Your app_id is the consumer group name
consumer = "my_app-1"

while True:
    messages = r.xreadgroup(group, consumer,
        {"latarnia:streams:other_app.commands.process": ">"}, count=10, block=5000)
    for stream, entries in messages:
        for msg_id, data in entries:
            # Process message
            payload = json.loads(data[b"data"])
            # ... handle payload ...
            r.xack(stream, group, msg_id)
```

### Constraints
- Two apps CANNOT publish to the same stream (collision error at registration)
- Multiple apps CAN subscribe to the same stream
- The platform does NOT validate message contents — apps own their schemas
- Stream retention uses Redis defaults

---

## Web UI (Reverse Proxy)

### Overview
Apps with `has_web_ui: true` serve their own HTTP-based web UI on their assigned port. The platform reverse-proxies requests from `/apps/{app_name}/` to the app.

### Requirements
- Serve HTML on `GET /` (the web UI root)
- All assets (CSS, JS, images) must use relative paths (not absolute `/` paths)
- The app does NOT know about the `/apps/{app_name}/` prefix — the platform strips it

### Platform Behavior
- `GET /apps/crm/dashboard` → proxied to `http://localhost:{port}/dashboard`
- `GET /apps/crm/static/style.css` → proxied to `http://localhost:{port}/static/style.css`
- WebSocket connections at `/apps/crm/ws` → proxied to `ws://localhost:{port}/ws`
- Headers added: `X-Forwarded-For`, `X-Forwarded-Proto`, `X-Forwarded-Host`

### Error Responses
- App not found: 404
- App not running: 503 with friendly error page
- App has no web UI declared: 404
- Connection timeout: 504

### Example
A minimal web UI in a FastAPI app:

```python
from fastapi import FastAPI
from fastapi.responses import HTMLResponse

app = FastAPI()

@app.get("/", response_class=HTMLResponse)
async def web_ui():
    return "<html><body><h1>My App</h1></body></html>"
```

---

## Example Apps

Two example apps are provided in the `examples/` directory:

### example_companion
Minimal service app that serves as a dependency target. Contains only a `/health` endpoint.

### example_full_app
Full-featured service app demonstrating all P-0002 capabilities:
- `latarnia.json` with all new fields (database, mcp_server, has_web_ui, redis_streams, requires)
- `migrations/` directory with 3 SQL migration files
- MCP server exposing 3 tools (list_items, add_item, get_status)
- Web UI (HTML page served by FastAPI at `/`)
- Redis Streams publisher (example.events.created) and subscriber (example.commands.process)
- REST API with `/health`, `/ui`, `/api/items`, `/api/events`
- Depends on `example_companion` >= 1.0.0

To use the example apps, copy them to the `apps/` directory (companion first, then full app).

This specification provides complete guidance for developing Latarnia-compatible apps while maintaining consistency and proper integration with the main system.