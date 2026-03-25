# HomeHelper: App Specification

## Overview

This specification defines the requirements for apps that integrate with the HomeHelper system. Apps can be of two types: **Service Apps** and **Streamlit Apps**.

## App Types

### Service Apps
- **Lifecycle**: Managed by systemd, controlled by main app
- **Port Assignment**: Dynamically assigned by main app via `--port` parameter
- **Requirements**: Must implement required API endpoints
- **Startup Command**: `python app.py --port {assigned_port}`

### Streamlit Apps
- **Lifecycle**: Started on-demand when user opens UI, single instance only
- **Port Assignment**: Fixed port assigned by the main app
- **TTL**: Automatically killed after configured timeout
- **Startup Command**: `streamlit run app.py --server.port {configured_port}`

## Common Requirements

All apps must have the following files in their root directory:
- **homehelper.json**: App manifest file
- **requirements.txt**: Python dependencies
- **app.py**: Main entry point for service apps

### App Manifest (homehelper.json)

Each app must include a `homehelper.json` file in its root directory:

```json
{
  "name": "Camera Detection",
  "version": "1.0.0",
  "description": "Detects motion in camera feeds and publishes events",
  "type": "service",
  "author": "Your Name",
  "config": {
    "has_UI": true,
    "redis_required": true,
    "logs_dir": true,
    "data_dir": true,
    "auto_start": true,
    "restart_policy": "always"
  },
  "install": {
    "setup_commands": [
      "mkdir -p /opt/homehelper/data/camera_detection"
    ]
  }
}
```

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
- **config.redis_required**: Boolean, if app needs Redis (default: false)
- **config.logs_dir**: Boolean, if app receives the logs_dir argument (default: false)
- **config.data_dir**: Boolean, if app receives the data_dir argument (default: false)
- **config.auto_start**: Boolean, start on main app startup (default: false)
- **config.restart_policy**: `"always"`, `"on-failure"`, `"never"` (default: "always")
- **install.setup_commands**: Shell commands to run during installation
- **events.publishes**: Array of event types this app publishes (see Redis Events section)
- **events.subscribes**: Array of event types this app subscribes to (see Redis Events section)

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
HomeHelper uses Redis as a message bus for inter-app communication and event publishing. Apps can publish events and subscribe to events from other apps.

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
**Channel Pattern**: `homehelper:events:{event_type}`

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

r.publish("homehelper:events:motion.detected", json.dumps(event))
```

### Subscribing to Events
**Channel Pattern**: `homehelper:events:*` or `homehelper:events:{specific_event}`

**Python Example**:
```python
import redis
import json

r = redis.from_url(redis_url)
pubsub = r.pubsub()

# Subscribe to all events
pubsub.subscribe("homehelper:events:*")

# Or subscribe to specific events
pubsub.subscribe("homehelper:events:motion.detected")

for message in pubsub.listen():
    if message['type'] == 'message':
        event = json.loads(message['data'])
        print(f"Received: {event['event_type']} from {event['source']}")
        # Handle event...
```

### Event Declaration in Manifest

Apps should declare the events they publish and subscribe to in their `homehelper.json` manifest. This provides self-documentation, enables validation, and helps with debugging.

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
HomeHelper provides dedicated directories for each app to store persistent data and logs. These directories are managed by the main system and backed up automatically.

### Data Directory (`--data-dir`)
**Purpose**: Store persistent application data that needs to survive app restarts

**Path Format**: `/opt/homehelper/data/{app_name}/`

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

### Logs Directory (`--logs-dir`)
**Purpose**: Store application logs for debugging and monitoring

**Path Format**: `/opt/homehelper/logs/{app_name}/`

**Use Cases**:
- Application logs
- Error logs
- Debug traces
- Audit logs
- Performance metrics

**Python Example**:
```python
import argparse
import logging
from pathlib import Path
from datetime import datetime

parser = argparse.ArgumentParser()
parser.add_argument('--logs-dir', type=str, required=True)
args = parser.parse_args()

logs_dir = Path(args.logs_dir) / "camera_detection"
logs_dir.mkdir(parents=True, exist_ok=True)

# Setup logging
log_file = logs_dir / f"app_{datetime.now().strftime('%Y%m%d')}.log"
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(log_file),
        logging.StreamHandler()  # Also log to console
    ]
)

logger = logging.getLogger(__name__)
logger.info("Application started")
```

### Directory Management
- Directories are created by HomeHelper during app installation
- Apps should create subdirectories as needed
- Apps must handle missing directories gracefully
- Do not hardcode paths - always use provided arguments
- Implement log rotation to prevent disk space issues

## Configuration Integration

### Configuration sent via run parameters
The main app will ALWAYS send the port to the app
- `port` or `server.port`: Integer, port number

If enabled in the config, the following parameters will be also sent to the app:

- `redis-url`: Redis connection string
- `data-dir`: Data directory path
- `logs-dir`: Logs directory path

**example Service app use**
```bash
python main.py --port 8101 --redis-url redis://localhost:6379 --data-dir /opt/homehelper/data --logs-dir /opt/homehelper/logs
```

**example Streamlit app use**
```bash
streamlit run app.py --server.port 8501 --redis-url redis://localhost:6379 --data-dir /opt/homehelper/data --logs-dir /opt/homehelper/logs
```

## Environment Variables

Apps can access these environment variables set by HomeHelper:

- `HOMEHELPER_APP_NAME`: The app's name from manifest
- `HOMEHELPER_APP_VERSION`: The app's version
- `HOMEHELPER_CONFIG_PATH`: Path to main HomeHelper config (read-only)
- `REDIS_HOST`: Redis server host (if redis_required: true)
- `REDIS_PORT`: Redis server port (if redis_required: true)
- `REDIS_PASSWORD`: Redis password if configured (if redis_required: true)

**Note**: Prefer using command-line arguments over environment variables for configuration.

## Installation Process

1. **Discovery**: Main app scans `./apps/` for `homehelper.json` files
2. **Validation**: Validates manifest format and required fields
3. **Dependencies**: Installs Python packages from requirements.txt
4. **Setup**: Runs setup commands from manifest
5. **Service Creation**: Creates systemd service file (Service apps only)
6. **Registration**: Adds app to main app registry

## Service Management

### Systemd Service Template (Service Apps)
```ini
[Unit]
Description=HomeHelper - {app_name}
After=homehelper-main.service
Requires=homehelper-main.service  
PartOf=homehelper-main.service

[Service]
Type=simple
User=homehelper
WorkingDirectory=/opt/homehelper/apps/{app_name}
ExecStart=/usr/bin/python3 main.py --port {assigned_port}
Restart={restart_policy}
Environment=HOMEHELPER_CONFIG_PATH=/etc/homehelper/config.yaml
Environment=REDIS_URL=redis://localhost:6379

[Install]
WantedBy=homehelper-main.service
```

### Lifecycle Management
- **Start**: `systemctl start homehelper-{app_name}`
- **Stop**: `systemctl stop homehelper-{app_name}`
- **Status**: `systemctl status homehelper-{app_name}`
- **Logs**: `journalctl -u homehelper-{app_name} -f`

## Complete Working Example

### Minimal Service App
Here's a complete, minimal service app that demonstrates all core concepts:

**Directory Structure**:
```
my_sensor_app/
├── homehelper.json
├── requirements.txt
└── app.py
```

**homehelper.json**:
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
            "homehelper:events:temperature.reading",
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
            "homehelper:events:temperature.threshold.exceeded",
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
        pubsub.subscribe("homehelper:events:system.config.updated")
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
Before deploying to HomeHelper, test your app locally:

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
- [ ] homehelper.json manifest is valid JSON with all required fields
- [ ] Event declarations in manifest match actual implementation
- [ ] requirements.txt includes all necessary dependencies

### Common Issues
- **Port already in use**: Choose a different port for testing
- **Redis connection failed**: Ensure Redis is running locally (`redis-server`)
- **Permission denied on directories**: Use local test directories with write permissions
- **Import errors**: Verify all dependencies are in requirements.txt
- **Health endpoint returns wrong format**: Ensure `health` field is exactly "good", "warning", or "error"

This specification provides complete guidance for developing HomeHelper-compatible apps while maintaining consistency and proper integration with the main system.