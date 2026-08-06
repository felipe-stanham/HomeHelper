# P-0011 — Architecture

## Component view

No new component. Three touch points inside the existing auth subsystem (P-0008), shown in
bold. Everything else is context.

```mermaid
flowchart TD
    subgraph Browser
        LOGIN["templates/auth/login.html<br/>username input — unchanged"]
        DASH["templates/dashboard.html<br/>Users panel — unchanged,<br/>renders whatever /api/users returns"]
    end

    subgraph Platform["Latarnia platform process"]
        ROUTES["auth/routes.py<br/>post_login, POST /api/users<br/>UNCHANGED — USERNAME_RE and all<br/>status codes stay as they are"]
        US["<b>auth/users.py</b><br/><b>normalize_username()</b> — cap-001<br/>UserStore.create_user<br/>UserStore.get_user_by_username"]
        TOTP["auth/providers/totp.py<br/>uses username as QR label only;<br/>secret keyed by user_id"]
        ROLES["auth/roles.py — RoleStore<br/>keyed by user_id; app_name untouched"]
        ADB["<b>auth/db.py — AuthDB</b><br/><b>_run_migrations + notice handler</b> — cap-003"]
        MIG["<b>auth/migrations/</b><br/>001..006 existing<br/><b>007_lowercase_usernames.sql</b> — cap-002"]
    end

    PG[("Postgres<br/>latarnia_platform_{env}<br/>users.username lowercase<br/>+ CHECK constraint")]

    LOGIN -->|POST /auth/login| ROUTES
    DASH -->|GET/POST /api/users| ROUTES
    ROUTES --> US
    ROUTES --> TOTP
    ROUTES --> ROLES
    US -->|"query_one / execute_returning"| ADB
    ROLES --> ADB
    TOTP --> ADB
    ADB --> PG
    MIG -->|read at startup| ADB
```

The key architectural decision is **where** normalization lives. `UserStore` is the only
module that issues SQL against the `users` table, so folding inside it makes the invariant
structural rather than a convention every caller must remember. `routes.py` therefore needs
no edit at all: its 409 duplicate check, the login lookup, and the bootstrap superuser
lookup already route through `UserStore.get_user_by_username`.

## Startup sequence — where migration 007 lands

```mermaid
sequenceDiagram
    participant MAIN as main.py lifespan
    participant ADB as AuthDB
    participant PGC as core/pg_client.py<br/>PgClient
    participant PG as Postgres

    MAIN->>ADB: initialize()
    ADB->>PGC: database_exists(latarnia_platform_{env})
    PGC-->>ADB: True
    ADB->>PGC: execute_on_db(SCHEMA_VERSIONS_DDL)
    ADB->>ADB: _applied() → {001..006}
    ADB->>ADB: pending = [007_lowercase_usernames.sql]
    ADB->>PGC: transaction(db_name)
    PGC-->>ADB: conn
    ADB->>ADB: conn.add_notice_handler(_forward)
    ADB->>PG: execute(007 SQL)
    PG-->>ADB: notices → logger (cap-003)
    ADB->>PG: INSERT schema_versions(007, checksum)
    ADB->>PG: commit
    ADB-->>MAIN: True
    Note over MAIN: no request is served until<br/>this completes — no window in which<br/>an uppercase username can be written
```

## Deployment topology

Migration 007 is applied independently by each platform process at its own startup. There is
no cross-host coordination and none is needed: the migration is per-database and
self-contained.

```mermaid
flowchart LR
    subgraph GH["GitHub Actions"]
        DEV["push to dev"]
        TST["merge dev → tst<br/>deploy-tst.yml"]
        PRD["merge tst → main<br/>deploy-prd.yml<br/>fail-fast: false matrix"]
    end

    subgraph HS["homeserver (Raspberry Pi 5, ARM64)<br/>runner label: homeserver"]
        HDEV[("latarnia_platform_dev")]
        HTST[("latarnia_platform_tst")]
        HPRD[("latarnia_platform_prd")]
    end

    subgraph HZ["hetzner-latarnia-1 (Debian 13, x86_64)<br/>runner label: hetzner-latarnia-1"]
        ZPRD[("latarnia_platform_prd")]
    end

    LOCAL[("local macOS dev<br/>latarnia_platform_dev<br/>Postgres 17.6")]

    DEV -.->|manual local run| LOCAL
    TST --> HTST
    PRD --> HPRD
    PRD --> ZPRD
    HS --> HDEV

    LOCAL -->|"007 applied at startup"| L1["users folded"]
    HTST -->|"007 applied at startup"| L2["users folded"]
    HPRD -->|"007 applied at startup"| L3["users folded"]
    ZPRD -->|"007 applied at startup"| L4["users folded"]
```

Each of the four platform databases runs 007 once. Because collision renames are ordered by
`created_at`, two prd hosts holding *different* user data could in principle derive
different suffixes — the pre-deploy query in `spec.md` (Risks) establishes whether either
host has any collision at all before `main` is touched.

## Data flow — a username from keystroke to storage

```mermaid
flowchart LR
    A["'  Felipe  '<br/>typed in browser"] --> B["routes.py: .strip()<br/>→ 'Felipe'"]
    B --> C["USERNAME_RE validate<br/>→ pass (uppercase allowed)"]
    C --> D["<b>normalize_username()</b><br/>strip + lower → 'felipe'"]
    D --> E["INSERT / SELECT param<br/>'felipe'"]
    E --> F{"CHECK<br/>username = lower(username)"}
    F -->|pass| G[("users.username = 'felipe'<br/>UNIQUE enforced")]
    F -->|fail| H["CheckViolation<br/>— only reachable if a future<br/>code path bypasses UserStore"]
```

`strip()` appears twice (once in `routes.py`, once in `normalize_username`) and that is
intentional: the login path never calls the `routes.py` strip, so the helper must be
self-sufficient rather than assume a pre-cleaned input.

## External systems

None added. No new extension, service, port, secret, or dependency. `psycopg`'s
`add_notice_handler` is part of the already-pinned `psycopg[binary]>=3.1.0,<4.0.0`.
