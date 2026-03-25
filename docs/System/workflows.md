# HomeHelper Workflows

This document covers the main process flows and interaction patterns in HomeHelper. For component architecture and lifecycle sequence diagrams, see [architecture.md](architecture.md).

## 1. Application Startup

What happens when the HomeHelper main application starts (the `lifespan` function in `main.py`).

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
    Loop -- No --> StartSub[Start Redis Event Subscriber<br/>psubscribe homehelper:events:*]
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

    NextDir -- Found --> HasManifest{homehelper.json<br/>exists?}
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
    participant API as HomeHelper API
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

## 5. Redis Event Pub/Sub Flow

How apps publish events through Redis and how the HomeHelper event subscriber captures them for the dashboard activity feed.

```mermaid
sequenceDiagram
    participant AppA as App A<br/>(Publisher)
    participant Redis as Redis<br/>(Message Bus)
    participant Sub as HomeHelper<br/>Event Subscriber
    participant Store as Redis List<br/>homehelper:events:recent
    participant AppB as App B<br/>(Subscriber)
    participant Dash as Dashboard API

    Note over Sub: Background thread<br/>psubscribe homehelper:events:*

    AppA->>Redis: PUBLISH homehelper:events:motion.detected<br/>{source, event_type, timestamp, data}

    par Fan-out to all subscribers
        Redis->>Sub: Deliver message to HomeHelper subscriber
        Redis->>AppB: Deliver message to App B subscriber
    end

    Sub->>Sub: Parse JSON event
    Sub->>Store: RPUSH event to recent events list
    Sub->>Store: LTRIM to max_events (default 100)

    AppB->>AppB: Handle event in<br/>subscriber callback

    Note over Dash,Store: Later, when user refreshes dashboard

    Dash->>Store: LRANGE homehelper:events:recent
    Store-->>Dash: Recent events list
    Dash->>Dash: Format timestamps,<br/>extract messages
```
