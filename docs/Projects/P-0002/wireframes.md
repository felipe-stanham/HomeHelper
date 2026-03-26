# P-0002: Latarnia Wireframes

The dashboard layout remains fundamentally unchanged from HomeHelper. The key change is that app tiles gain new capability indicators and action links. No new pages are added.

---

## Screen: Dashboard (Evolved) [cap-010]

The overall layout is identical to HomeHelper. Only the app tile content changes.

```
+------------------------------------------------------------------+
| HEADER: Latarnia | System Status | Refresh                       |
+------------------------------------------------------------------+
| SYSTEM METRICS BAR                                                |
| CPU: ██░░ 45%  |  RAM: ████░ 62%  |  Disk: ██░░ 38%  |  42°C   |
+------------------------------------------------------------------+
|                                                                    |
|  APP GRID (2-3 columns, responsive)                               |
|                                                                    |
|  +---------------------------+  +---------------------------+     |
|  | [App Tile - Full]         |  | [App Tile - Minimal]      |     |
|  | (see detail below)        |  | (see detail below)        |     |
|  +---------------------------+  +---------------------------+     |
|                                                                    |
|  +---------------------------+  +---------------------------+     |
|  | [App Tile - Agent]        |  | [App Tile - Streamlit]    |     |
|  |                           |  |                           |     |
|  +---------------------------+  +---------------------------+     |
|                                                                    |
+------------------------------------------------------------------+
| RECENT ACTIVITY                                                    |
| • 10:30 crm: contact created (MCP)                               |
| • 10:28 scraper: new lead published (Stream)                      |
| • 10:25 kb: health check OK                                      |
+------------------------------------------------------------------+
```

---

## Component: App Tile — Full-Featured App [cap-010]

An app with REST, MCP, Database, Web UI, and Streams.

```
+-------------------------------------------+
| ● CRM                           v1.2.0    |
| Customer relationship manager              |
+-------------------------------------------+
| Status: ✅ Running        Port: 8101      |
+-------------------------------------------+
| CAPABILITIES                               |
| 🔧 MCP: 5 tools     📊 DB: Migrated (3)  |
| 📡 Streams: 2 pub / 1 sub                 |
+-------------------------------------------+
| HEALTH                                     |
| "All systems operational"                  |
| Response: 12ms | CPU: 3% | RAM: 45MB     |
+-------------------------------------------+
| ACTIONS                                    |
| [Monitor]  [Web UI]  [Start/Stop]  [Logs] |
+-------------------------------------------+
```

- **Monitor** opens the existing REST-in-modal view (unchanged)
- **Web UI** links to `/apps/crm/` (new, only shown if `has_web_ui: true`)
- **Start/Stop** controls the systemd service (unchanged)
- **Logs** opens the log viewer (unchanged)

---

## Component: App Tile — Minimal/Legacy App [cap-010]

An existing HomeHelper app with no new capabilities. Identical to current behavior.

```
+-------------------------------------------+
| ● Temperature Monitor            v1.0.0   |
| Monitors temperature sensors               |
+-------------------------------------------+
| Status: ✅ Running        Port: 8104      |
+-------------------------------------------+
| CAPABILITIES                               |
| (No MCP · No DB · No Streams)             |
+-------------------------------------------+
| HEALTH                                     |
| "3 sensors active"                         |
| Response: 8ms | CPU: 1% | RAM: 22MB      |
+-------------------------------------------+
| ACTIONS                                    |
| [Monitor]  [Start/Stop]  [Logs]           |
+-------------------------------------------+
```

No Web UI button. No MCP/DB/Stream indicators. Fully backward compatible display.

---

## Component: App Tile — Agent App [cap-010]

An agent-app (LLM-powered) with MCP and Streams but no Web UI.

```
+-------------------------------------------+
| ● Lead Qualifier                 v1.0.0   |
| AI-powered lead scoring agent              |
+-------------------------------------------+
| Status: ✅ Running        Port: 8103      |
+-------------------------------------------+
| CAPABILITIES                               |
| 🔧 MCP: 3 tools     📊 DB: Migrated (2)  |
| 📡 Streams: 0 pub / 2 sub                 |
+-------------------------------------------+
| HEALTH                                     |
| "Processing queue: 4 pending"             |
| Response: 15ms | CPU: 8% | RAM: 120MB    |
+-------------------------------------------+
| ACTIONS                                    |
| [Monitor]  [Start/Stop]  [Logs]           |
+-------------------------------------------+
```

---

## Component: App Tile — Streamlit App [cap-010]

Streamlit apps are unchanged. They don't support MCP, DB, or Streams in this version.

```
+-------------------------------------------+
| ○ Config Editor                  v1.0.0   |
| System configuration interface             |
+-------------------------------------------+
| Status: ⏹ Stopped (on-demand)            |
+-------------------------------------------+
| CAPABILITIES                               |
| (Streamlit app · On-demand UI)             |
+-------------------------------------------+
| ACTIONS                                    |
| [Launch]                                   |
+-------------------------------------------+
```

---

## Component: App Tile — Error States [cap-010]

### App with failed migration

```
+-------------------------------------------+
| ● Inventory                      v1.1.0   |
| Inventory tracking system                  |
+-------------------------------------------+
| Status: ❌ Migration Failed   Port: 8105  |
+-------------------------------------------+
| ERROR                                      |
| Migration 003_add_indexes.sql failed:     |
| "relation 'products' does not exist"      |
+-------------------------------------------+
| ACTIONS                                    |
| [View Error]  [Logs]                      |
+-------------------------------------------+
```

### App with unmet dependency

```
+-------------------------------------------+
| ● CRM Advanced                   v1.0.0   |
| Extended CRM with AI features             |
+-------------------------------------------+
| Status: ⚠️ Dependency Unmet              |
+-------------------------------------------+
| MISSING                                    |
| Requires: knowledge_base >= 1.2.0         |
| Installed: (not found)                     |
+-------------------------------------------+
| ACTIONS                                    |
| [View Details]                             |
+-------------------------------------------+
```

---

## Interaction Notes

- **Capability badges** (MCP, DB, Streams) are read-only indicators. Clicking them does nothing in v1.
- **Web UI button** opens `/apps/{name}/` in a new browser tab (not in a modal — the app owns the full page).
- **Monitor button** opens the existing modal with REST API resource tabs (unchanged behavior).
- The **tile layout and grid behavior** is unchanged from HomeHelper. Only the content within tiles is extended.
- All new indicators degrade gracefully: if an app has no new capabilities, the tile looks exactly like a HomeHelper tile.
