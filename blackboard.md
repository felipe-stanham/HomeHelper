# HomeHelper Project Analysis & Planning

## Project Overview
HomeHelper is a unified home automation platform running on Raspberry Pi that manages multiple independent applications through a single dashboard interface.

## Key Architecture Components
1. **Main App** (FastAPI + Web UI) - Central orchestrator
2. **App Manager** - Discovery, installation, registry management
3. **Service Manager** - Systemd integration for background services
4. **UI Manager** - On-demand Streamlit app management
5. **Redis Message Bus** - Inter-app communication
6. **Dashboard** - Web interface for monitoring and control

## Technical Stack
- **Backend**: FastAPI + Uvicorn
- **Frontend**: Jinja2 templates + Bootstrap 5
- **Messaging**: Redis
- **Process Management**: systemd
- **Target**: Raspberry Pi OS (Debian-based)
- **Python**: 3.9+

## App Types
1. **Service Apps**: Long-running background services with REST APIs
2. **Streamlit Apps**: On-demand interactive UIs with TTL management

## Key Features to Implement
- Auto-discovery of apps in `./apps/` directory
- Dynamic port assignment for service apps
- Health monitoring and dashboard
- Service lifecycle management (start/stop/restart)
- Redis message bus integration
- Modal Streamlit app integration
- UI proxy for service apps
- System resource monitoring

## UI/UX Considerations
- Bootstrap 5 responsive design
- Manual refresh pattern (no auto-updates)
- Status indicators with color coding
- Card-based app display
- Modal overlays for Streamlit apps and service UI rendering
- Comprehensive log viewing

## Shared directories
- `data/`: Shared app data storage. Each app has its own subdirectory.
- `logs/`: Shared app logging. Each app has its own subdirectory. There is no standard format for logging, each app is responsible for its own logging.

## Sample Apps Needed
- A streamlit and a service app will be provided for testing.

## File System Structure
```
/opt/homehelper/
├── main/                 # Main application
├── apps/                 # App directories
├── data/                 # Shared app data storage
├── logs/                 # Shared app logging
└── config/               # System configuration
```
