# P-0002: Latarnia Workflows

This document covers the process flows and interaction patterns introduced or modified by P-0002. For existing Latarnia workflows that remain unchanged, see `System/workflows.md`.

---

## 1. Evolved App Discovery [cap-002, cap-003, cap-004, cap-007, cap-009]

The discovery flow gains database provisioning, migration execution, stream setup, and dependency checking. Existing apps (no new manifest fields) follow the unchanged path.

```mermaid
flowchart TD
    Trigger([Discover Apps]) --> Scan[Scan apps/ directory]
    Scan --> NextDir{Next directory?}

    NextDir -- None left --> Persist[Persist registry to disk]
    Persist --> Done([Return discovered count])

    NextDir -- Found --> HasManifest{"latarnia.json or
    latarnia.json?"}
    HasManifest -- No --> SkipDir[Skip, log warning]
    SkipDir --> NextDir

    HasManifest -- latarnia.json --> DeprecWarn[Log deprecation warning]
    DeprecWarn --> Parse[Parse manifest]
    HasManifest -- latarnia.json --> Parse

    Parse --> Valid{Manifest valid?}
    Valid -- No --> LogError[Log validation error]
    LogError --> NextDir

    Valid -- Yes --> AlreadyReg{Already registered?}
    AlreadyReg -- Yes, same version --> NextDir
    AlreadyReg -- Yes, version changed --> VersionBump([Go to Version Bump flow])

    AlreadyReg -- No --> CheckDeps{"Has requires[]?"}
    CheckDeps -- Yes --> ValidateDeps["Check each dependency:
    installed + version >= min"]
    ValidateDeps --> DepsOk{All satisfied?}
    DepsOk -- No --> LogDepErr["Log missing dependency error.
    Skip app"]
    LogDepErr --> NextDir

    CheckDeps -- No --> AllocPort
    DepsOk -- Yes --> AllocPort["Allocate REST port
    from 8100-8199"]

    AllocPort --> HasDB{"database: true?"}
    HasDB -- Yes --> ProvisionDB([Go to DB Provisioning flow])
    HasDB -- No --> HasMCP

    ProvisionDB --> DBOk{"DB provisioned
    + migrations OK?"}
    DBOk -- No --> LogDBErr[Log error, skip app]
    LogDBErr --> NextDir
    DBOk -- Yes --> HasMCP

    HasMCP{"mcp_server: true?"} -- Yes --> AllocMCPPort["Record MCP port
    from manifest"]
    HasMCP -- No --> HasStreams

    AllocMCPPort --> HasStreams{"Has redis_streams_*?"}
    HasStreams -- Yes --> SetupStreams([Go to Stream Setup flow])
    HasStreams -- No --> InstallDeps

    SetupStreams --> StreamsOk{Streams OK?}
    StreamsOk -- No --> LogStreamErr["Log collision error.
    Skip app"]
    LogStreamErr --> NextDir
    StreamsOk -- Yes --> InstallDeps

    InstallDeps[Install requirements.txt] --> RunSetup[Run setup_commands]
    RunSetup --> Register["Register in registry
    with all metadata"]
    Register --> PublishEvent["Publish app_discovered
    via Redis pub/sub"]
    PublishEvent --> NextDir
```

---

## 2. Database Provisioning [cap-003, cap-004]

Triggered during app discovery when `database: true` is declared.

```mermaid
flowchart TD
    Start(["DB Provisioning for app_name"]) --> GenCreds["Generate role password
    securely"]
    GenCreds --> CreateRole["CREATE ROLE latarnia_app_role
    WITH LOGIN PASSWORD '...'"]
    CreateRole --> CreateDB["CREATE DATABASE latarnia_app
    OWNER latarnia_app_role"]
    CreateDB --> RevokePublic["REVOKE CONNECT ON DATABASE
    latarnia_app FROM PUBLIC"]
    RevokePublic --> GrantRole["GRANT CONNECT ON DATABASE
    latarnia_app TO latarnia_app_role"]
    GrantRole --> CreateVersionsTable["Connect to app DB
    CREATE TABLE schema_versions"]

    CreateVersionsTable --> CheckMigrations{"migrations/
    directory exists?"}
    CheckMigrations -- No --> BuildURL["Build connection URL
    Store in registry"]
    CheckMigrations -- Yes --> ListFiles["List migration files
    sorted numerically"]
    ListFiles --> BeginTx[BEGIN TRANSACTION]
    BeginTx --> NextMig{"Next migration
    file?"}

    NextMig -- None left --> CommitTx[COMMIT]
    CommitTx --> BuildURL

    NextMig -- Found --> ExecMig[Execute SQL file]
    ExecMig --> MigOk{Succeeded?}
    MigOk -- Yes --> RecordMig["INSERT INTO schema_versions
    file, checksum, timestamp"]
    RecordMig --> NextMig
    MigOk -- No --> RollbackTx[ROLLBACK]
    RollbackTx --> DropDB["DROP DATABASE + ROLE
    Clean up"]
    DropDB --> Fail(["Return failure
    with error details"])

    BuildURL --> Done(["Return success
    with db_url"])
```

---

## 3. Version Bump Handling [cap-004, cap-011]

Triggered when a registered app's manifest version has changed.

```mermaid
flowchart TD
    Start(["Version bump detected: old_ver to new_ver"]) --> ReadNewManifest[Read updated manifest]
    ReadNewManifest --> HasMCP{"App has
    mcp_server: true?"}

    HasMCP -- Yes --> CheckToolCompat["Compare registered MCP tools
    with new version's tools"]
    CheckToolCompat --> ToolsOk{"All prior tools
    still present?"}
    ToolsOk -- No --> RejectBump["Reject version bump.
    Log backward-compat error.
    Keep old version running"]
    RejectBump --> Done([Return failure])

    ToolsOk -- Yes --> CheckDB
    HasMCP -- No --> CheckDB

    CheckDB{"App has
    database: true?"} -- No --> UpdateRegistry
    CheckDB -- Yes --> GetApplied["Query schema_versions
    in app DB"]
    GetApplied --> ListNewMigs["List migration files
    in updated app"]
    ListNewMigs --> DiffMigs["Find pending migrations
    not in schema_versions"]
    DiffMigs --> HasPending{Pending migrations?}

    HasPending -- No --> UpdateRegistry
    HasPending -- Yes --> StopApp[Stop running app]
    StopApp --> BeginTx[BEGIN TRANSACTION]
    BeginTx --> RunPending["Execute pending migrations
    in order"]
    RunPending --> MigsOk{All succeeded?}
    MigsOk -- No --> Rollback[ROLLBACK transaction]
    Rollback --> LogErr["Log migration failure.
    App stays stopped"]
    LogErr --> Done

    MigsOk -- Yes --> Commit[COMMIT]
    Commit --> UpdateRegistry

    UpdateRegistry["Update registry:
    version, tools, streams"] --> RestartApp["Restart app with
    updated config"]
    RestartApp --> SyncMCP{MCP enabled?}
    SyncMCP -- Yes --> RefreshTools["Refresh MCP tool listing
    in gateway"]
    SyncMCP -- No --> Done2([Return success])
    RefreshTools --> Done2
```

---

## 4. Redis Stream Setup [cap-007]

Triggered during app discovery when `redis_streams_publish` or `redis_streams_subscribe` is declared.

```mermaid
flowchart TD
    Start(["Stream Setup for app_name"]) --> CheckPublish{"Has
    publish streams?"}

    CheckPublish -- Yes --> NextPub{"Next publish
    stream name?"}
    CheckPublish -- No --> CheckSubscribe

    NextPub -- None left --> CheckSubscribe
    NextPub -- Found --> CheckCollision{"Stream already
    has a publisher?"}
    CheckCollision -- Yes, different app --> Fail([Return collision error])
    CheckCollision -- No --> CreateStream["XGROUP CREATE
    latarnia:streams:name
    MKSTREAM"]
    CreateStream --> RecordPublisher["Record app as publisher
    in registry"]
    RecordPublisher --> NextPub

    CheckSubscribe{"Has
    subscribe streams?"} -- No --> Done([Return success])
    CheckSubscribe -- Yes --> NextSub{"Next subscribe
    stream name?"}
    NextSub -- None left --> Done
    NextSub -- Found --> StreamExists{Stream exists?}
    StreamExists -- No --> CreateStreamSub["Create stream
    MKSTREAM"]
    CreateStreamSub --> CreateGroup
    StreamExists -- Yes --> CreateGroup["XGROUP CREATE
    group=app_name
    if not exists"]
    CreateGroup --> RecordSub["Record consumer group
    in registry"]
    RecordSub --> NextSub
```

---

## 5. MCP Gateway — Tool Discovery and Routing [cap-005, cap-006]

How the MCP gateway aggregates tools from all apps and routes client requests.

```mermaid
sequenceDiagram
    participant Client as MCP Client
    participant GW as MCP Gateway :8000/mcp
    participant Reg as App Registry
    participant App1 as CRM App (MCP :9001)
    participant App2 as KB App (MCP :9002)

    Note over GW: Startup - build tool index

    GW->>Reg: Get all MCP-enabled apps
    Reg-->>GW: crm (port 9001), kb (port 9002)

    GW->>App1: MCP list_tools
    App1-->>GW: add_contact, search_contacts, delete_contact
    GW->>App2: MCP list_tools
    App2-->>GW: query, add_document

    GW->>GW: Build namespaced index

    Note over Client,App2: Runtime - client connects

    Client->>GW: Initialize / list_tools
    GW-->>Client: crm.add_contact, crm.search_contacts, kb.query, etc.

    Client->>GW: Call crm.search_contacts(query=Alice)
    GW->>Reg: Is crm healthy?
    Reg-->>GW: Yes
    GW->>App1: Call search_contacts(query=Alice)
    App1-->>GW: id=1, name=Alice Smith
    GW-->>Client: id=1, name=Alice Smith

    Note over Client,App2: Unhealthy app scenario

    Client->>GW: Call kb.query(q=test)
    GW->>Reg: Is kb healthy?
    Reg-->>GW: No (health check failed)
    GW-->>Client: Error - App kb is currently unavailable
```

---

## 6. MCP Tool Sync on App Lifecycle Events [cap-005, cap-006]

How the gateway stays in sync when apps start, stop, or update.

```mermaid
flowchart TD
    Event([App lifecycle event]) --> Type{Event type?}

    Type -- App started --> WaitHealth[Wait for health check pass]
    WaitHealth --> HasMCP{"App has
    mcp_server: true?"}
    HasMCP -- No --> Done([No MCP action])
    HasMCP -- Yes --> ProbeMCP["HTTP probe app's MCP port"]
    ProbeMCP --> MCPUp{"MCP server
    responding?"}
    MCPUp -- No --> RetryLater["Schedule retry
    up to 3 attempts"]
    RetryLater --> MCPUp
    MCPUp -- Yes --> FetchTools[list_tools from app MCP]
    FetchTools --> UpdateIndex["Update gateway tool index
    with namespaced tools"]
    UpdateIndex --> StoreTools["Store tool list
    in registry MCPInfo"]
    StoreTools --> Done

    Type -- App stopped --> RemoveTools["Remove app's tools
    from gateway index"]
    RemoveTools --> Done

    Type -- App version bump --> CheckCompat["Verify backward compatibility
    see Version Bump flow"]
    CheckCompat --> FetchTools
```

---

## 7. Web UI Reverse Proxy Request Flow [cap-008]

How the platform proxies requests to app-owned web UIs.

```mermaid
sequenceDiagram
    participant Browser as User Browser
    participant Platform as Platform :8000
    participant Reg as App Registry
    participant App as CRM App :8101

    Browser->>Platform: GET /apps/crm/dashboard
    Platform->>Reg: Lookup app crm
    Reg-->>Platform: port=8101, has_web_ui=true, running

    Platform->>App: GET /dashboard + X-Forwarded headers
    App-->>Platform: 200 OK (HTML)
    Platform-->>Browser: 200 OK (HTML)

    Browser->>Platform: GET /apps/crm/static/style.css
    Platform->>App: GET /static/style.css
    App-->>Platform: 200 OK (CSS)
    Platform-->>Browser: 200 OK (CSS)

    Note over Browser,App: WebSocket upgrade

    Browser->>Platform: GET /apps/crm/ws (Upgrade websocket)
    Platform->>App: GET /ws (Upgrade websocket)
    App-->>Platform: 101 Switching Protocols
    Platform-->>Browser: 101 Switching Protocols
    Browser->>App: WebSocket frames proxied

    Note over Browser,App: App not running

    Browser->>Platform: GET /apps/offline_app/
    Platform->>Reg: Lookup offline_app
    Reg-->>Platform: status=stopped
    Platform-->>Browser: 503 Service Unavailable
```

---

## 8. App Launch Sequence (Evolved) [cap-003, cap-005]

How the Service Manager starts an app with the new parameters.

```mermaid
flowchart TD
    Start([Start app request]) --> GetReg[Load app from registry]
    GetReg --> BuildCmd["Build launch command:
    python app.py --port PORT"]

    BuildCmd --> AddRedis{redis_required?}
    AddRedis -- Yes --> AppendRedis[Append --redis-url]
    AddRedis -- No --> AddData

    AppendRedis --> AddData{data_dir?}
    AddData -- Yes --> AppendData[Append --data-dir]
    AddData -- No --> AddLogs

    AppendData --> AddLogs{logs_dir?}
    AddLogs -- Yes --> AppendLogs[Append --logs-dir]
    AddLogs -- No --> AddDB

    AppendLogs --> AddDB{"database: true?"}
    AddDB -- Yes --> AppendDB["Append --db-url
    from registry.database_info"]
    AddDB -- No --> GenService

    AppendDB --> GenService[Generate systemd service file]
    GenService --> StartService["systemctl start latarnia-app_name"]
    StartService --> WaitHealth[Poll /health endpoint]
    WaitHealth --> Healthy{"Health check
    passes?"}
    Healthy -- No, retries left --> WaitHealth
    Healthy -- No, max retries --> MarkError[Mark app as ERROR]
    MarkError --> Done([Return error])

    Healthy -- Yes --> HasMCP{"mcp_server: true?"}
    HasMCP -- Yes --> ProbeMCP[Probe MCP port]
    ProbeMCP --> MCPOk{MCP responding?}
    MCPOk -- Yes --> SyncTools[Sync tools to gateway]
    MCPOk -- No --> LogMCPWarn["Log MCP warning.
    App runs without MCP"]
    HasMCP -- No --> MarkRunning
    SyncTools --> MarkRunning
    LogMCPWarn --> MarkRunning

    MarkRunning[Mark app as RUNNING] --> Done2([Return success])
```

---

## 9. Platform Startup (Evolved) [cap-001, cap-006]

How the Latarnia platform starts up, including new MCP gateway initialization.

```mermaid
flowchart TD
    Start([Latarnia Startup]) --> CreateDirs[Ensure data/ logs/ directories]
    CreateDirs --> LoadConfig[Load config.json]
    LoadConfig --> SetupLog[Setup logging]

    SetupLog --> CheckRedis{Redis running?}
    CheckRedis -- No --> StartRedis[Attempt to start Redis]
    StartRedis --> RedisOk{Started?}
    RedisOk -- No --> LogWarn[Log warning, continue]
    RedisOk -- Yes --> CheckPG
    CheckRedis -- Yes --> CheckPG

    LogWarn --> CheckPG{Postgres reachable?}
    CheckPG -- No --> LogPGWarn["Log Postgres unavailable.
    DB apps will fail to start"]
    CheckPG -- Yes --> Discover
    LogPGWarn --> Discover

    Discover["Run app discovery
    with evolved flow"] --> AutoStart["Start auto_start apps
    with new launch params"]
    AutoStart --> InitGateway{"MCP enabled
    in config?"}
    InitGateway -- Yes --> StartGW["Initialize MCP gateway.
    Build tool index from
    running MCP apps"]
    InitGateway -- No --> StartSub
    StartGW --> StartSub[Start Redis event subscriber]
    StartSub --> Ready([Platform Ready])
```
