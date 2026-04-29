# Pitch: Latarnia Secret Manager

**For:** Latarnia (HomeHelper) spec assistant
**From:** Latarnik (the first Latarnia app to need runtime secrets)
**Date:** 2026-04-26
**Status:** Draft pitch — please turn into a P-XXXX spec package.

---

## Problem

Latarnia apps increasingly need runtime secrets — API keys for external services (Anthropic, Voyage, OpenAI, etc.), tokens for third-party APIs (GitHub PATs, webhook signing keys), or credentials for non-platform-managed datastores. Today there is **no first-class way** to get a secret into an app's process environment.

Concrete blocker: **Latarnik cannot deploy until `VOYAGE_API_KEY` and `ANTHROPIC_API_KEY` reach its environment.** Latarnik validates both at startup and exits non-zero if missing. Today the only workaround is for the operator to hand-write a systemd user-level drop-in:

```
~/.config/systemd/user/latarnia-tst-latarnik.service.d/secrets.conf
```

That works once, but:

- It bypasses Latarnia entirely — the platform has no record that the app received those secrets.
- Rotation is manual (edit the file → `daemon-reload` → `restart`) and per-app.
- The same secret used by two apps must be written in two places.
- Per-environment isolation (`dev` / `tst` / `prd` having different keys) is operator discipline, not enforced.
- Audit ("when was this key last rotated?") is invisible to the platform.
- Apps that declare `config.requires_secrets` (Latarnik already does) get no validation — the platform silently doesn't honour the field.

This will only get worse as more apps land — every new app's deployment gains a "and now hand-edit this systemd file" step.

---

## Context (current state, do NOT re-derive)

- **Apps run as per-app systemd user units** named `latarnia-{env}-{app}.service` (P-0005 Scope 4).
- **Latarnia already passes scoped configuration via CLI args** (`--db-url`, `--redis-url`, `--data-dir`, etc.) so the pattern of platform-injected per-launch values exists.
- **The `latarnia.json` manifest already accepts a `config.requires_secrets` array** in some apps (Latarnik declares `["VOYAGE_API_KEY", "ANTHROPIC_API_KEY"]`) — it's currently ignored by the spec but apps are using it as forward-looking documentation.
- **Logs go to journald** (`journalctl --user -u latarnia-{env}-{app}.service`). Anything echoed to stdout/stderr at startup is durably captured. Latarnia must NOT log secret values during injection.
- **Multi-tenant on a single Pi:** `tst` and `prd` Latarnia instances coexist on the same host. They must NOT share secret state (`tst` Anthropic key ≠ `prd` Anthropic key, even if today they're identical).

---

## Appetite

Small to medium. The minimum viable feature is "operator stores secrets somewhere; Latarnia injects requested secrets into the launched app's environment, scoped per-env." Everything beyond that (rotation tooling, audit, encryption-at-rest, multi-operator access) can be a v2.

---

## Proposed shape (rough — open to redesign)

### What every app needs from this feature

```python
# In Latarnik's main.py (already implemented):
if not os.environ.get("VOYAGE_API_KEY"):
    sys.exit("missing required secret: VOYAGE_API_KEY")
```

That is the entire app-side contract: **the secret is in `os.environ` when the app starts.** Apps don't care how it got there.

### Suggested operator-side flow (v1)

1. **Declare** in the manifest:
   ```json
   {
     "config": {
       "requires_secrets": ["VOYAGE_API_KEY", "ANTHROPIC_API_KEY"]
     }
   }
   ```
2. **Set** values, scoped per-env, via a Latarnia CLI subcommand (or a config file the operator edits):
   ```sh
   latarnia secrets set --env tst VOYAGE_API_KEY=pa-xxxxx
   latarnia secrets set --env tst ANTHROPIC_API_KEY=sk-ant-xxxxx
   latarnia secrets set --env prd VOYAGE_API_KEY=pa-yyyyy   # different value for prd
   ```
3. **Inject** at app launch: when Latarnia starts `latarnia-tst-latarnik.service`, it reads the set of secret names from the app's manifest, looks them up in the per-env secret store, and ensures they're in the process environment of that one unit only.
4. **Rotate** by re-running `latarnia secrets set ...` and restarting the consuming apps. The platform should be able to enumerate which apps consume a given secret name.
5. **Inspect** without leaking values:
   ```sh
   latarnia secrets list --env tst
   # VOYAGE_API_KEY    (set 2026-04-20, used by: latarnik)
   # ANTHROPIC_API_KEY (set 2026-04-20, used by: latarnik)
   ```

### Storage options for v1 (rank ordered)

1. **Plaintext file with strict permissions** — simplest. `/opt/latarnia/{env}/secrets.env`, chmod 600, owned by the latarnia user. Same trust model as the systemd drop-in approach we use today, but centralised and platform-owned. Acceptable for a single-operator Pi.
2. **Plaintext file + age/sops encryption** — operator's key encrypts at rest; platform decrypts at start with a key the operator provides via `loginctl linger` or env. Slight complexity bump, real defence-in-depth.
3. **OS keychain / `pass` / `gpg-agent`** — strongest local option, requires interactive unlock, doesn't survive reboots without operator presence. Probably over-scope for v1.
4. **External vault (HashiCorp / Bitwarden / 1Password)** — overkill for a Pi single-operator deploy.

I'd lean toward (1) for v1 with a documented migration path to (2). v1 does not need rotation tooling beyond "edit the file, restart the apps."

### Validation

If `latarnia.json` declares `requires_secrets: [X, Y]` and any of those values are not set in the per-env store, Latarnia should **refuse to start the app** with a clear error in the dashboard (e.g. `latarnik (tst): missing required secret VOYAGE_API_KEY — run 'latarnia secrets set --env tst VOYAGE_API_KEY=...'`). Failing fast is better than starting a broken app whose `_require_secrets()` exits with a cryptic stderr line buried in journald.

---

## Boundaries

### IN scope (v1)

- `config.requires_secrets: string[]` becomes a documented, validated manifest field.
- Per-env secret store with set/list operations and scoped injection at app launch.
- Refuse-to-start when a declared secret is missing; surface in the dashboard.
- One secret name can be consumed by multiple apps (e.g. several apps share an `ANTHROPIC_API_KEY`); set once, all consumers see it.
- Secrets injected into the launched app's environment ONLY — not the platform's, not other apps'.
- Logs MUST NOT echo secret values during inject or restart.

### OUT of scope (defer to v2)

- Encryption at rest (operator can layer disk encryption today).
- Audit log of who set / read which secret when.
- Per-secret access policies ("only app X may read secret Y" — v1 trusts manifest declaration).
- Secret rotation automation / expiry alerts.
- Web UI for setting secrets — CLI / file only in v1.
- Sharing secrets across `tst` and `prd` (intentionally disallowed; force per-env values).
- Multi-operator workflows (single-user model in v1).

### Cut list (drop in this order if scope shrinks)

1. **Refuse-to-start enforcement** — degrade to "warn in logs" (apps already validate themselves).
2. **CLI tooling** — degrade to "edit a documented file format directly."
3. **Multiple consumers per secret** — require duplicate values per app for v1.

---

## Risks & rabbit holes

- **Secret leakage via `journalctl`** — every "starting app X with environment Y" log line is a footgun. Latarnia's launch path needs a code-review pass to ensure no `log.info(env)` or `log.debug(systemd_unit_text)` leaks the injected values. Test plan should include `grep -r VOYAGE_API_KEY /var/log` against a deployed instance.
- **Secret leakage via `/proc/PID/environ`** — by default, on Linux a process's environment is readable by other processes running as the same user. On a single-user Pi this is fine; if multi-tenant matters later, the platform needs to launch each app under a separate UID.
- **systemd drop-in vs. native env merge** — implementing injection as systemd drop-in files written at launch time is straightforward, but adds inode churn and a `systemctl --user daemon-reload` cost on every restart. A cleaner alternative: load secrets in a Latarnia-side launcher and `os.execvpe` the app with the merged environment, bypassing the unit file entirely. Worth a feasibility check.
- **Manifest field naming collision** — the existing `requires_secrets` field has been silently accepted as no-op. v1 must NOT break apps that declared it without the platform validating it. Either the platform starts validating it (apps may fail to start where they used to silently start broken), or the platform documents the field and starts injecting. The latter is the right call but it's a behavioural change.
- **What if the operator's secret value contains `$` or `=` or newlines?** — choose a file format that escapes correctly. `.env` style is fine if you're disciplined; `tomli` or `json` is more robust.
- **Reboot ordering** — secrets must be available before any auto-start app launches. If the secret store is decrypted on operator login, apps that auto-start at boot won't see them. Decide whether secrets live in always-decrypted state (file with 600 perms) or operator-unlocked state.

---

## Open questions for the spec assistant

1. **CLI surface vs. file format** — does Latarnia already have a CLI binary (`latarnia ...`)? If so, `latarnia secrets ...` subcommands fit naturally. If not, do we want to introduce one for this, or just document a file format the operator edits with `$EDITOR`?
2. **Is there an existing Latarnia config dir convention for per-env config?** — `/etc/latarnia/{env}/`, `/opt/latarnia/{env}/config/`, etc. The secret store should live next to other per-env config.
3. **Should Latarnia inject `LATARNIA_*` env vars** (`LATARNIA_APP_NAME`, `LATARNIA_APP_VERSION`) at the same time? The current spec lists those env vars but it's unclear if they're set today; the secret-injection path is the natural place to add them.
4. **Does the migration runner run before or after secret injection?** — Latarnik's migrations don't need API keys, but a future app might call out during migration (e.g. fetch a remote schema). Probably "before app start" is the right answer, but worth pinning.
5. **What happens on rotation?** — the operator runs `latarnia secrets set ... --env tst VOYAGE_API_KEY=new`. Does Latarnia auto-restart the consuming apps, or just emit "X apps need restart" and leave it to the operator? v1 should probably leave it manual.
6. **Are secrets ever displayed back?** — `latarnia secrets show --env tst VOYAGE_API_KEY` could be useful for debugging but is also a leak vector. v1 should probably refuse to display values, only confirm presence + last-set-at.

---

## What Latarnik needs to do once this ships

Almost nothing — Latarnik already declares `requires_secrets` and validates at startup. Once Latarnia honours the field:

1. Operator runs `latarnia secrets set --env tst VOYAGE_API_KEY=...` and `... ANTHROPIC_API_KEY=...`.
2. Operator deploys Latarnik (`git pull` + restart per the deployment-process skill).
3. Latarnia injects, Latarnik starts, first scrape triggers OCR + categorize successfully.

The only Latarnik-side cleanup is removing the manual systemd drop-in workaround currently documented in `.claude/skills/deployment-process/SKILL.md` step 8. That's a one-line edit.

---

## No-gos

- **Do not** put secrets in `latarnia.json` (committed).
- **Do not** put secrets in app `.env` files inside the repo (gitignored or not — bad pattern).
- **Do not** broadcast secrets via Redis / pubsub for other apps to fetch.
- **Do not** make the secret store world-readable on disk, ever.
- **Do not** echo secret values to stdout/stderr at any point — journald has weeks of retention by default.
- **Do not** require apps to know about Latarnia's secret-store implementation — apps only consume `os.environ`.
