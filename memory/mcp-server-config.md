# MCP Server Configuration

MCP servers for Claude Code are configured in `.mcp.json` at the project root. The `mcpServers` key is NOT valid in `settings.json` — this was a source of confusion in an early session.

Auto-approval of project MCP servers is set via `enableAllProjectMcpServers: true` in `.claude/settings.json`.

## Current Servers

- `latarnia-tst` — SSE connection to the Latarnia TST environment on the Raspberry Pi (`http://192.168.68.100:8000/mcp/sse`). Exposes tools from deployed apps.
- `playwright` — Local stdio server (`npx @playwright/mcp@latest`). Used for browser-level testing of dashboards and web UIs.

## User Profile

The user runs Claude Code with `CLAUDE_CONFIG_DIR=~/.claude-dor` (alias `claude-dor`). Global settings are at `~/.claude-dor/settings.json`, not `~/.claude/settings.json`.
