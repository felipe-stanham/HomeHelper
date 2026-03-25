# Claude Code — Project Instructions

## Session Startup

At the start of every session:
1. Read `MEMORY.md` if it exists — it contains persistent learnings from past sessions.
2. Read `docs/SYSTEM.md` if it exists — it contains a lightweight description of the current system state and active projects.

## System Context

- `docs/SYSTEM.md` is the always-loaded system index. It describes the existing system at a high level without requiring all project files to be read.
- `docs/SYSTEM.md` contains:
  - A brief description of what the system does and its main components
  - Key architectural decisions that must be respected across all projects
  - A list of completed and active projects with one-line summaries and links to their `P-xxxx.md`
  - Cross-project constraints that apply to every session
- Never load individual project files unless the user specifies which project to work on.
- When a project's final scope is marked `[DONE]`, update the project's entry in `docs/SYSTEM.md` to reflect its completed status.
- If `docs/SYSTEM.md` does not exist at session start, ask the user whether to create it before proceeding.

The expected `SYSTEM.md` format is:

```
# System: [System Name]

## What This System Does
[2–4 sentences describing the system's purpose and main components]

## Architecture Principles
- [Key decision that must be respected, e.g., "API-first: all features exposed via REST before UI"]
- [Another constraint, e.g., "Single Postgres database — no secondary datastores"]

## Cross-Project Constraints
- [Constraint that applies to every project, e.g., "All auth uses JWT via auth-service"]

## Projects
| ID      | Name            | Status      | Summary                              |
|---------|-----------------|-------------|--------------------------------------|
| P-0001  | [Project Name]  | [DONE]      | One-line description                 |
| P-0002  | [Project Name]  | [ACTIVE]    | One-line description                 |
```

---

## General

- Plans are produced externally and arrive as `docs/Projects/P-xxxx.md`. Do not modify the plan — if something in it is wrong or unclear, stop and ask.
- I will indicate in which project we will be working on by specifying the corresponding file.
- Do NOT read all the files in `docs/Projects/` folder unless instructed to.
- Commit after each completed task (not mid-implementation). Use clear, descriptive commit messages.
- When blocked or at a decision point with no clear answer, stop and ask rather than guessing.
- Prefer the simplest solution that works. Do not create abstractions unless there are at least two concrete use cases today.

## Memory

- `MEMORY.md` is the only place for persistent learnings. Update it when you discover gotchas, failed patterns, or non-obvious constraints.
- Never solve the same problem twice — if you're re-discovering something, it belongs in `MEMORY.md`.

---

## Environments

Every project must support at least two environment configurations: **dev** (local development and testing) and **prod** (production).

### Configuration

- Environment is selected via `ENV` variable in `.env` (values: `dev`, `prod`). Default is `dev`.
- Each environment has its own configuration block in `.env`. Use a prefix convention:
  ```
  ENV=dev
  # Dev environment
  DEV_API_URL=https://dev.example.com
  DEV_API_USER=dev-user@example.com
  DEV_API_TOKEN=dev-token
  # Prod environment
  PROD_API_URL=https://prod.example.com
  PROD_API_USER=prod-user@example.com
  PROD_API_TOKEN=prod-token
  ```
- The config module must load the correct set of credentials based on `ENV`. Shared settings that are the same across environments do not need a prefix.
- If a project does not have external services (pure local app with no API), the `ENV` variable is still required but may only affect logging verbosity or output paths.

### Rules

- **Never run tests against prod.** All automated and manual testing uses `dev` environment only.
- **Never run destructive operations (create, update, delete) against prod** unless the user explicitly confirms.
- Before executing any test or destructive operation, verify the active environment. If `ENV=prod`, stop and warn the user.

---

## Logging

- Use Python `logging` module (or the language-appropriate equivalent). Never use `print()` for operational output.
- Log level is controlled by environment: `dev` defaults to `DEBUG`, `prod` defaults to `WARNING`.
- Log format must include: timestamp, level, module name, and message. Example: `2026-03-20 14:30:00 [INFO] fetcher: Fetched 12 children for FEAT-100`.
- Log to stdout/stderr by default. File logging is added only if the project requires it.
- What to log:
  - **INFO:** Key operation milestones (start/end of major workflows, external API calls, file writes).
  - **DEBUG:** Detailed internal state useful during development (variable values, loop iterations, config loaded).
  - **WARNING:** Recoverable issues (missing optional config, fallback behavior triggered, retries).
  - **ERROR:** Failures that stop an operation (API errors, missing required config, file write failures).
- Never log secrets, tokens, or full API responses containing sensitive data. Mask or omit them.

---

## Branching Strategy

- Branch naming: `scope/P-XXXX-NUMBER-<short-description>`
- Always branch off `main`. Never branch off another scope branch.
- One agent per branch when working in parallel.
- Never commit directly to `main` except for trivial fixes.
- Before merging to main: run all regression tests (see Testing section below). Do not merge if any test fails.
- Check with me before merging to main.
- Delete the branches after merging to main.

---

## Planning

For any non-trivial task, plan before coding:
1. Explore relevant files, patterns, and existing implementations.
2. Read architecture docs and constraints.
3. If a spec package exists for the project (e.g., `spec.md`, `workflows.md`, `data_model.md`, `architecture.md` in the same folder as `P-xxxx.md`), read them before proposing an approach.
4. Propose an approach and identify all files to be modified.
5. Wait for approval before writing any code.

---

## CodeReview

After finishing a task and befor commit, review the code with the review agent.

---

## Testing

### Core Rule

**Tests must be executed, not reviewed.** Reading code and confirming it "looks correct" is not testing. Every test must run as code, produce observable output, and report pass/fail. No scope can be marked `[DONE]` based on code review alone.

### Declarative Tests

Tests are defined declaratively in `TESTS.md` (and in each scope's acceptance criteria), not as pre-written test scripts. Each test entry describes **what to verify** and **what the expected result is**. At execution time, Claude Code reads the declarative test, writes a throwaway script or command to verify it, executes it, and reports pass/fail. No persistent test code is maintained.

This means:
- `TESTS.md` is the only test artifact that is maintained.
- There is no `tests/` directory with code files to keep in sync.
- When Claude Code runs tests, it generates the verification code on the fly, runs it, and discards it.
- The test description in `TESTS.md` must be specific enough that Claude Code can unambiguously generate the verification. Include: what to call/check, with what inputs, and what the expected output or behavior is.

### How to Test

When a scope is complete, execute tests against its acceptance criteria. Choose the appropriate method based on what the scope implements:

- **API endpoints** → Run requests against the running service. Assert status codes, response shapes, and business logic.
- **UI** → Use Playwright (via MCP if available) to interact with the running app. Verify that elements render, user flows work end-to-end, and error states display correctly.
- **Data processing / business logic** → Call functions directly with known inputs and assert expected outputs.
- **File output** → Generate the file, then programmatically inspect it (e.g., open with the appropriate library and assert values, structure, formatting).

### Environment

- **Always run tests against the `dev` environment.** Before executing any test, verify `ENV != prod`. If it is, stop and warn the user.
- Tests that create, modify, or delete external resources must use dev/sandbox credentials only.

### Test Execution Flow

For each scope being completed:
1. Ensure the application/service is running (if applicable).
2. Read the scope's acceptance criteria from `P-xxxx.md`.
3. For each acceptance criterion, generate a verification script, execute it, and report pass/fail.
4. All tests must pass. If any fail, fix the implementation and re-run.
5. Only after all tests pass, mark the scope `[DONE]`.

### Regression Tests (`TESTS.md`)

`TESTS.md` is the curated regression test registry. It contains only **critical-path tests** — tests that verify core functionality which, if broken, would make the system unusable or produce incorrect results.

**What to include in `TESTS.md`:**
- Tests for core workflows (e.g., "fetch a record tree and verify the hierarchy is correct")
- Tests for data integrity (e.g., "output file contains correct number of sections with expected names")
- Tests for integration points (e.g., "API authentication works and returns valid data")
- Tests for destructive operations (e.g., "create operation produces correct resource hierarchy")

**What NOT to include:**
- Cosmetic tests (border styles, column widths, exact color hex values)
- Edge cases that don't affect core functionality
- Tests that duplicate other tests at a different level

**Format for each test entry in `TESTS.md`:**
```
- **test_name:** [What to do] → [Expected result]
```
The description must be specific enough for Claude Code to generate a verification script without guessing. Include concrete inputs and expected outputs where possible.

**When a scope is marked `[DONE]`:**
1. Review its acceptance criteria and select which ones qualify as critical-path.
2. Add those to `TESTS.md` with concrete test descriptions.
3. If the scope modifies behavior covered by an existing entry in `TESTS.md`, update that entry.

**When to run regression tests:**
- Before merging any branch to `main`.
- Before deploying to prod (if applicable).
- Regression tests are always run against the `dev` environment.

**How to run regression tests:**
- Read `TESTS.md`, generate verification scripts for each entry, execute them, and report results.
- If any regression test fails, do not merge or deploy.

---

## Progress Tracking

- `P-xxxx.md` is the single source of truth for progress. Keep it current:
- Mark tasks `[x]` as they are completed.
- Update Scope status (`[ ]` → `[IN PROGRESS]` → `[DONE]`) after each commit.
- Never mark a Scope `[DONE]` unless its tests have been **executed and passed** (not just reviewed).

---

## Documentation

- Document all APIs as part of the task that implements them. REST APIs must use OpenAPI.
- At the end of each scope, update `docs/System/` to reflect the current state of the system. The following files must be kept up to date:
  - `workflows.md`
    - A set of Mermaid diagrams covering the main workflows and interactions:
    - `flowchart` for process flows and decision logic
    - `sequenceDiagram` for system/component interactions and API calls
  - `architecture.md` Mermaid diagrams covering:
    - High-level component architecture
    - Deployment topology
    - External system interactions
    - Data flow between components
  - `dataModel.md`: Mermaid `erDiagram` and/or `classDiagram` representing the data model.
    - Use `classDiagram` for objects/classes model.
    - Use `erDiagram` for databases.
    - Include field types and key relationships
- For every schema change, create a migration and rollback script in `docs/System/migrations/`, named `YYYYMMDD_short_description.sql`.
- Use sub-agents for documentation.
