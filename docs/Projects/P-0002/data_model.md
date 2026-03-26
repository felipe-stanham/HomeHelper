# P-0002: Latarnia Data Model

## Storage Strategy (Evolved)

Latarnia uses a hybrid storage approach:

- **Platform configuration**: JSON files (unchanged from HomeHelper)
- **Platform registry**: JSON persistence with in-memory operations (unchanged, extended with new fields)
- **Platform events**: Redis pub/sub (unchanged)
- **App→App communication**: Redis Streams (new)
- **App databases**: Postgres with per-app isolated databases (new)
- **Logs**: File-based logging with rotation (unchanged)

---

## Platform Registry — Extended Schema

The in-memory/JSON registry gains new fields per app. Existing fields are unchanged.

```mermaid
classDiagram
    class AppRegistry {
        +String app_id
        +String name
        +String type
        +String description
        +String version
        +String status
        +String path
        +Manifest manifest
        +RuntimeInfo runtime_info
        +DatabaseInfo database_info
        +MCPInfo mcp_info
        +StreamInfo stream_info
        +Dependency[] dependencies
        +DateTime discovered_at
        +DateTime last_updated
    }

    class Manifest {
        +String name
        +String type
        +String description
        +String version
        +String main_file
        +String requirements
        +ManifestConfig config
        +Endpoints endpoints
        +Object install
        +Dependency[] requires
    }

    class ManifestConfig {
        +Boolean has_UI
        +Boolean has_web_ui
        +Boolean redis_required
        +Boolean database
        +Boolean mcp_server
        +Integer mcp_port
        +Boolean logs_dir
        +Boolean data_dir
        +Boolean auto_start
        +String restart_policy
        +String[] redis_streams_publish
        +String[] redis_streams_subscribe
    }

    class RuntimeInfo {
        +Integer assigned_port
        +String process_id
        +String service_name
        +DateTime started_at
        +DateTime last_health_check
        +ResourceUsage resource_usage
    }

    class DatabaseInfo {
        +Boolean provisioned
        +String database_name
        +String role_name
        +String connection_url
        +String[] applied_migrations
        +DateTime last_migration_at
    }

    class MCPInfo {
        +Boolean enabled
        +Integer mcp_port
        +Boolean healthy
        +String[] registered_tools
        +DateTime last_tool_sync
    }

    class StreamInfo {
        +String[] publish_streams
        +String[] subscribe_streams
        +String[] consumer_groups
    }

    class Dependency {
        +String app
        +String min_version
        +Boolean satisfied
    }

    class Endpoints {
        +String health
        +String ui
        +String metrics
    }

    class ResourceUsage {
        +Float cpu_percent
        +Integer memory_mb
        +Integer disk_mb
    }

    AppRegistry --> Manifest
    AppRegistry --> RuntimeInfo
    AppRegistry --> DatabaseInfo
    AppRegistry --> MCPInfo
    AppRegistry --> StreamInfo
    AppRegistry --> "0..*" Dependency
    Manifest --> ManifestConfig
    Manifest --> Endpoints
    Manifest --> "0..*" Dependency
    RuntimeInfo --> ResourceUsage
```

---

## Postgres — Per-App Database Schema

Each app that declares `database: true` gets its own isolated Postgres database. The platform creates one table in every app database to track migrations.

### Schema Versions Table (created by platform in each app DB)

```mermaid
erDiagram
    SCHEMA_VERSIONS {
        integer id PK "auto-increment"
        string migration_file "e.g. 001_initial.sql"
        integer migration_number "extracted from filename"
        string checksum "SHA-256 of migration file contents"
        datetime applied_at "timestamp of execution"
        integer duration_ms "execution time"
    }
```

### Postgres Provisioning Model

```mermaid
erDiagram
    POSTGRES_INSTANCE {
        string host "from platform config"
        integer port "from platform config"
        string superuser "platform provisioning account"
    }

    APP_DATABASE {
        string database_name "latarnia_{app_name}"
        string role_name "latarnia_{app_name}_role"
        string role_password "auto-generated"
        datetime created_at
    }

    POSTGRES_INSTANCE ||--o{ APP_DATABASE : "hosts"
```

**Isolation guarantees:**
- Each app database has a dedicated Postgres role
- Role has CONNECT privilege only on its own database
- PUBLIC CONNECT is revoked on each app database
- Platform superuser is used for provisioning only, never passed to apps

---

## Redis — Streams Data Model (New)

### Stream Naming Convention

```
latarnia:streams:{declared_stream_name}
```

Example: An app declares `redis_streams_publish: ["crm.contacts.created"]` → the Redis stream key is `latarnia:streams:crm.contacts.created`.

### Consumer Group Naming Convention

```
Consumer group name = subscribing app's app_id
Consumer name = {app_id}-{instance_number}
```

Example: App `crm` subscribes to `scraper.leads.new` → consumer group `crm` on stream `latarnia:streams:scraper.leads.new`.

### Stream Message Format

Apps own their message schemas. The platform does NOT enforce message structure. However, the recommended convention is:

```json
{
    "source": "app_name",
    "timestamp": 1704067200,
    "version": "1.0",
    "data": {
        "...app-specific payload..."
    }
}
```

### Stream Ownership Model

```mermaid
erDiagram
    STREAM {
        string stream_key "latarnia:streams:{name}"
        string publisher_app "exactly one publisher"
        datetime created_at
    }

    CONSUMER_GROUP {
        string group_name "subscribing app_id"
        string stream_key FK
        datetime created_at
    }

    APP_STREAM_DECLARATION {
        string app_id FK
        string stream_name
        string direction "publish or subscribe"
    }

    STREAM ||--o{ CONSUMER_GROUP : "has subscribers"
    APP_STREAM_DECLARATION }o--|| STREAM : "references"
```

**Ownership rules:**
- Each stream has exactly ONE publisher app (enforced at registration time)
- Multiple apps can subscribe to the same stream
- Stream names are globally unique — collision = registration failure

---

## Redis — Existing Pub/Sub (Unchanged)

Platform events continue to use pub/sub. These channels are NOT migrated to Streams.

```
latarnia:events              # General system events (renamed from homehelper:events)
latarnia:events:*            # App-specific platform events
latarnia:health              # Health check events
latarnia:metrics             # System metrics
```

---

## Configuration — Extended Platform Config

The platform config file (`config.json`) gains new sections for Postgres and MCP.

```mermaid
classDiagram
    class PlatformConfig {
        +RedisConfig redis
        +PostgresConfig postgres
        +MCPConfig mcp
        +LoggingConfig logging
        +ProcessManagerConfig process_manager
        +SystemConfig system
    }

    class PostgresConfig {
        +String host
        +Integer port
        +String superuser
        +String superuser_password
        +String database_prefix "latarnia_"
        +String role_prefix "latarnia_"
    }

    class MCPConfig {
        +Boolean enabled
        +String transport "sse or streamable-http"
        +Integer gateway_port "default: 8000 (same as main)"
        +String gateway_path "/mcp"
        +Integer tool_sync_interval_seconds
    }

    class RedisConfig {
        +String host
        +Integer port
        +Integer db
    }

    class LoggingConfig {
        +String level
        +String format
    }

    class ProcessManagerConfig {
        +String data_dir
        +String logs_dir
        +Integer streamlit_port
        +Integer streamlit_ttl_seconds
        +PortRange port_range
        +PortRange mcp_port_range
    }

    class PortRange {
        +Integer start
        +Integer end
    }

    class SystemConfig {
        +Integer main_port
        +String host
    }

    PlatformConfig --> RedisConfig
    PlatformConfig --> PostgresConfig
    PlatformConfig --> MCPConfig
    PlatformConfig --> LoggingConfig
    PlatformConfig --> ProcessManagerConfig
    PlatformConfig --> SystemConfig
    ProcessManagerConfig --> "2" PortRange
```

---

## File System Layout (Evolved)

```
/opt/latarnia/                          # Renamed from /opt/homehelper/
├── config/
│   └── config.json                     # Extended with postgres + mcp sections
├── src/latarnia/                        # Application code (renamed)
├── apps/                                # Discovered applications
│   └── crm/
│       ├── latarnia.json               # Manifest (or homehelper.json with deprecation)
│       ├── requirements.txt
│       ├── app.py                       # Main entry point
│       ├── mcp_server.py               # MCP server (if mcp_server: true)
│       └── migrations/                  # SQL migrations (if database: true)
│           ├── 001_initial.sql
│           └── 002_add_tags.sql
├── data/                                # Per-app data directories (unchanged)
├── logs/                                # Per-app log directories (unchanged)
└── registry/
    └── apps.json                       # Extended registry with DB/MCP/Stream info
```

---

## App Launch Parameters (Evolved)

Service apps receive these command-line arguments at launch:

| Parameter | Condition | Example |
|-----------|-----------|---------|
| `--port` | Always | `--port 8101` |
| `--redis-url` | `redis_required: true` | `--redis-url redis://localhost:6379` |
| `--data-dir` | `data_dir: true` | `--data-dir /opt/latarnia/data` |
| `--logs-dir` | `logs_dir: true` | `--logs-dir /opt/latarnia/logs` |
| `--db-url` | `database: true` | `--db-url postgresql://latarnia_crm_role:pass@localhost/latarnia_crm` |

The `--db-url` parameter is new. Apps that don't declare `database: true` never receive it.
