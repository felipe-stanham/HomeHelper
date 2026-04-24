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
- Port ranges: Main app on 8000, service apps on 8100-8199, MCP servers on 9001-9099, Streamlit apps on 8501+
- Environment port isolation (homeserver multi-env):

| Resource | TST Range | PRD Range |
|----------|-----------|-----------|
| REST API ports | 8100–8149 | 8150–8199 |
| MCP ports | 9001–9049 | 9050–9099 |

- Production deployment path: `/opt/latarnia/`
- All apps must provide a `latarnia.json` manifest and `requirements.txt`
- App specification details in `docs/System/app-specification.md`

## Projects
| ID      | Name            | Status      | Summary                                              |
|---------|-----------------|-------------|------------------------------------------------------|
| P-0001  | Latarnia Core | [DONE]      | Full platform: core infra, app/service/UI management, dashboard, deployment |
| P-0002  | Latarnia        | [DONE]      | Platform rename + evolved manifests, Postgres, MCP gateway, Redis Streams, web UI proxy |
| P-0003  | Dynamic MCP Port Allocation | [DONE] | Runtime allocation of MCP ports from configured range |
| P-0004  | Env-Scoped Services | [DONE]      | Env-scope per-app systemd units + bootstrap docs for main platform units |

## Testing Tools

| Tool        | Config location  | Purpose                                                |
|-------------|------------------|--------------------------------------------------------|
| pytest      | `tests/unit/`    | Unit tests with mocks — run via `python3 -m pytest tests/ -v --tb=short --no-cov` |
| Playwright MCP | `.mcp.json`  | Browser-level testing for dashboards and web UIs — available as `playwright` MCP server |
| latarnia-tst MCP | `.mcp.json` | SSE connection to TST environment — interact with deployed app tools |

MCP servers are configured in `.mcp.json` at the project root.

### Integration Test Fixtures

`example_full_app` and `example_companion` (in `examples/`) are the integration test fixtures for the platform. They exercise every platform feature: Postgres DB with migrations, MCP server with tools, Redis Streams pub/sub, web UI proxy, and app dependencies. Any change to a platform feature must be accompanied by a corresponding update to `example_full_app` that exercises that feature.

> **Source of truth:** `examples/` is committed to git. `apps/` is gitignored and populated from `examples/` during deployment. All changes to example apps must be made in `examples/`, never in `apps/`.

To run integration tests locally, copy examples to `apps/`:
```
cp -r examples/example_full_app apps/
cp -r examples/example_companion apps/
```

## Deployment

### Procedure
1. Run regression tests (`TESTS.md`) — all must pass
2. Read `.deploy-secrets` for the target
3. SSH to the target, `git pull` the correct branch
4. **DEV/TST only:** Copy example apps to `apps/`:
   ```
   cp -r examples/example_full_app apps/
   cp -r examples/example_companion apps/
   ```
   PRD does **not** deploy example apps — only real apps live in PRD `apps/`.
5. Restart the service
6. Run smoke tests against the deployed instance
7. Log the deployment in `DEPLOYMENTS.md`

### Targets
| Target      | Environments | Host             | Description                        |
|-------------|--------------|------------------|------------------------------------|
| local       | dev          | localhost        | Developer workstation (macOS)      |
| homeserver  | tst, prd     | 192.168.68.100   | Raspberry Pi 5 (8GB) — self-hosted multi-environment |

### Environment Isolation (homeserver)

Single Raspberry Pi runs both TST and PRD side-by-side, isolated by:

| Resource         | TST                        | PRD                        |
|------------------|----------------------------|----------------------------|
| Deploy path      | `/opt/latarnia/tst`        | `/opt/latarnia/prd`        |
| Git branch       | `tst`                      | `main`                     |
| Main app port    | 8000                       | 8080                       |
| Service app ports| 8100-8149                  | 8150-8199                  |
| Streamlit port   | 8501                       | 8551                       |
| DB prefix        | `tst_latarnia_`            | `prd_latarnia_`            |
| Redis DB         | 0                          | 1                          |
| Logs             | `/opt/latarnia/tst/logs`   | `/opt/latarnia/prd/logs`   |
| Data             | `/opt/latarnia/tst/data`   | `/opt/latarnia/prd/data`   |
| Update method    | `git pull` on tst branch   | `git pull` on main branch  |
