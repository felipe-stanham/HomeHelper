# P-0005 Architecture

## Before / after component diagram

### Before (current — subprocess active, systemd dormant)

```mermaid
flowchart LR
    subgraph SystemSystemd[systemd system]
        MainUnit[latarnia-tst.service]
    end

    subgraph Platform[Latarnia main process PID M]
        Main[main.py]
        AppMgr[AppManager]
        SM[ServiceManager<br/>dormant]
        MPM[MacOSProcessManager<br/>active]
        StM[StreamlitManager]
        HM[HealthMonitor]
        MCP[MCPGateway]
    end

    subgraph Children[Platform process children]
        App1[app_a PID X]
        App2[app_b PID Y]
        StApp[streamlit_c PID Z]
    end

    MainUnit --> Main
    Main --> AppMgr
    Main -->|"auto_start"| MPM
    MPM -.Popen.-> App1
    MPM -.Popen.-> App2
    StM -.Popen.-> StApp
    Main --> HM
    HM -.HTTP /health.-> App1
    HM -.HTTP /health.-> App2

    ApiApps["/api/apps/{id}/process/*<br/>(subprocess REST)"] --> MPM
    ApiSvc["/api/services/*<br/>(systemd REST, unused)"] -.dormant.-> SM

    style SM fill:#f5f5f5,stroke-dasharray:5 5
    style ApiSvc fill:#f5f5f5,stroke-dasharray:5 5
```

### After (P-0005 — systemd active on Linux, subprocess macOS-only)

```mermaid
flowchart LR
    subgraph SystemSystemd[systemd system]
        MainUnit[latarnia-tst.service]
    end

    subgraph UserSystemd["systemd --user (linger on)"]
        UA[latarnia-tst-app_a.service]
        UB[latarnia-tst-app_b.service]
    end

    subgraph Platform[Latarnia main process PID M]
        Main[main.py]
        Router[LaunchRouter<br/>os+type → target]
        SM[ServiceManager<br/>active on Linux]
        Sub[SubprocessLauncher<br/>macOS fallback]
        StM[StreamlitManager]
        HM[HealthMonitor]
        MCP[MCPGateway]
    end

    subgraph Apps[App processes]
        App1[app_a PID X<br/>child of UA]
        App2[app_b PID Y<br/>child of UB]
        StApp[streamlit_c PID Z<br/>child of platform]
    end

    MainUnit --> Main
    Main --> Router
    Router -->|Linux + service| SM
    Router -->|Darwin + service| Sub
    Router -->|any + streamlit| StM
    SM -.systemctl --user start.-> UA
    SM -.systemctl --user start.-> UB
    UA -->|ExecStart venv python| App1
    UB -->|ExecStart venv python| App2
    StM -.Popen.-> StApp

    HM -.systemctl show.-> UA
    HM -.systemctl show.-> UB
    HM -.HTTP /health.-> App1
    HM -.HTTP /health.-> App2

    ApiSvc["/api/services/*"] --> SM
    ApiApps["/api/apps/{id}/process/*"] -.route on Linux.-> SM

    style Router fill:#e1f5ff
    style SM fill:#e1f5ff
    style Sub fill:#fff4e1
```

The `LaunchRouter` is a thin dispatch in `main.py` / the start path — not a new class with its own state. It just picks a target based on `(platform.system(), manifest.type)`.

---

## Deployment topology (Pi, after P-0005)

```mermaid
flowchart TB
    subgraph Pi["Raspberry Pi 5 (HERMES, 192.168.68.100)"]
        subgraph SystemScope["System-scope systemd (/etc/systemd/system/)"]
            TstUnit["latarnia-tst.service<br/>User=felipe, :8000"]
            PrdUnit["latarnia-prd.service<br/>User=felipe, :8080"]
        end

        subgraph UserScopeTst["~felipe/.config/systemd/user/ (TST)"]
            TstApp1[latarnia-tst-app_a.service]
            TstApp2[latarnia-tst-app_b.service]
            TstAppN[latarnia-tst-app_N.service]
        end

        subgraph UserScopePrd["~felipe/.config/systemd/user/ (PRD)"]
            PrdApp1[latarnia-prd-app_a.service]
            PrdApp2[latarnia-prd-app_b.service]
        end

        subgraph TstVenv["/opt/latarnia/tst/.venv/"]
            TstPython[bin/python]
        end

        subgraph PrdVenv["/opt/latarnia/prd/.venv/"]
            PrdPython[bin/python]
        end

        TstUnit --> TstPython
        PrdUnit --> PrdPython
        TstApp1 --> TstPython
        TstApp2 --> TstPython
        TstAppN --> TstPython
        PrdApp1 --> PrdPython
        PrdApp2 --> PrdPython

        Redis[(Redis :6379<br/>shared)]
        Pg[(Postgres :5432<br/>shared instance<br/>per-env DBs)]

        TstApp1 -.--> Redis
        TstApp2 -.--> Pg
        PrdApp1 -.--> Redis
        PrdApp2 -.--> Pg
    end

    Browser[Browser<br/>laptop] -->|:8000| TstUnit
    Browser -->|:8080| PrdUnit
```

Key properties:
- **System-scope** units for the main platforms — one per env, sudo to install.
- **User-scope** units for per-app services — generated at runtime by `ServiceManager`, no sudo needed. Linger enabled so they persist across login sessions.
- **One venv per env** — shared by the main platform and all its per-app units. `ExecStart` points to the absolute venv Python path.
- **Shared Redis and Postgres** at the host level; per-app DBs are provisioned under a single Postgres instance by env-scoped role/db prefixes.

---

## External system interactions

```mermaid
flowchart LR
    subgraph Pi[Pi]
        Platform[Latarnia platform<br/>main unit]
        AppUnit[Per-app systemd unit]
        App[App process]
    end

    Journal[(systemd journal)]
    Browser[Dashboard browser]
    MCPClient[MCP AI client<br/>Claude / IDE]

    Platform -.systemctl --user.-> AppUnit
    AppUnit -->|ExecStart| App
    App -->|stdout/stderr| Journal
    AppUnit -->|unit events| Journal
    Browser -->|HTTP :8000 dashboard| Platform
    Browser -->|HTTP :8000 /apps/{x}/| Platform
    Platform -->|HTTP proxy :81xx| App
    MCPClient -->|SSE :8000/mcp/sse| Platform
    Platform -->|SSE :9xxx| App
```

The dashboard and MCP paths are unchanged from today. The new arrow is `Platform -.systemctl --user.-> AppUnit` replacing `Platform -.Popen.-> App` from the before diagram.

---

## Data flow between components

```mermaid
sequenceDiagram
    participant User
    participant Dash as Dashboard
    participant Platform
    participant SM as ServiceManager
    participant USyst as systemd (--user)
    participant App
    participant HM as HealthMonitor

    User->>Dash: load page
    Dash->>Platform: GET /api/apps
    Platform->>HM: get_all_app_health()
    HM->>USyst: systemctl show (batched)
    USyst-->>HM: unit states
    HM->>App: /health (per active app)
    App-->>HM: {status, detail}
    HM-->>Platform: combined states
    Platform-->>Dash: JSON
    Dash-->>User: cards render

    User->>Dash: click "Restart"
    Dash->>Platform: POST /api/services/{id}/restart
    Platform->>SM: restart_service(id)
    SM->>USyst: systemctl --user restart
    USyst-->>App: SIGTERM, then respawn
    App-->>USyst: ready
    USyst-->>SM: active
    SM-->>Platform: OK
    Platform-->>Dash: 200
```

No data model changes. No new tables, no new config fields. The only persistent new artifact is the per-app unit file under `~/.config/systemd/user/`, which is not project data — it's generated output.
