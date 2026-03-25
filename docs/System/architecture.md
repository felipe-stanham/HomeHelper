# HomeHelper Architecture

This document describes the overall architecture of the HomeHelper unified home automation platform.

## System Overview

```mermaid
graph TB
    subgraph "Raspberry Pi 5"
        subgraph "HomeHelper Main Application"
            FastAPI[FastAPI Web Server<br/>Port 8000]
            AppMgr[App Manager<br/>Discovery & Registry]
            SvcMgr[Service Manager<br/>systemd Integration]
            UIMgr[UI Manager<br/>Streamlit TTL]
            SysMon[System Monitor<br/>Hardware Metrics]
        end
        
        subgraph "Message Bus"
            Redis[(Redis<br/>Port 6379)]
        end
        
        subgraph "Applications"
            SvcApp1[Service App 1<br/>Port 8100-8199]
            SvcApp2[Service App 2<br/>Port 8100-8199]
            StreamlitApp1[Streamlit App 1<br/>Port 8501+]
            StreamlitApp2[Streamlit App 2<br/>Port 8501+]
        end
        
        subgraph "System Services"
            systemd[systemd<br/>Process Management]
            FileSystem[Shared Storage<br/>/opt/homehelper/]
        end
    end
    
    subgraph "External"
        Browser[Web Browser]
        User[User]
    end
    
    User --> Browser
    Browser --> FastAPI
    FastAPI --> AppMgr
    FastAPI --> SvcMgr
    FastAPI --> UIMgr
    FastAPI --> SysMon
    
    AppMgr --> Redis
    SvcMgr --> systemd
    UIMgr --> StreamlitApp1
    UIMgr --> StreamlitApp2
    
    systemd --> SvcApp1
    systemd --> SvcApp2
    
    SvcApp1 --> Redis
    SvcApp2 --> Redis
    StreamlitApp1 --> Redis
    StreamlitApp2 --> Redis
    
    SvcApp1 --> FileSystem
    SvcApp2 --> FileSystem
    StreamlitApp1 --> FileSystem
    StreamlitApp2 --> FileSystem
```

## Core Components

### 1. FastAPI Main Application
- **Purpose**: Central web server and API gateway
- **Port**: 8000 (configurable)
- **Responsibilities**:
  - Web dashboard serving
  - Health monitoring endpoints
  - System metrics API
  - App management API
  - Configuration management

### 2. App Manager
- **Purpose**: Application discovery and lifecycle management
- **Responsibilities**:
  - Auto-discovery of apps in `./apps/` directory
  - Manifest parsing (`homehelper.json`)
  - In-memory app registry with persistence
  - Dynamic port allocation (8100-8199 range)
  - Python dependency installation
  - App validation and setup

### 3. Service Manager
- **Purpose**: Background service lifecycle control
- **Responsibilities**:
  - systemd service template generation
  - Service start/stop/restart operations
  - Health check polling
  - Process monitoring and metrics
  - Error recovery and restart policies
  - Log access via journalctl

### 4. UI Manager
- **Purpose**: On-demand Streamlit application management
- **Responsibilities**:
  - Streamlit process spawning
  - TTL-based cleanup (default 300 seconds)
  - Port management for Streamlit apps
  - Modal integration with main dashboard
  - Resource monitoring and cleanup

### 5. System Monitor
- **Purpose**: Hardware and system metrics collection
- **Responsibilities**:
  - CPU usage monitoring
  - Memory utilization tracking
  - Disk space monitoring
  - Temperature sensors (Raspberry Pi specific)
  - Process metrics collection
  - Health status determination

### 6. Redis Message Bus
- **Purpose**: Inter-app communication and event system
- **Responsibilities**:
  - Pub/Sub messaging between apps
  - Event logging and history
  - Health monitoring data
  - Configuration change notifications
  - App status updates

## Application Types

### Service Apps
```mermaid
graph LR
    subgraph "Service App"
        Main[main.py<br/>FastAPI/Flask]
        Health[&sol;health endpoint]
        UI[&sol;ui endpoint<br/>REST API]
        Logic[Business Logic]
        Data[Data Processing]
    end
    
    subgraph "HomeHelper Integration"
        Manifest[homehelper.json]
        Requirements[requirements.txt]
        Setup[setup.py/commands]
    end
    
    subgraph "System Integration"
        systemd[systemd Service]
        Redis[Redis Pub/Sub]
        Storage[/opt/homehelper/data/app-name/]
        Logs[/opt/homehelper/logs/app-name/]
    end
    
    Main --> Health
    Main --> UI
    Main --> Logic
    Logic --> Data
    
    Manifest --> systemd
    Requirements --> systemd
    Setup --> systemd
    
    Main --> Redis
    Main --> Storage
    Main --> Logs
```

### Streamlit Apps
```mermaid
graph LR
    subgraph "Streamlit App"
        App[app.py<br/>Streamlit UI]
        Components[UI Components]
        Widgets[Interactive Widgets]
        Charts[Data Visualization]
    end
    
    subgraph "HomeHelper Integration"
        Manifest[homehelper.json]
        Requirements[requirements.txt]
    end
    
    subgraph "Runtime Management"
        TTL[TTL Manager<br/>300s default]
        Process[Process Spawning]
        Cleanup[Resource Cleanup]
    end
    
    subgraph "System Integration"
        Redis[Redis Pub/Sub]
        Storage[/opt/homehelper/data/app-name/]
        Logs[/opt/homehelper/logs/app-name/]
    end
    
    App --> Components
    App --> Widgets
    App --> Charts
    
    Manifest --> Process
    Requirements --> Process
    
    Process --> TTL
    TTL --> Cleanup
    
    App --> Redis
    App --> Storage
    App --> Logs
```

## Data Flow

### App Discovery Flow
```mermaid
sequenceDiagram
    participant AM as App Manager
    participant FS as File System
    participant Reg as App Registry
    participant Redis as Redis
    
    AM->>FS: Scan ./apps/ directory
    FS->>AM: Return app directories
    
    loop For each app directory
        AM->>FS: Read homehelper.json
        FS->>AM: Return manifest data
        AM->>AM: Validate manifest
        AM->>Reg: Register app
        AM->>Redis: Publish app_discovered event
    end
    
    AM->>Reg: Persist registry to disk
```

### Service App Lifecycle
```mermaid
sequenceDiagram
    participant UI as Web Dashboard
    participant SM as Service Manager
    participant systemd as systemd
    participant App as Service App
    participant Redis as Redis
    
    UI->>SM: Start app request
    SM->>systemd: Generate service file
    SM->>systemd: systemctl start app
    systemd->>App: Launch process
    App->>Redis: Publish app_started event
    App->>SM: Health check response
    SM->>UI: Return app status
    
    Note over App: App runs continuously
    
    UI->>SM: Stop app request
    SM->>systemd: systemctl stop app
    systemd->>App: Terminate process
    App->>Redis: Publish app_stopped event
    SM->>UI: Return app status
```

### Streamlit App Lifecycle
```mermaid
sequenceDiagram
    participant UI as Web Dashboard
    participant UM as UI Manager
    participant Process as Streamlit Process
    participant TTL as TTL Manager
    participant Redis as Redis
    
    UI->>UM: Launch Streamlit app
    UM->>Process: Spawn streamlit run
    Process->>Redis: Publish app_started event
    UM->>TTL: Start TTL timer (300s)
    UM->>UI: Return app URL/modal
    
    Note over Process: User interacts with app
    
    TTL->>TTL: Timer expires
    TTL->>Process: Terminate process
    Process->>Redis: Publish app_stopped event
    TTL->>UM: Cleanup resources
```

## Security Model

### Process Isolation
- Each app runs as separate systemd service
- Apps cannot access each other's data directly
- Shared resources through well-defined interfaces only

### File System Security
- Apps have dedicated data directories
- No cross-app file access
- Logs isolated per application
- Configuration files protected

### Network Security
- Port allocation managed centrally
- Apps communicate via Redis message bus
- No direct inter-app network connections
- Web dashboard proxies app UIs

### Resource Management
- Memory and CPU limits via systemd
- TTL-based cleanup for temporary processes
- Disk usage monitoring and alerts
- Process count limitations

## Deployment Architecture

### Development Environment
```
localhost:8000 (Main Dashboard)
├── localhost:8100-8199 (Service Apps)
├── localhost:8501+ (Streamlit Apps)
└── localhost:6379 (Redis)
```

### Production Environment (Raspberry Pi)
```
raspberrypi.local:8000 (Main Dashboard)
├── Internal:8100-8199 (Service Apps)
├── Internal:8501+ (Streamlit Apps)
└── Internal:6379 (Redis)
```

### File System Layout
```
/opt/homehelper/
├── config/config.json
├── src/homehelper/ (Application code)
├── apps/ (Discovered applications)
├── data/ (Per-app data directories)
├── logs/ (Per-app log directories)
└── registry/ (App registry persistence)
```

## Performance Considerations

### Resource Optimization
- Manual refresh pattern (no auto-updates)
- TTL-based Streamlit cleanup
- Efficient Redis pub/sub usage
- systemd resource limits

### Scalability Targets
- Support 10-20 concurrent apps
- Raspberry Pi 5 with 8GB RAM
- Minimal CPU overhead for main app
- Efficient memory usage patterns

### Monitoring Strategy
- Hardware metrics collection
- Process resource monitoring
- Redis performance tracking
- App health check polling
