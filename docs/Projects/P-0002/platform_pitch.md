# Unified Mini-App Platform — Architecture Pitch

> **Name:** TBD — candidates: Latarnia · Razem · Rdzeń
> **Status:** Pre-spec review
> **Evolved from:** Latarnia v1

---

## The Problem

Latarnia works. Apps run, services are monitored, the dashboard is live. But the interaction model has a ceiling.

Every capability is a REST call or a dashboard click. There's no way to interact conversationally, no way to coordinate across apps, and the app contract doesn't support the richer workflows we want to build — a CRM that gets populated by a scraper, a knowledge base that serves as memory for everything, an agent that can reason across all of it.

More fundamentally: the existing model has no concept of *what an app can do*. It knows apps are running. It doesn't know what they expose.

The goal is to evolve Latarnia into a **general-purpose mini-app platform** where:
- Apps declare typed, callable surfaces (MCP tools)
- Apps communicate asynchronously through a managed bus (Redis Streams)
- The platform manages lifecycle, routing, and discovery — not reasoning

---

## What Stays

Everything that works stays unchanged:

- FastAPI core, systemd process management
- App discovery via `latarnia.json` manifest
- Health monitoring and REST endpoints (monitoring surface only)
- Streamlit app pattern for on-demand UIs
- Redis (gains Streams, loses ad-hoc pub/sub for app→app)
- Deployment-agnostic (RPi, VPS, local machine — platform doesn't care)

---

## Core Idea

The platform becomes an **MCP server that manages apps**.

Any MCP-compatible client connects to the platform's registry and gets the full tool surface of all installed apps. The platform builds neither an agent nor a chat UI. It builds the registry and the apps.

```
MCP Client ──► MCP Registry (HTTPS + OAuth 2.1) ──► App Tools
```

---

## Centralized Database

One pre-existing Postgres instance. The platform has superuser access and manages all provisioning. Each app gets its own isolated database, created automatically on first discovery and migrated automatically on version bump. Backups are out of scope for v1.

### How It Works

```
First discovery:
  Platform detects new app → creates database + dedicated Postgres role
  → runs all migration files in order → stores connection string in registry
  → passes --db-url to app at launch

Version bump detected (manifest version changed):
  Platform diffs applied migrations vs. available → runs pending in order
  → updates schema_versions table → updates registry

App runtime:
  App receives --db-url as launch parameter
  Postgres role has CONNECT privilege on its own DB only
  Cannot access other app databases — enforced by Postgres, not convention
```

### Migrations

Migrations are **mandatory** for any app that uses a database. No migration files = no database provisioned. Enforced at install time.

Apps ship ordered, numbered migration files:

```
migrations/
  001_initial.sql
  002_add_tags.sql
  003_add_embeddings.sql
```

The platform tracks applied migrations in a `schema_versions` table inside each app's database. On every version bump, the platform runs pending migrations before restarting the app. The platform runs forward only — rollback is the app author's responsibility.

### Isolation Model

| Level | Mechanism |
|---|---|
| App → App | Separate Postgres databases |
| Access control | Per-app Postgres role, restricted to own DB |
| Platform access | Superuser manages provisioning only, not app data |

---

## Agent Memory

The platform core maintains a lightweight memory store — a simple key-value table in the platform's own database. Any MCP client can read and write cross-session context here via dedicated platform-level MCP tools (`platform.getMemory()`, `platform.setMemory()`). No vectors, no graph, no provenance. Just persistent context owned by the platform.

---

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                         PLATFORM                                 │
│                                                                  │
│  ┌─────────────────────────────────────────────────────────┐    │
│  │  MCP Registry                                           │    │
│  │  Discovers + registers app MCP servers at startup       │    │
│  │  Namespaced tools: app_name.tool_name                   │    │
│  └────────────────────────┬────────────────────────────────┘    │
│                           │                                      │
│  ┌────────────────────────▼────────────────────────────────┐    │
│  │  Platform Core (Latarnia evolved)                     │    │
│  │  App Manager · Service Manager · Web Proxy · Dashboard  │    │
│  └──────────┬──────────────────────────────────────────────┘    │
│             │                                                    │
│  ┌──────────▼──────────────────────────────────────────────┐    │
│  │  Redis                                                  │    │
│  │  Events (existing) · Streams (inter-app comms)          │    │
│  └──────────┬──────────────────────────────────────────────┘    │
│             │                                                    │
│  ┌──────────▼──────────────────────────────────────────────┐    │
│  │  Postgres (pre-existing instance)                       │    │
│  │  Platform DB · Per-app isolated databases               │    │
│  └──────────┬──────────────────────────────────────────────┘    │
│             │                                                    │
│  ┌──────────┴────────────────────────────────────────────┐      │
│  ▼                    ▼                    ▼             ▼      │
│ ┌──────────┐   ┌──────────────┐   ┌─────────────────────────┐  │
│ │ App      │   │ App          │   │ Agent-App               │  │
│ │ REST+MCP │   │ REST only    │   │ LLM inside (Claude API) │  │
│ │ Web UI   │   │ (monitoring) │   │ Posts to Redis Streams  │  │
│ │ optional │   │              │   │ Own MCP surface         │  │
│ └──────────┘   └──────────────┘   └─────────────────────────┘  │
└─────────────────────────────────────────────────────────────────┘
```

---

## App Types

Two types. One contract.

### Streamlit Apps
Unchanged from Latarnia. On-demand UI, single instance, TTL-managed. Launched when user opens UI, killed after timeout.

### Service / Web Apps
Long-running process. UI is optional, not a type distinction.

Each app can expose:
- **REST endpoints** — required for health monitoring (`/health`). The dashboard reads these.
- **MCP server** — optional, declared in manifest. MCP clients call these.
- **Web UI** — optional. App owns its own HTTP server on its assigned port. Platform reverse-proxies it under `/apps/{name}/`.

An app with all three is a first-class platform citizen. An app with only REST still works — it's just not reachable via MCP.

---

## The App Contract — Evolved

`latarnia.json` gains the following optional fields:

```json
{
  "name": "CRM",
  "version": "1.2.0",
  "type": "service",
  "config": {
    "has_web_ui": true,
    "database": true,
    "mcp_server": true,
    "mcp_port": 9001,
    "redis_streams_publish": ["crm.contacts.created", "crm.contacts.updated"],
    "redis_streams_subscribe": ["scraper.leads.new"]
  },
  "requires": [
    { "app": "knowledge_base", "min_version": "1.2.0" }
  ]
}
```

**`database`**: platform provisions an isolated Postgres database and injects `--db-url` at launch.

**`mcp_server`**: platform registers this app's MCP tools in the registry at startup under the `app_name.*` namespace.

**`redis_streams_publish/subscribe`**: declares the app's async communication contract. Platform validates no stream name collisions at registration time.

**`requires`**: declares dependencies on other installed apps. Platform refuses to install an app whose dependencies are not satisfied. Each dependency specifies a minimum version floor.

REST endpoints and the `/health` contract are unchanged.

### App Versioning and Compatibility Contract

All versions under the same app name must be **backwards compatible**. Version numbers are a minimum floor — `knowledge_base >= 1.2.0` is satisfied by any installed version at or above 1.2.0.

Breaking changes — removing or changing the signature of an existing MCP tool or Redis Stream schema — require a new app name. Adding new tools or streams is never breaking.

```
knowledge_base 1.0.0 → 1.2.0 → 2.0.0   (same name, always backwards compatible)
knowledge_base2 1.0.0                    (new name = breaking change from prior lineage)
```

---

## Communication Model

Two distinct paths. Never mixed.

### Synchronous — Client → App
An MCP client calls a tool. App responds. This path is for interactive use where something is waiting for a response.

```
MCP Client ──► MCP Registry ──► app_name.tool_name ──► Response
```

### Asynchronous — App → App
An app needs to inform or trigger another app. It posts to a Redis Stream. The receiving app reads, processes, and ACKs. No message is lost. No tight coupling.

Redis Streams provide:
- **Consumer groups** — the receiving app owns its messages
- **XACK** — explicit acknowledgment on successful processing
- **Automatic re-delivery** — unACKed messages redelivered if consumer crashes
- **Audit trail** — the stream is a persistent log, not a transient channel

```
App A ──► Redis Stream ──► App B ──► XACK
```

---

## Agent-Apps

A pattern, not a new type.

An **agent-app** is a Service app whose internal implementation uses an LLM (Claude API) and communicates with other apps via Redis Streams. From the platform's perspective it is indistinguishable from any other service app — manifest, lifecycle, MCP surface, health endpoint.

The platform provides the bus. The agent-app provides the reasoning. No new platform primitives required.

---

## v1 Scope

### IN
- Evolved app contract (`database`, `mcp_server`, `redis_streams_*`, `requires` in manifest)
- App versioning and backwards compatibility contract
- App dependency resolution at install time
- MCP registry with namespaced tool discovery
- Centralized Postgres (pre-existing instance), per-app isolated databases, mandatory migrations
- Redis Streams as the inter-app communication bus
- Web UI proxy (app owns server, platform proxies under `/apps/{name}/`)
- Lightweight platform memory store (`platform.getMemory()`, `platform.setMemory()`)
- Agent-app pattern supported structurally

### OUT
- Built-in agent or chat UI
- App Builder pipeline
- Approval flows for destructive operations
- Multi-user / per-user app isolation
- Database backups
- REST Bridge for legacy Latarnia apps (adapted directly)
- External third-party MCP servers in platform registry (client configuration concern, not platform)

---

## Open Questions

1. **Platform name.** Latarnia · Razem · Rdzeń. Needs a decision before implementation touches file paths, service names, and the dashboard header.

2. **MCP namespace collision policy.** Confirm the `app_name.tool_name` convention is sufficient, or define a disambiguation rule for two apps exposing identically named tools.

3. **Redis Streams schema ownership.** Each app owns its own message schema, documented in its repo. Platform validates stream names only, not message contents. Confirm this is sufficient or define a schema registry.

4. **Migration failure policy.** If a migration fails mid-run, does the platform halt the app and alert, or attempt rollback? Needs an explicit policy before the first failure occurs in production.

---

## Why This Works

The blast radius of any LLM client is bounded by the MCP surface of installed apps. It cannot touch a database directly. It cannot invent operations. Schema evolution requires explicit migrations, not a chat message.

Every app is independently deployable, independently testable, and independently useful without any MCP client at all. The MCP layer multiplies their value. It doesn't replace the contracts they define.

The platform grows with every new app installed. Any MCP client connecting to the registry immediately gains the full tool surface of everything installed — past, present, and future.

That's Latarnia with a brain.
