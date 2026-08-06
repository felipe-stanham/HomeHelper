# P-0011 — Workflows

## flow-01 — Login with a mixed-case username (cap-001)

`auth/routes.py:post_login` is unchanged. Normalization is invisible to it because it
happens inside `UserStore.get_user_by_username`. TOTP validation keys off `user["id"]`, so
the stored casing is irrelevant to credential lookup.

```mermaid
sequenceDiagram
    participant U as User (browser)
    participant R as auth/routes.py<br/>post_login
    participant S as UserStore
    participant DB as latarnia_platform_{env}
    participant T as TotpProvider
    participant SS as SessionStore

    U->>R: POST /auth/login<br/>username=FELIPE&code=123456
    R->>S: get_user_by_username("FELIPE")
    Note over S: normalize_username()<br/>strip + lower → "felipe"
    S->>DB: SELECT id, username, ... WHERE username = 'felipe'
    DB-->>S: {id: c3.., username: "felipe", is_active: true}
    S-->>R: user row
    R->>T: validate(user["id"], {"code": "123456"})
    T-->>R: true
    R->>S: touch_last_login(user["id"])
    R->>SS: create_session(user["id"], client_ip)
    SS-->>R: session token
    R-->>U: 303 → /dashboard<br/>Set-Cookie: session
```

Failure path is unchanged: an unknown name still yields the generic
`Invalid username or code.` at HTTP 401 — the project removes the capitalization *cause*
without weakening the message.

## flow-02 — Invite: case-variant duplicate is rejected (cap-001)

```mermaid
flowchart TD
    A["POST /api/auth/users<br/>{username: 'Felipe'}<br/>Superuser only"] --> B["body.username.strip()<br/>routes.py:340 — unchanged"]
    B --> C{"USERNAME_RE match?<br/>^[A-Za-z0-9._-]{1,64}$<br/>unchanged — accepts mixed case"}
    C -->|no| D["400 — username must be 1-64 chars<br/>of letters, digits, '.', '_', '-'"]
    C -->|yes| E["UserStore.get_user_by_username('Felipe')"]
    E --> F["normalize_username → 'felipe'"]
    F --> G{"row exists?"}
    G -->|yes| H["409 — username already exists<br/>NEW: now fires for case variants"]
    G -->|no| I["UserStore.create_user('Felipe')"]
    I --> J["normalize_username → 'felipe'"]
    J --> K["INSERT username='felipe',<br/>is_active=FALSE, setup_token"]
    K --> L["200 — {setup_url}<br/>dashboard shows 'felipe'"]
```

## flow-03 — Migration 007 applied at platform startup (cap-002, cap-003)

The migration runs inside the existing single-transaction batch in
`AuthDB._run_migrations`. The notice handler is attached to the connection *before* any
migration executes, so warnings raised by 007 are captured.

```mermaid
sequenceDiagram
    participant M as main.py startup
    participant A as AuthDB
    participant P as PgClient
    participant DB as latarnia_platform_{env}
    participant L as logger<br/>latarnia.auth.db

    M->>A: initialize()
    A->>P: transaction(db_name)
    P-->>A: conn (autocommit=False)
    A->>P: conn.add_notice_handler(_forward)
    Note over A: cap-003 — attached once,<br/>covers every pending migration
    A->>DB: execute(007_lowercase_usernames.sql)
    Note over DB: DO block resolves collisions
    DB-->>L: WARNING 'P-0011: renamed Felipe -> felipe3 (user c3..)'
    L->>L: logger.warning("migration: ...")
    Note over DB: UPDATE ... SET username = lower(username)
    Note over DB: ADD CHECK (username = lower(username))
    DB-->>A: ok
    A->>DB: INSERT INTO schema_versions (007..., checksum, duration_ms)
    A->>P: conn.commit()
    A-->>M: True
```

On any failure the existing `except` path calls `conn.rollback()` and re-raises, so a
partially folded `users` table is not possible.

## flow-04 — Collision resolution algorithm inside migration 007 (cap-002)

```mermaid
flowchart TD
    A["SELECT lower(username) AS lname<br/>FROM users GROUP BY 1<br/>HAVING COUNT(*) > 1"] --> B{"any groups?"}
    B -->|no| Z["skip to fold step"]
    B -->|yes| C["for each group lname"]
    C --> D["SELECT id, username FROM users<br/>WHERE lower(username) = lname<br/>ORDER BY created_at, id OFFSET 1"]
    Note1["OFFSET 1 — the oldest row is not<br/>renamed; it keeps lname"]
    D --> Note1
    Note1 --> E["for each remaining row:<br/>base := left(lname, 62)"]
    E --> F["n := n + 1 (starts at 2)<br/>cand := base || n"]
    F --> G{"EXISTS row WHERE<br/>lower(username) = cand?"}
    G -->|yes| F
    G -->|no| H["UPDATE users SET username = cand<br/>WHERE id = row.id"]
    H --> I["RAISE WARNING<br/>'renamed old -> cand (user id)'"]
    I --> E
    E -->|group exhausted| C
    C -->|all groups done| Z
    Z --> Y["UPDATE users SET username = lower(username)<br/>WHERE username <> lower(username)"]
    Y --> X["DROP CONSTRAINT IF EXISTS<br/>users_username_lowercase"]
    X --> W["ADD CONSTRAINT users_username_lowercase<br/>CHECK (username = lower(username))"]
```

`left(lname, 62)` keeps a renamed username inside the 1–64 character contract that
`USERNAME_RE` enforces on invite, even when the original name used all 64 characters.
The `EXISTS` check compares against `lower(username)` rather than `username`, so a
candidate cannot collide with a row that has not yet been folded.

## flow-05 — Notice severity mapping (cap-003)

```mermaid
flowchart LR
    A["Postgres server notice<br/>(Diagnostic)"] --> B["_forward_notice(logger, diag)"]
    B --> C{"severity_nonlocalized in<br/>WARNING / ERROR / FATAL / PANIC?"}
    C -->|yes| D["logger.warning('migration: %s',<br/>diag.message_primary)"]
    C -->|no| E["logger.debug('migration: %s',<br/>diag.message_primary)"]
```

`NOTICE`, `INFO`, `DEBUG`, and `LOG` severities land at DEBUG so routine chatter (for
example the implicit index creation notices Postgres emits for `PRIMARY KEY`) does not
pollute the WARNING stream in a `prd` deploy log.
