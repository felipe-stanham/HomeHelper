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

This specification provides complete guidance for developing HomeHelper-compatible apps while maintaining consistency and proper integration with the main system.