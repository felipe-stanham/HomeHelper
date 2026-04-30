# P-0006 Architecture

## Component placement

`SecretManager` is a new platform-side component, peer to `ServiceManager` / `SubprocessLauncher` / `DbProvisioner` / `MCPGateway`. It owns the master `secrets.env` and the per-app filtered files. Both launchers consult it on every `start_service` call.

```mermaid
flowchart LR
    subgraph Platform[Latarnia main process]
        Main[main.py lifespan]
        Router[pick_launcher]
        SvcMgr[ServiceManager<br/>Linux]
        SubLn[SubprocessLauncher<br/>Darwin]
        SM[SecretManager<br/>NEW]
        Reg[AppRegistry]
        API["/api/secrets<br/>(GET, listing)"]
    end

    subgraph FS["File system (per env)"]
        Master["secrets.env<br/>(operator-edited; mode 600)"]
        SecretsDir["secrets/<br/>(platform-managed; mode 700)"]
        AppFiles["secrets/{app_id}.env<br/>(platform-written; mode 600)"]
    end

    subgraph SystemD["systemd --user (Linux)"]
        Unit["latarnia-{env}-{app_id}.service<br/>EnvironmentFile=-secrets/{app_id}.env"]
        AppProc["app process<br/>(env has declared secrets)"]
    end

    Main --> SM
    Main --> Router
    Router --> SvcMgr
    Router --> SubLn

    SvcMgr -->|validate_and_materialize| SM
    SubLn -->|validate_and_get_env| SM
    SM -->|read| Master
    SM -->|write| AppFiles
    AppFiles -.contained in.-> SecretsDir

    SvcMgr -->|generate unit incl. EnvironmentFile=| Unit
    Unit --> AppProc

    SubLn -.Popen env=...-> AppProc

    API -->|list_secrets| SM
    SM -->|get_all_apps| Reg

    style SM fill:#e1f5ff
    style Master fill:#fff4e1
    style AppFiles fill:#e1ffe1
```

The blue node is new. Master file (yellow) is operator-owned; the platform never writes to it. Per-app files (green) are 100% platform-managed and idempotently regenerated on every launch.

---

## File-system layout (per env)

```mermaid
flowchart TD
    EnvRoot["/opt/latarnia/{env}/"]
    EnvRoot --> Apps["apps/<br/>(discovered)"]
    EnvRoot --> Data["data/{app_id}/<br/>(--data-dir, P-0001)"]
    EnvRoot --> Logs["logs/{app_id}.log<br/>(macOS dev only, P-0005)"]
    EnvRoot --> Venv[".venv/<br/>(shared interpreter)"]
    EnvRoot --> Master["secrets.env<br/>mode 600<br/>NEW in P-0006<br/>OPERATOR-EDITED"]
    EnvRoot --> SecDir["secrets/<br/>mode 700<br/>NEW in P-0006<br/>PLATFORM-MANAGED"]
    SecDir --> AppA["{app_a}.env<br/>mode 600"]
    SecDir --> AppB["{app_b}.env<br/>mode 600"]

    style Master fill:#fff4e1
    style SecDir fill:#e1ffe1
    style AppA fill:#e1ffe1
    style AppB fill:#e1ffe1
```

- **Master** is the only file the operator edits. One per env (TST and PRD must NOT share).
- **`secrets/`** dir is created by the platform on first need; mode 700 (only `felipe` enters).
- **`{app_id}.env`** files are written by `SecretManager.materialize` before each `start_service`. Idempotent — same input always produces same output. Stale files (apps removed) are NOT cleaned up in v1.

---

## Lifecycle: validate → materialize → launch

The tight sequence around every `start_service` call.

```mermaid
sequenceDiagram
    participant Caller as ServiceManager.start_service
    participant SM as SecretManager
    participant Master as secrets.env
    participant PerApp as secrets/{app_id}.env
    participant Reg as AppRegistry

    Caller->>SM: validate_and_materialize(app_entry)
    activate SM

    SM->>Master: load() — open + stat
    alt mode wider than 600
        SM->>SM: logger.warning('master file too permissive: {path}')
        SM-->>Caller: ValidationResult(ok=False, detail="master file mode 6XX too permissive")
        Caller->>Caller: return False (refuse-to-start)
    end

    Master-->>SM: contents (parsed, dict[str,str])

    SM->>SM: declared = app_entry.manifest.config.requires_secrets
    SM->>SM: missing = [k for k in declared if k not in contents]

    alt missing is non-empty
        SM->>Reg: registry.update_app(app_id,<br/>status=ERROR,<br/>runtime_info.error_message=...)
        SM-->>Caller: ValidationResult(ok=False,<br/>missing=[...],<br/>detail="missing required secret: X")
        Caller->>Caller: return False (refuse-to-start)
    end

    SM->>SM: filtered = {k: contents[k] for k in declared}

    alt declared is empty
        SM-->>Caller: ValidationResult(ok=True)<br/>(no per-app file written)
    else
        SM->>PerApp: write filtered (mode 600)
        SM-->>Caller: ValidationResult(ok=True)
    end

    deactivate SM

    Caller->>Caller: continue: port alloc → unit gen → systemctl start
```

Key invariants:

1. **Validation runs before any side effect.** Port allocation + unit file generation + systemctl start happen only after `ok=True`.
2. **`registry.update_app` on failure** is what surfaces the error in `/api/apps` `overall_status` (red) via `runtime_info.error_message` — reusing existing P-0005 cap-005 plumbing, no new fields.
3. **Apps with `requires_secrets: []`** (the vast majority) never write a per-app file. The systemd unit's `EnvironmentFile=-...` line is harmless because of the `-` (ignore-missing).

---

## Deployment topology (Pi, after P-0006)

```mermaid
flowchart TB
    subgraph Pi["Raspberry Pi 5 (HERMES)"]
        subgraph SystemScope["System-scope systemd"]
            TstUnit[latarnia-tst.service<br/>main platform]
            PrdUnit[latarnia-prd.service<br/>main platform]
        end

        subgraph TstFS["/opt/latarnia/tst/"]
            TstMaster[secrets.env<br/>operator-edited]
            TstSec[secrets/]
            TstAppSec[secrets/latarnik.env<br/>platform-written]
        end

        subgraph PrdFS["/opt/latarnia/prd/"]
            PrdMaster[secrets.env<br/>operator-edited]
            PrdSec[secrets/]
            PrdAppSec[secrets/latarnik.env<br/>platform-written]
        end

        subgraph TstUserUnits["~felipe/.config/systemd/user/ (TST)"]
            TstAppUnit[latarnia-tst-latarnik.service<br/>EnvironmentFile=-/opt/latarnia/tst/secrets/latarnik.env]
        end

        subgraph PrdUserUnits["~felipe/.config/systemd/user/ (PRD)"]
            PrdAppUnit[latarnia-prd-latarnik.service<br/>EnvironmentFile=-/opt/latarnia/prd/secrets/latarnik.env]
        end

        TstUnit -->|reads via SecretManager| TstMaster
        TstUnit -->|writes via SecretManager| TstAppSec
        PrdUnit -->|reads via SecretManager| PrdMaster
        PrdUnit -->|writes via SecretManager| PrdAppSec

        TstAppSec -.referenced by.-> TstAppUnit
        PrdAppSec -.referenced by.-> PrdAppUnit
    end

    Op([Operator]) -->|"$EDITOR + chmod 600"| TstMaster
    Op -->|"$EDITOR + chmod 600"| PrdMaster
```

Key isolation property: a TST app's process can never read PRD secrets, and vice versa. Two mechanisms enforce this:

1. The two main-platform units run with different `Environment=ENV={env}`; each platform's `SecretManager` is bound to its own env at construction. It only ever reads `/opt/latarnia/{env}/secrets.env` — the path is computed from `self.env`, not from the request.
2. The per-app filtered files are written under env-scoped paths (`/opt/latarnia/tst/secrets/...` vs `/opt/latarnia/prd/secrets/...`). The systemd unit's `EnvironmentFile=` is absolute and bakes in the env at unit-write time.

---

## External system interactions

No new external interactions. P-0006 is platform-internal — file-system + the existing systemd integration. No network calls, no Redis pub/sub, no external secret store.

```mermaid
flowchart LR
    Operator([felipe with $EDITOR]) -->|writes| Master[secrets.env]
    Master -->|read by| Plat[Latarnia platform]
    Plat -->|writes filtered| PerApp[per-app .env]
    PerApp -->|EnvironmentFile=- / Popen env=| App[app process]
    App -->|os.environ| AppLogic[app logic]

    style Master fill:#fff4e1
    style PerApp fill:#e1ffe1
```

The arrow that would have existed in a CLI design (`latarnia secrets set ...`) is replaced by `$EDITOR` directly. We accept that the operator must remember `chmod 600` on first create; the platform refuses to read insufficiently-restricted files and logs why.

---

## Rejected alternatives (and why)

| Alternative | Why rejected for v1 |
|---|---|
| `EnvironmentFile=` pointing directly at master `secrets.env` (no per-app filtering) | Every app would see every secret. Pitch's "injected into the launched app's environment ONLY — not other apps'" rules this out. |
| `Environment=KEY=value` lines inlined into the generated unit file | Values would be readable from `~felipe/.config/systemd/user/latarnia-{env}-{app}.service`, a path more discoverable than the master file. Per-app filtered file with mode 600 in a 700 directory limits exposure surface. |
| Latarnia-side `os.execvpe` of the app with merged environment | Requires the platform to host the process, breaking systemd's ownership and giving up `Restart=`, journald, and reconciliation. Big regression vs P-0005. |
| HashiCorp Vault / external secret store | Overkill for single-operator Pi; deployment cost > the problem. |
| Latarnia CLI (`latarnia secrets set ...`) | No CLI binary exists today; introducing one for this feature alone is over-scope. File-only matches the existing operator surface (config files + dashboard buttons). |
| Encryption at rest (age/sops) | Defence-in-depth on top of mode 600 is real value but adds a key-management story (where does the platform's decryption key live?). v1 ships with mode 600 only; v2 can layer this on. |
