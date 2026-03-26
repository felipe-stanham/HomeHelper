# P-0002: Latarnia Architecture

## System Overview

```mermaid
graph TB
    subgraph External
        MCPClient["MCP Client (Claude Desktop, etc.)"]
        Browser[Web Browser]
    end

    subgraph Latarnia_Platform["Latarnia Platform"]
        subgraph Platform_Core["Platform Core :8000"]
            FastAPI[FastAPI Web Server]
            MCPGateway["MCP Gateway (/mcp)"]
            WebProxy["Web UI Proxy (/apps/name/)"]
            AppMgr["App Manager (Discovery + Registry)"]
            SvcMgr["Service Manager (systemd)"]
            UIMgr["UI Manager (Streamlit TTL)"]
            DBProvisioner["DB Provisioner (Postgres)"]
            StreamMgr["Stream Manager (Redis Streams)"]
            SysMon[System Monitor]
            Dashboard["Dashboard (Bootstrap 5)"]
        end

        subgraph Data_Layer["Data Layer"]
            Redis[("Redis (Pub/Sub + Streams)")]
            Postgres[("Postgres (Per-app databases)")]
            ConfigFiles["Config Files (JSON)"]
            RegistryFile["Registry (JSON + Memory)"]
        end

        subgraph Applications
            App1["Service App: REST + MCP + Web UI"]
            App2["Service App: REST only"]
            App3["Agent App: REST + MCP + LLM"]
            App4["Streamlit App: On-demand UI"]
        end

        subgraph System
            systemdSvc["systemd (Process Management)"]
        end
    end

    MCPClient -->|MCP Protocol| MCPGateway
    Browser -->|HTTP| FastAPI
    Browser -->|HTTP| WebProxy

    FastAPI --> Dashboard
    FastAPI --> AppMgr
    FastAPI --> SvcMgr
    FastAPI --> UIMgr
    FastAPI --> SysMon

    MCPGateway -->|MCP HTTP| App1
    MCPGateway -->|MCP HTTP| App3

    WebProxy -->|HTTP Proxy| App1

    AppMgr --> DBProvisioner
    AppMgr --> StreamMgr
    AppMgr --> RegistryFile
    AppMgr --> ConfigFiles

    DBProvisioner --> Postgres
    StreamMgr --> Redis

    SvcMgr --> systemdSvc
    systemdSvc --> App1
    systemdSvc --> App2
    systemdSvc --> App3
    UIMgr --> App4

    App1 --> Redis
    App1 --> Postgres
    App2 --> Redis
    App3 --> Redis
    App3 --> Postgres
    App4 --> Redis
```

---

## Component Architecture

### Platform Core Modules

```mermaid
graph LR
    subgraph FastAPI_App["FastAPI Application"]
        direction TB
        Main["main.py - Lifespan + Router setup"]

        subgraph Routers
            DashRouter["Dashboard Router (GET /)"]
            AppRouter["App API Router (/api/apps/*)"]
            SystemRouter["System API Router (/api/system/*)"]
            MCPRouter["MCP Gateway Router (/mcp)"]
            ProxyRouter["Web UI Proxy Router (/apps/name/*)"]
        end

        subgraph Core_Modules["Core Modules"]
            AppManager["app_manager.py - Discovery, Registry, Dependencies"]
            ServiceManager["service_manager.py - systemd, Health, Lifecycle"]
            UIManager["ui_manager.py - Streamlit TTL"]
            DBProvisioner2["db_provisioner.py - Postgres lifecycle + migrations"]
            StreamManager["stream_manager.py - Redis Streams setup"]
            MCPGateway2["mcp_gateway.py - Tool index, proxy, namespace"]
            WebProxy2["web_proxy.py - HTTP reverse proxy"]
            SystemMonitor["system_monitor.py - Hardware metrics"]
        end

        subgraph Shared
            Config["config.py - JSON config loader"]
            RedisClient["redis_client.py - Pub/Sub + Streams"]
            PGClient["pg_client.py - Postgres superuser ops"]
            Models["models.py - Pydantic schemas"]
        end
    end

    Main --> DashRouter
    Main --> AppRouter
    Main --> SystemRouter
    Main --> MCPRouter
    Main --> ProxyRouter

    AppRouter --> AppManager
    AppRouter --> ServiceManager
    MCPRouter --> MCPGateway2
    ProxyRouter --> WebProxy2

    AppManager --> DBProvisioner2
    AppManager --> StreamManager
    ServiceManager --> MCPGateway2

    DBProvisioner2 --> PGClient
    StreamManager --> RedisClient
    MCPGateway2 --> RedisClient
    AppManager --> Config
    AppManager --> Models
```

---

## MCP Gateway Architecture

The gateway acts as a single MCP server endpoint that aggregates tools from all MCP-enabled apps.

```mermaid
graph TB
    subgraph MCP_GW["MCP Gateway :8000/mcp"]
        Endpoint["MCP Server Endpoint (SSE / Streamable HTTP)"]
        ToolIndex["Tool Index (Namespaced tool registry)"]
        ToolRouter["Tool Router (app_name to port mapping)"]
        HealthFilter["Health Filter (Skip unhealthy apps)"]
    end

    subgraph App_MCP["App MCP Servers"]
        CRM_MCP["CRM MCP Server :9001"]
        KB_MCP["KB MCP Server :9002"]
        Agent_MCP["Agent MCP Server :9003"]
    end

    Client[MCP Client] -->|1. Connect| Endpoint
    Endpoint -->|2. list_tools| ToolIndex
    ToolIndex -->|3. Return namespaced tools| Endpoint

    Client -->|4. Call crm.add_contact| Endpoint
    Endpoint -->|5. Parse namespace| ToolRouter
    ToolRouter -->|6. Check health| HealthFilter
    HealthFilter -->|7. Proxy call| CRM_MCP
    CRM_MCP -->|8. Response| Endpoint
    Endpoint -->|9. Return result| Client
```

### Tool Index Structure

```
{
    "crm.add_contact":    { app: "crm", port: 9001, tool: "add_contact" },
    "crm.search_contacts": { app: "crm", port: 9001, tool: "search_contacts" },
    "kb.query":           { app: "kb",  port: 9002, tool: "query" },
    "kb.add_document":    { app: "kb",  port: 9002, tool: "add_document" }
}
```

### Gateway Behavior Rules
- Tool index is rebuilt on: platform startup, app start/stop, app version bump
- Tool calls to unhealthy apps return an error immediately (no timeout waiting)
- Namespace format is always `{app_name}.{tool_name}` — no nesting
- If two apps somehow expose tools with the same namespaced name, the second registration fails (enforced by unique app names)

---

## Data Flow Architecture

```mermaid
graph LR
    subgraph Sync["Synchronous Path"]
        direction LR
        MCPClient2[MCP Client] -->|Tool call| Gateway[MCP Gateway]
        Gateway -->|HTTP| AppMCP[App MCP Server]
        AppMCP -->|Query/Write| AppDB[(App Postgres DB)]
        AppMCP -->|Response| Gateway
        Gateway -->|Result| MCPClient2
    end

    subgraph Async["Asynchronous Path"]
        direction LR
        AppA[App A] -->|XADD| Stream[(Redis Stream)]
        Stream -->|XREADGROUP| AppB[App B]
        AppB -->|Process| AppBDB[(App B Postgres DB)]
        AppB -->|XACK| Stream
    end

    subgraph Monitor["Monitoring Path"]
        direction LR
        Dash[Dashboard] -->|GET /api/apps| Platform[Platform API]
        Platform -->|GET /health| AppHealth["App REST (/health)"]
        AppHealth -->|Status| Platform
        Platform -->|JSON| Dash
    end
```

---

## Deployment Topology

### Production (Raspberry Pi 5 / VPS)

```
Machine
├── Postgres (pre-installed, port 5432)
│   ├── latarnia_crm        (app database)
│   ├── latarnia_kb          (app database)
│   └── latarnia_scraper     (app database)
│
├── Redis (port 6379)
│   ├── Pub/Sub channels     (platform events)
│   └── Streams              (app→app communication)
│
├── Latarnia Platform (port 8000)
│   ├── Dashboard            (GET /)
│   ├── API                  (GET /api/*)
│   ├── MCP Gateway          (SSE /mcp)
│   └── Web UI Proxy         (GET /apps/*)
│
├── Service Apps
│   ├── CRM App              (REST :8101, MCP :9001, Web UI via proxy)
│   ├── Knowledge Base       (REST :8102, MCP :9002)
│   ├── Scraper Agent        (REST :8103, MCP :9003)
│   └── Sensor Monitor       (REST :8104, no MCP)
│
└── Streamlit Apps (on-demand)
    └── Config Editor        (:8501, TTL-managed)
```

### Port Allocation

| Range | Purpose |
|-------|---------|
| 5432 | Postgres (pre-existing) |
| 6379 | Redis |
| 8000 | Latarnia platform (dashboard, API, MCP gateway, web proxy) |
| 8100-8199 | Service app REST/HTTP servers |
| 8501+ | Streamlit apps (on-demand) |
| 9001-9099 | Service app MCP servers (declared in manifest) |

---

## External System Interactions

```mermaid
graph LR
    subgraph Lat_Plat["Latarnia Platform"]
        Platform[Platform Core]
        Apps[Apps]
    end

    subgraph Infra["Infrastructure (pre-existing)"]
        PG[(Postgres)]
        Redis2[(Redis)]
        systemd2[systemd]
    end

    subgraph Ext_Clients["External Clients"]
        Claude[Claude Desktop]
        OtherMCP[Other MCP Clients]
        Browser2[Web Browser]
    end

    subgraph Ext_Services["External Services (app-level)"]
        APIs["Third-party APIs (per app responsibility)"]
        LLMs["LLM APIs: Claude, OpenAI, etc. (agent-apps only)"]
    end

    Platform --> PG
    Platform --> Redis2
    Platform --> systemd2

    Claude --> Platform
    OtherMCP --> Platform
    Browser2 --> Platform

    Apps --> APIs
    Apps --> LLMs
    Apps --> PG
    Apps --> Redis2
```

**Key boundary:** The platform manages Postgres provisioning and Redis Streams setup but does NOT intermediate app-level data access. Apps connect to their own Postgres database and Redis streams directly at runtime.

---

## Security Model (Evolved)

### Database Isolation
- Each app gets a dedicated Postgres database and role
- Role can only CONNECT to its own database (enforced by Postgres, not convention)
- Platform superuser used for provisioning only; connection string never passed to apps
- Apps cannot query other apps' databases

### Network Isolation
- MCP gateway validates tool calls against the registered tool index — apps cannot be called with arbitrary tool names
- Web UI proxy validates that the target app exists and has `has_web_ui: true`
- Redis Streams enforce consumer group isolation — apps can only read from groups they own

### Process Isolation (unchanged)
- Each app runs as a separate systemd service
- Resource limits via systemd cgroups
- Apps cannot access each other's file system data directories

### Trust Model
- v1 assumes a trusted network (single operator, local deployment)
- No MCP authentication in v1 — any client that can reach port 8000 can invoke tools
- No Redis AUTH in v1 — assumed localhost-only deployment
- Postgres roles provide app-level isolation but no encryption in transit
