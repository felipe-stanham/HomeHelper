# Latarnia Workflows

This document covers the main process flows and interaction patterns in Latarnia. For component architecture and lifecycle sequence diagrams, see [architecture.md](architecture.md).

## 1. Application Startup

What happens when the Latarnia main application starts (the `lifespan` function in `main.py`).

```mermaid
flowchart TD
    Start([FastAPI Lifespan Start]) --> CreateDirs[Create data/ and logs/ directories]
    CreateDirs --> SetupLog[Setup logging]
    SetupLog --> CheckRedis{Redis running?}

    CheckRedis -- Yes --> Discover[Scan ./apps/ directory]
    CheckRedis -- No --> AutoStart[Attempt to start Redis<br/>via brew/systemctl]
    AutoStart --> RedisOk{Redis started?}
    RedisOk -- Yes --> Discover
    RedisOk -- No --> LogWarn[Log error, continue without Redis]
    LogWarn --> Discover

    Discover --> Loop{More apps<br/>to check?}
    Loop -- Yes --> AutoCheck{Service app with<br/>auto_start = true?}
    AutoCheck -- Yes --> StartApp[Start app via ProcessManager]
    AutoCheck -- No --> Loop
    StartApp --> Loop
    Loop -- No --> StartSub[Start Redis Event Subscriber<br/>psubscribe latarnia:events:*]
    StartSub --> Ready([Application Ready])

    Ready -.-> Shutdown([Shutdown Signal])
    Shutdown --> StopSub[Stop Event Subscriber]
    StopSub --> StopServices[Stop all managed service apps]
    StopServices --> StopStreamlit[Stop all Streamlit apps]
    StopStreamlit --> Done([Shutdown Complete])
```

## 2. App Installation and Discovery

Decision logic when the App Manager scans the `./apps/` directory and processes each app folder.

```mermaid
flowchart TD
    Trigger([Discover Apps called]) --> Scan[Scan ./apps/ directory<br/>for subdirectories]
    Scan --> NextDir{Next directory?}

    NextDir -- None left --> Persist[Persist registry to disk]
    Persist --> Done([Return discovered count])

    NextDir -- Found --> HasManifest{latarnia.json<br/>exists?}
    HasManifest -- No --> SkipDir[Skip directory, log warning]
    SkipDir --> NextDir

    HasManifest -- Yes --> Parse[Parse manifest JSON]
    Parse --> Valid{Manifest valid?<br/>Required fields present?}
    Valid -- No --> LogError[Log validation error]
    LogError --> NextDir

    Valid -- Yes --> AlreadyReg{Already in<br/>registry?}
    AlreadyReg -- Yes --> NextDir

    AlreadyReg -- No --> AllocPort[Allocate port from<br/>8100-8199 range]
    AllocPort --> PortOk{Port available?}
    PortOk -- No --> LogPortErr[Log port allocation error]
    LogPortErr --> NextDir

    PortOk -- Yes --> InstallDeps[Install requirements.txt<br/>via pip]
    InstallDeps --> RunSetup[Run setup_commands<br/>from manifest]
    RunSetup --> Register[Register app in registry<br/>with assigned port]
    Register --> PublishEvent[Publish app_discovered<br/>event to Redis]
    PublishEvent --> NextDir
```

## 3. Dashboard UI Interaction

How a user navigates the web dashboard and interacts with apps through modals.

```mermaid
sequenceDiagram
    participant User as User Browser
    participant Dash as Dashboard<br/>(FastAPI + Bootstrap)
    participant API as Latarnia API
    participant SvcApp as Service App
    participant StMgr as Streamlit Manager
    participant StApp as Streamlit Process

    User->>Dash: Open dashboard (GET /)
    Dash->>API: GET /api/apps
    Dash->>API: GET /api/system/metrics
    Dash->>API: GET /api/activity/recent
    API-->>Dash: App list, metrics, events
    Dash-->>User: Render app cards + system status

    User->>Dash: Click Refresh button
    Dash->>API: Re-fetch all data
    API-->>Dash: Updated data
    Dash-->>User: Re-render dashboard

    Note over User,StApp: Service App UI Flow

    User->>Dash: Click service app card
    Dash->>API: GET /api/apps/{id}/ui/resources
    API->>SvcApp: GET /ui
    SvcApp-->>API: ["readings", "alerts"]
    API-->>Dash: Resource list
    Dash-->>User: Open modal with resource tabs

    User->>Dash: Select resource tab
    Dash->>API: GET /api/apps/{id}/ui/{resource}
    API->>SvcApp: GET /api/{resource}
    SvcApp-->>API: Resource data (JSON)
    API-->>Dash: Rendered HTML table
    Dash-->>User: Display table in modal

    Note over User,StApp: Streamlit App UI Flow

    User->>Dash: Click Streamlit app card
    Dash->>API: POST /api/apps/{id}/streamlit/launch
    API->>StMgr: Launch or get existing instance
    StMgr->>StApp: Spawn streamlit process (if needed)
    StMgr-->>API: {url, port, ttl}
    API-->>Dash: Streamlit URL
    Dash-->>User: Open modal with iframe to Streamlit

    User->>Dash: Interact with Streamlit iframe
    Dash->>API: POST /api/apps/{id}/streamlit/touch
    Note right of StMgr: TTL timer resets on each touch
```

## 4. Health Check Monitoring

How the HealthMonitor periodically checks service app health and tracks failures.

```mermaid
flowchart TD
    Start([Health Monitor Started]) --> Wait[Wait for check interval<br/>default: 30 seconds]
    Wait --> GetApps[Get all running<br/>service apps from registry]
    GetApps --> NextApp{Next running<br/>service app?}

    NextApp -- None left --> Wait

    NextApp -- Found --> CallHealth[HTTP GET /health<br/>on app port]
    CallHealth --> Timeout{Response within<br/>timeout?}

    Timeout -- No --> IncFail[Increment consecutive<br/>failure count]
    Timeout -- Yes --> ParseResp[Parse health response<br/>good / warning / error]

    ParseResp --> StatusGood{Status = good?}
    StatusGood -- Yes --> ResetFail[Reset failure count]
    ResetFail --> StoreResult[Store HealthCheckResult<br/>with response time]
    StoreResult --> NextApp

    StatusGood -- No --> StoreWarn[Store result with<br/>warning or error status]
    StoreWarn --> NextApp

    IncFail --> ThresholdCheck{Failures >= threshold?}
    ThresholdCheck -- No --> StoreTimeout[Store result as UNKNOWN]
    StoreTimeout --> NextApp
    ThresholdCheck -- Yes --> MarkError[Mark app health as ERROR]
    MarkError --> NextApp
```

## 5. MCP Gateway — Tool Discovery and Routing

How the MCP gateway aggregates tools from all MCP-enabled apps at startup and routes tool calls from external clients. References cap-006 and flow-05 in P-0002.

```mermaid
sequenceDiagram
    participant Client as MCP Client
    participant GW as MCP Gateway :8000/mcp
    participant Reg as App Registry
    participant App1 as App1 MCP Server
    participant App2 as App2 MCP Server

    Note over GW: Platform startup — build tool index

    GW->>Reg: Get all MCP-enabled apps
    Reg-->>GW: app1 (port 9001), app2 (port 9002)

    GW->>App1: MCP SSE connect + list_tools
    App1-->>GW: [tool_a, tool_b]
    GW->>App2: MCP SSE connect + list_tools
    App2-->>GW: [tool_c]

    GW->>GW: Build namespaced index<br/>app1.tool_a, app1.tool_b, app2.tool_c

    Note over Client,App2: Runtime — client connects via SSE

    Client->>GW: GET /mcp/sse (SSE connect)
    Client->>GW: initialize + list_tools
    GW-->>Client: app1.tool_a, app1.tool_b, app2.tool_c

    Client->>GW: call_tool(app1.tool_a, args)
    GW->>Reg: Is app1 healthy?
    Reg-->>GW: Yes
    GW->>App1: call_tool(tool_a, args)
    App1-->>GW: result content
    GW-->>Client: result content

    Note over Client,App2: Unhealthy app scenario

    Client->>GW: call_tool(app2.tool_c, args)
    GW->>Reg: Is app2 healthy?
    Reg-->>GW: No (health check failed)
    GW-->>Client: Error: App app2 is currently unavailable
```

## 6. MCP Tool Sync on App Lifecycle Events

How the gateway keeps the tool index in sync when apps start, stop, or undergo a version bump. References cap-006, cap-011.

```mermaid
flowchart TD
    Event([App lifecycle event]) --> Type{Event type?}

    Type -- App started --> HasMCP{"App has
    mcp_server: true?"}
    HasMCP -- No --> Done([No MCP action])
    HasMCP -- Yes --> FetchTools[list_tools from app MCP server]
    FetchTools --> GotTools{Tools returned?}
    GotTools -- No --> LogWarn[Log warning, index unchanged]
    LogWarn --> Done

    GotTools -- Yes --> HasOldTools{Prior tools
    registered?}
    HasOldTools -- No --> AddToIndex[Add namespaced tools to index]
    HasOldTools -- Yes --> CompatCheck{Backward compat OK?
    set_diff old minus new = empty?}
    CompatCheck -- No --> MarkUnhealthy["Mark app mcp_info.healthy = False.
    Return HTTP 409.
    App stopped."]
    MarkUnhealthy --> Done

    CompatCheck -- Yes --> RemoveOld[Remove old tools for app from index]
    RemoveOld --> AddToIndex
    AddToIndex --> UpdateReg["Update registry: registered_tools,
    last_tool_sync, healthy=True"]
    UpdateReg --> Done

    Type -- App stopped --> RemoveTools[Remove all tools for app from index]
    RemoveTools --> Done

    Type -- Version bump --> FetchTools
```

## 7. Redis Event Pub/Sub Flow

How apps publish events through Redis and how the Latarnia event subscriber captures them for the dashboard activity feed.

```mermaid
sequenceDiagram
    participant AppA as App A<br/>(Publisher)
    participant Redis as Redis<br/>(Message Bus)
    participant Sub as Latarnia<br/>Event Subscriber
    participant Store as Redis List<br/>latarnia:events:recent
    participant AppB as App B<br/>(Subscriber)
    participant Dash as Dashboard API

    Note over Sub: Background thread<br/>psubscribe latarnia:events:*

    AppA->>Redis: PUBLISH latarnia:events:motion.detected<br/>{source, event_type, timestamp, data}

    par Fan-out to all subscribers
        Redis->>Sub: Deliver message to Latarnia subscriber
        Redis->>AppB: Deliver message to App B subscriber
    end

    Sub->>Sub: Parse JSON event
    Sub->>Store: RPUSH event to recent events list
    Sub->>Store: LTRIM to max_events (default 100)

    AppB->>AppB: Handle event in<br/>subscriber callback

    Note over Dash,Store: Later, when user refreshes dashboard

    Dash->>Store: LRANGE latarnia:events:recent
    Store-->>Dash: Recent events list
    Dash->>Dash: Format timestamps,<br/>extract messages
```

## 8. Web UI Reverse Proxy Request Flow

How the platform proxies HTTP and WebSocket requests to app-owned web UIs. References cap-008 in P-0002.

```mermaid
sequenceDiagram
    participant Browser as User Browser
    participant Proxy as Web Proxy<br/>/apps/{name}/{path}
    participant Reg as App Registry
    participant App as App Web Server<br/>:810x

    Browser->>Proxy: GET /apps/crm/ (HTTP)
    Proxy->>Reg: Lookup app crm
    Reg-->>Proxy: port=8101, has_web_ui=true, running

    Proxy->>App: GET / + X-Forwarded-For/Proto/Host headers
    App-->>Proxy: 200 OK (HTML)
    Proxy-->>Browser: 200 OK (HTML, stripped response headers)

    Note over Browser,App: Static assets

    Browser->>Proxy: GET /apps/crm/static/style.css
    Proxy->>App: GET /static/style.css
    App-->>Proxy: 200 OK (CSS)
    Proxy-->>Browser: 200 OK (CSS)

    Note over Browser,App: WebSocket upgrade (via aiohttp)

    Browser->>Proxy: GET /apps/crm/ws (Upgrade: websocket)
    Proxy->>App: WS connect ws://localhost:8101/ws
    App-->>Proxy: 101 Switching Protocols
    Proxy-->>Browser: 101 Switching Protocols
    Browser->>Proxy: WS frames (bidirectional relay)
    Proxy->>App: WS frames (bidirectional relay)

    Note over Browser,App: Error scenarios

    Browser->>Proxy: GET /apps/offline_app/
    Proxy->>Reg: Lookup offline_app
    Reg-->>Proxy: status=stopped
    Proxy-->>Browser: 503 App Unavailable (HTML error page)

    Browser->>Proxy: GET /apps/unknown/
    Proxy->>Reg: Lookup unknown
    Reg-->>Proxy: not found
    Proxy-->>Browser: 404 App Not Found (HTML error page)
```

```mermaid
flowchart TD
    Request([Incoming request<br/>/apps/app_name/path]) --> Redirect{Bare /apps/app_name<br/>no trailing slash?}
    Redirect -- Yes --> HTTP307[307 Redirect to /apps/app_name/]

    Redirect -- No --> LookupApp[Lookup app in registry]
    LookupApp --> Exists{App found?}
    Exists -- No --> E404[404 Not Found page]

    Exists -- Yes --> HasWebUI{has_web_ui = true?}
    HasWebUI -- No --> E404NoUI[404 No Web UI page]

    HasWebUI -- Yes --> IsRunning{status = running?}
    IsRunning -- No --> E503[503 App Unavailable page]

    IsRunning -- Yes --> IsWS{WebSocket upgrade?}
    IsWS -- Yes --> WSProxy[aiohttp bidirectional relay<br/>to ws://localhost:PORT/path]
    IsWS -- No --> HTTPProxy[httpx.AsyncClient request<br/>to http://localhost:PORT/path]

    HTTPProxy --> ConnectOk{Connect OK?}
    ConnectOk -- ConnectError --> E503Connect[503 Cannot connect page]
    ConnectOk -- Timeout --> E504[504 Gateway Timeout page]
    ConnectOk -- Other error --> E502[502 Bad Gateway page]
    ConnectOk -- Success --> ForwardResp[Forward status + headers + body]
```
