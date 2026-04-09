"""
Minimal MCP Server Example for Latarnia Apps

This standalone example demonstrates how a Latarnia service app can expose
an MCP (Model Context Protocol) server alongside its REST API. The MCP server
uses the `mcp` Python SDK with SSE (Server-Sent Events) transport.

Requirements:
    pip install mcp starlette uvicorn

Usage:
    python mcp_server_example.py

    # In another terminal, verify the MCP server:
    curl -N http://localhost:9001/sse

This example is intended to be adapted into a full Latarnia app (see Scope 9).
The REST API (FastAPI on --port) and MCP server (on mcp_port) run as separate
processes or async servers within the same app.
"""

import argparse
import asyncio
import logging
import threading
from datetime import datetime

import uvicorn
from fastapi import FastAPI
from mcp.server import Server
from mcp.server.sse import SseServerTransport
from starlette.applications import Starlette
from starlette.routing import Route, Mount

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

logger = logging.getLogger("mcp_server_example")
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)

# ---------------------------------------------------------------------------
# MCP Server Setup
# ---------------------------------------------------------------------------

mcp_server = Server("example-mcp-app")


@mcp_server.list_tools()
async def list_tools():
    """Return the list of tools this app provides via MCP."""
    return [
        {
            "name": "get_time",
            "description": "Return the current server time in ISO-8601 format",
            "inputSchema": {
                "type": "object",
                "properties": {},
                "required": [],
            },
        },
        {
            "name": "echo",
            "description": "Echo back the provided message",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "message": {
                        "type": "string",
                        "description": "The message to echo",
                    }
                },
                "required": ["message"],
            },
        },
    ]


@mcp_server.call_tool()
async def call_tool(name: str, arguments: dict):
    """Execute a tool invocation."""
    if name == "get_time":
        return [{"type": "text", "text": datetime.now().isoformat()}]

    if name == "echo":
        message = arguments.get("message", "")
        return [{"type": "text", "text": f"Echo: {message}"}]

    raise ValueError(f"Unknown tool: {name}")


def _build_mcp_app() -> Starlette:
    """Build the Starlette ASGI app that serves MCP over SSE."""
    sse_transport = SseServerTransport("/messages/")

    def handle_sse(scope, receive, send):
        async def _run():
            async with sse_transport.connect_sse(
                scope, receive, send
            ) as streams:
                await mcp_server.run(
                    streams[0],
                    streams[1],
                    mcp_server.create_initialization_options(),
                )
        return _run()

    return Starlette(
        routes=[
            Route("/sse", endpoint=handle_sse),
            Mount("/messages/", app=sse_transport.handle_post_message),
        ]
    )


# ---------------------------------------------------------------------------
# REST API (standard Latarnia /health endpoint)
# ---------------------------------------------------------------------------

rest_app = FastAPI()


@rest_app.get("/health")
async def health():
    return {
        "health": "good",
        "message": "MCP example app is running",
        "extra_info": {
            "mcp_tools": 2,
            "last_check": datetime.now().isoformat(),
        },
    }


# ---------------------------------------------------------------------------
# Entrypoint — runs both REST and MCP servers
# ---------------------------------------------------------------------------


def _run_mcp_server(mcp_port: int):
    """Run the MCP server in a separate thread with its own event loop."""
    mcp_app = _build_mcp_app()
    logger.info(f"MCP server starting on port {mcp_port}")
    uvicorn.run(mcp_app, host="0.0.0.0", port=mcp_port, log_level="warning")


def main():
    parser = argparse.ArgumentParser(description="Latarnia MCP server example app")
    parser.add_argument("--port", type=int, default=8100, help="REST API port")
    parser.add_argument("--mcp-port", type=int, default=9001, help="MCP server port")
    args = parser.parse_args()

    # Start MCP server in a background daemon thread
    mcp_thread = threading.Thread(
        target=_run_mcp_server, args=(args.mcp_port,), daemon=True
    )
    mcp_thread.start()

    # Run the REST API on the main thread
    logger.info(f"REST API starting on port {args.port}")
    uvicorn.run(rest_app, host="0.0.0.0", port=args.port, log_level="info")


if __name__ == "__main__":
    main()
