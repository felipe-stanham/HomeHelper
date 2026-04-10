# Memory

## Workflow

- **Always test in DEV before deploying to TST.** Run unit tests (`python3 -m pytest tests/ -v --tb=short --no-cov`) and, for runtime changes, spin up the dev server locally. Never skip straight to TST, even for "obvious" fixes. (Learned: deploying untested SSE fixes to TST caused two rounds of broken deployments.)

- **Always log deployments.** After every successful deployment, add a row to `DEPLOYMENTS.md` with: date, target, branch, commit hash, and a short note. Do not skip this step.

- **CLAUDE.md is project-agnostic.** It's a reusable template for future projects. Project-specific rules (e.g., example apps, port ranges, deployment targets) belong in `docs/SYSTEM.md`. Non-obvious learnings belong here in MEMORY.md.

## Project Rules

- **Example apps are the integration test fixtures.** `example_full_app` and `example_companion` in `examples/` exercise every platform feature (DB, MCP, Redis Streams, web UI, dependencies). Any platform feature change must include a corresponding update to `example_full_app`. `examples/` is committed (source of truth); `apps/` is gitignored and populated from `examples/` during deployment or local dev.

- **MCP servers are configured in `.mcp.json`** at the project root, NOT in `settings.json` (the `mcpServers` key is not valid in settings.json). Auto-approval is set via `enableAllProjectMcpServers: true` in `.claude/settings.json`. Current servers: `latarnia-tst` (SSE to RPi at 192.168.68.100:8000) and `playwright` (local stdio via npx).

- **User runs Claude Code with `CLAUDE_CONFIG_DIR=~/.claude-dor`** (alias `claude-dor`). Global settings are at `~/.claude-dor/settings.json`, not `~/.claude/settings.json`.
