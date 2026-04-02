# System: Latarnia

## What This System Does
Latarnia is a unified home automation platform for Raspberry Pi 5 (8GB RAM) that manages multiple independent applications through a single web dashboard. It provides auto-discovery, lifecycle management (via systemd), health monitoring, and a Redis-based message bus for inter-app communication. Apps can be either long-running **Service Apps** (FastAPI with REST APIs) or on-demand **Streamlit Apps** (with TTL-based cleanup).

## Architecture Principles
- **Manual refresh pattern**: No auto-updates to reduce Pi resource usage
- **App independence**: Each app is fully self-contained with its own dependencies, data directory, and logs
- **Centralized shared resources**: Data (`data/`) and logs (`logs/`) directories are shared but organized per-app
- **Modal UI strategy**: Both Streamlit apps and service app UIs render in modals on the dashboard
- **JSON-based persistence**: Config, registry, and app data stored as JSON files (no database)
- **Redis message bus**: All inter-app communication goes through Redis pub/sub
- **systemd integration**: Service apps managed as systemd units for reliability

## Cross-Project Constraints
- Target hardware: Raspberry Pi 5 with 8GB RAM running Raspberry Pi OS (Debian-based)
- Tech stack: Python 3.9+, FastAPI, Bootstrap 5, Redis
- Port ranges: Main app on 8000, service apps on 8100-8199, Streamlit apps on 8501+
- Production deployment path: `/opt/latarnia/`
- All apps must provide a `latarnia.json` manifest and `requirements.txt`
- App specification details in `docs/System/app-specification.md`

## Projects
| ID      | Name            | Status      | Summary                                              |
|---------|-----------------|-------------|------------------------------------------------------|
| P-0001  | Latarnia Core | [DONE]      | Full platform: core infra, app/service/UI management, dashboard, deployment |
| P-0002  | Latarnia        | [DONE]      | Platform rename + evolved manifests, Postgres, MCP gateway, Redis Streams, web UI proxy |

## Deployment

### Procedure
1. Run regression tests (`TESTS.md`) — all must pass
2. Build the project for the target environment
3. Read `.deploy-secrets` for the target
4. SSH to the target and deploy
5. Run smoke tests against the deployed instance
6. Log the deployment in `DEPLOYMENTS.md`

### Targets
| Target      | Environments | Description                        |
|-------------|--------------|------------------------------------|
| local       | dev          | Developer workstation (macOS)      |
| homeserver  | dev, tst, prd| Raspberry Pi 5 — self-hosted multi-environment |
