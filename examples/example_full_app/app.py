"""
Example Full App — Demonstrates all Latarnia P-0002 capabilities.

This app exercises:
- Database (Postgres via --db-url)
- MCP server (tools on --mcp-port)
- Web UI (HTML served on the REST port)
- Redis Streams (publish and subscribe)
- REST API with /health endpoint
- Dependency on example_companion (via requires)

Usage:
    python app.py --port 8101 --mcp-port 9001 \
        --db-url postgresql://... --redis-url redis://localhost:6379/0
"""

import argparse
import asyncio
import json
import logging
import threading
from datetime import datetime

import redis
import uvicorn
from fastapi import FastAPI
from fastapi.responses import HTMLResponse
from mcp.server import Server
from mcp.server.sse import SseServerTransport
from starlette.applications import Starlette
from starlette.routing import Route, Mount

logger = logging.getLogger("example_full_app")
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")

# ---------------------------------------------------------------------------
# REST API
# ---------------------------------------------------------------------------

rest_app = FastAPI(title="Example Full App")


@rest_app.get("/health")
async def health():
    return {
        "health": "good",
        "message": "Example full app is running",
        "extra_info": {
            "mcp_tools": 3,
            "db_connected": db_url is not None,
            "streams_active": redis_url is not None,
            "last_check": datetime.now().isoformat(),
        },
    }


@rest_app.get("/ui")
async def ui_resources():
    """Return list of browsable resources for the legacy UI modal."""
    return ["items", "events"]


@rest_app.get("/api/items")
async def list_items():
    return [
        {"id": 1, "name": "Sample Item", "status": "active", "created_at": "2026-01-01T00:00:00"},
        {"id": 2, "name": "Another Item", "status": "active", "created_at": "2026-01-02T00:00:00"},
    ]


@rest_app.get("/api/events")
async def list_events():
    return [
        {"id": 1, "item_id": 1, "event_type": "created", "created_at": "2026-01-01T00:00:00"},
    ]


# ---------------------------------------------------------------------------
# Web UI (served on the same port, proxied via /apps/example_full_app/)
# ---------------------------------------------------------------------------

WEB_UI_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Example Full App</title>
    <style>
        body { font-family: sans-serif; max-width: 800px; margin: 2rem auto; padding: 0 1rem; }
        table { border-collapse: collapse; width: 100%; }
        th, td { border: 1px solid #ddd; padding: 8px; text-align: left; }
        th { background: #f4f4f4; }
        .badge { display: inline-block; padding: 2px 8px; border-radius: 4px;
                 font-size: 0.8rem; color: white; background: #0d6efd; }
    </style>
</head>
<body>
    <h1>Example Full App <span class="badge">v1.0.0</span></h1>
    <p>This is the web UI served by the app and proxied through Latarnia at
       <code>/apps/example_full_app/</code>.</p>
    <h2>Capabilities</h2>
    <ul>
        <li>Database (Postgres) with 3 migrations</li>
        <li>MCP server exposing 3 tools</li>
        <li>Redis Streams: publishes <code>example.events.created</code>,
            subscribes to <code>example.commands.process</code></li>
        <li>Depends on <code>example_companion</code> &ge; 1.0.0</li>
    </ul>
    <h2>Items</h2>
    <table>
        <thead><tr><th>ID</th><th>Name</th><th>Status</th></tr></thead>
        <tbody id="items"><tr><td colspan="3">Loading...</td></tr></tbody>
    </table>
    <script>
        fetch('/api/items')
            .then(r => r.json())
            .then(items => {
                const tbody = document.getElementById('items');
                tbody.innerHTML = items.map(i =>
                    `<tr><td>${i.id}</td><td>${i.name}</td><td>${i.status}</td></tr>`
                ).join('');
            })
            .catch(() => {
                document.getElementById('items').innerHTML =
                    '<tr><td colspan="3">Failed to load</td></tr>';
            });
    </script>
</body>
</html>"""


@rest_app.get("/", response_class=HTMLResponse)
async def web_ui_root():
    return WEB_UI_HTML


@rest_app.get("/index.html", response_class=HTMLResponse)
async def web_ui_index():
    return WEB_UI_HTML


# ---------------------------------------------------------------------------
# MCP Server
# ---------------------------------------------------------------------------

mcp_server = Server("example-full-app")


@mcp_server.list_tools()
async def list_tools():
    return [
        {
            "name": "list_items",
            "description": "List all items in the database",
            "inputSchema": {"type": "object", "properties": {}, "required": []},
        },
        {
            "name": "add_item",
            "description": "Add a new item to the database",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "name": {"type": "string", "description": "Item name"},
                    "description": {"type": "string", "description": "Item description"},
                },
                "required": ["name"],
            },
        },
        {
            "name": "get_status",
            "description": "Get the current status of the example app",
            "inputSchema": {"type": "object", "properties": {}, "required": []},
        },
    ]


@mcp_server.call_tool()
async def call_tool(name: str, arguments: dict):
    if name == "list_items":
        return [{"type": "text", "text": json.dumps([
            {"id": 1, "name": "Sample Item", "status": "active"},
            {"id": 2, "name": "Another Item", "status": "active"},
        ])}]
    if name == "add_item":
        item_name = arguments.get("name", "Unnamed")
        return [{"type": "text", "text": f"Added item: {item_name} (id=3)"}]
    if name == "get_status":
        return [{"type": "text", "text": json.dumps({
            "health": "good",
            "db_connected": db_url is not None,
            "mcp_port": mcp_port,
            "tools": 3,
        })}]
    raise ValueError(f"Unknown tool: {name}")


def _build_mcp_app() -> Starlette:
    sse_transport = SseServerTransport("/messages/")

    async def handle_sse(request):
        async with sse_transport.connect_sse(
            request.scope, request.receive, request._send
        ) as streams:
            await mcp_server.run(
                streams[0], streams[1],
                mcp_server.create_initialization_options(),
            )

    return Starlette(
        routes=[
            Route("/sse", endpoint=handle_sse),
            Mount("/messages/", app=sse_transport.handle_post_message),
        ]
    )


def _run_mcp_server(port: int):
    mcp_app = _build_mcp_app()
    logger.info("MCP server starting on port %d", port)
    uvicorn.run(mcp_app, host="0.0.0.0", port=port, log_level="warning")


# ---------------------------------------------------------------------------
# Redis Streams (background publisher example)
# ---------------------------------------------------------------------------

def _stream_publisher(redis_url_str: str, interval: int = 60):
    """Publish a heartbeat event to the declared stream every `interval` seconds."""
    try:
        r = redis.from_url(redis_url_str)
        stream_key = "latarnia:streams:example.events.created"
        while True:
            r.xadd(stream_key, {
                "source": "example_full_app",
                "timestamp": str(int(datetime.now().timestamp())),
                "version": "1.0",
                "data": json.dumps({"type": "heartbeat", "time": datetime.now().isoformat()}),
            })
            logger.debug("Published heartbeat to %s", stream_key)
            import time
            time.sleep(interval)
    except Exception as e:
        logger.error("Stream publisher failed: %s", e)


# ---------------------------------------------------------------------------
# Entrypoint
# ---------------------------------------------------------------------------

db_url = None
redis_url = None
mcp_port = None


def main():
    global db_url, redis_url, mcp_port

    parser = argparse.ArgumentParser(description="Example Full App")
    parser.add_argument("--port", type=int, default=8101, help="REST API port")
    parser.add_argument("--mcp-port", type=int, default=9001, help="MCP server port")
    parser.add_argument("--db-url", type=str, default=None, help="Postgres connection URL")
    parser.add_argument("--redis-url", type=str, default=None, help="Redis connection URL")
    parser.add_argument("--data-dir", type=str, default=None, help="Data directory")
    parser.add_argument("--logs-dir", type=str, default=None, help="Logs directory")
    args = parser.parse_args()

    db_url = args.db_url
    redis_url = args.redis_url
    mcp_port = args.mcp_port

    logger.info("Starting Example Full App")
    logger.info("  REST port: %d", args.port)
    logger.info("  MCP port:  %d", args.mcp_port)
    logger.info("  DB URL:    %s", "set" if db_url else "not set")
    logger.info("  Redis URL: %s", "set" if redis_url else "not set")

    # Start MCP server in background thread
    mcp_thread = threading.Thread(target=_run_mcp_server, args=(args.mcp_port,), daemon=True)
    mcp_thread.start()

    # Start Redis Streams publisher in background thread (if Redis available)
    if redis_url:
        pub_thread = threading.Thread(
            target=_stream_publisher, args=(redis_url, 60), daemon=True
        )
        pub_thread.start()

    # Run REST API (with web UI) on main thread
    uvicorn.run(rest_app, host="0.0.0.0", port=args.port, log_level="info")


if __name__ == "__main__":
    main()
