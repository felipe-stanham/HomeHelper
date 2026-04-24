---
name: deployment-process
description: Deployment procedure for this project. Contains the step-by-step process, target-specific notes, and a log of procedural changes over time.
---

# Rules

- Before any deployment, read `.deploy-secrets` and verify the target exists.
- **Never deploy to a `prd` target without explicit user confirmation.**
- Warn me if regression tests have not been run before deploying to PRD (see Testing section).
- Deploy to `tst` targets from the `tst` branch; deploy to `prd` targets from `main` only.
- Log every deployment action: target, environment, timestamp, commit hash in `DEPLOYMENTS.md`.
- If `.deploy-secrets` does not exist or is missing a target, stop and ask the user to provide the credentials.
- If adding a new deploy target, use template at `docs/templates/deploy-secrets.template`.


# Procedure
1. Run regression tests (`TESTS.md`) — all must pass
2. Read `.deploy-secrets` for the target
3. SSH to the target, `git pull` the correct branch
4. **DEV/TST only:** Copy example apps to `apps/`:
   ```
   cp -r examples/example_full_app apps/
   cp -r examples/example_companion apps/
   ```
   PRD does **not** deploy example apps — only real apps live in PRD `apps/`.
5. Restart the service. The main platform runs as environment-scoped **system** systemd units on the Pi:
   - TST: `sudo systemctl restart latarnia-tst.service`
   - PRD: `sudo systemctl restart latarnia-prd.service`

   Verify with `systemctl list-units --type=service --all | grep -i latarnia` (no `--user`).

   > **Per-app services are env-scoped** (P-0004). `ServiceManager` reads `ENV` and generates unit names like `latarnia-tst-{app}.service` / `latarnia-prd-{app}.service` so TST and PRD apps don't collide in `~/.config/systemd/user/`. Ensure the relevant `ENV` value is set in the platform's environment (systemd unit `Environment=ENV=tst` for `latarnia-tst.service`, `ENV=prd` for `latarnia-prd.service`).
6. Run smoke tests against the deployed instance
7. Log the deployment in `DEPLOYMENTS.md`

# Service Names (reference)

| Component              | Unit name                                   | Scope           | Restart command                                       |
|------------------------|---------------------------------------------|-----------------|-------------------------------------------------------|
| Main platform (TST)    | `latarnia-tst.service`                      | system          | `sudo systemctl restart latarnia-tst.service`         |
| Main platform (PRD)    | `latarnia-prd.service`                      | system          | `sudo systemctl restart latarnia-prd.service`         |
| Per-app (TST)          | `latarnia-tst-{app_name}.service`           | user (`--user`) | `systemctl --user restart latarnia-tst-{app}.service` |
| Per-app (PRD)          | `latarnia-prd-{app_name}.service`           | user (`--user`) | `systemctl --user restart latarnia-prd-{app}.service` |

# First-Time Bootstrap (fresh Pi)

Use this once per host when bringing up a new homeserver or re-creating the main-platform systemd units. The two main-platform units (`latarnia-tst.service`, `latarnia-prd.service`) are **system-scope** units installed under `/etc/systemd/system/` and run by the `felipe` user, each pointing at its own `DEPLOY_PATH` and `PORT` from `.deploy-secrets`.

## 1. Prerequisites on the Pi
- OS: Raspberry Pi OS (Debian-based)
- Packages: `git`, `python3`, `python3-venv`, `redis-server`, `postgresql`
- Base dirs created as root:
  ```
  sudo mkdir -p /opt/latarnia/tst /opt/latarnia/prd
  sudo chown -R felipe:felipe /opt/latarnia
  ```

## 2. Clone the repo into each env dir
As the `felipe` user:
```
git clone <repo-url> /opt/latarnia/tst && cd /opt/latarnia/tst && git checkout tst
git clone <repo-url> /opt/latarnia/prd && cd /opt/latarnia/prd && git checkout main
```
Create a venv and install deps in each:
```
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
```

## 3. Install the main-platform unit files

> **TODO — paste verified contents from the running Pi here.** Placeholder template below reflects the intended shape; the authoritative unit files live in `/etc/systemd/system/` on the homeserver and must be captured verbatim. Do not bootstrap from this placeholder alone.

`/etc/systemd/system/latarnia-tst.service` (placeholder):
```ini
[Unit]
Description=Latarnia TST Environment
After=network.target redis-server.service postgresql.service
Wants=redis-server.service postgresql.service

[Service]
Type=simple
User=felipe
Group=felipe
WorkingDirectory=/opt/latarnia/tst
Environment=ENV=tst
Environment=PYTHONUNBUFFERED=1
ExecStart=/opt/latarnia/tst/.venv/bin/python -m latarnia.main
Restart=on-failure
RestartSec=5
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
```

`/etc/systemd/system/latarnia-prd.service` (placeholder): same shape with `ENV=prd`, `WorkingDirectory=/opt/latarnia/prd`, and the PRD port.

## 4. Enable and start
```
sudo systemctl daemon-reload
sudo systemctl enable --now latarnia-tst.service
sudo systemctl enable --now latarnia-prd.service
sudo systemctl status latarnia-tst.service latarnia-prd.service
```

## 5. Verify
```
systemctl list-units --type=service --all | grep -i latarnia
curl http://localhost:8000/health   # TST
curl http://localhost:8080/health   # PRD
```
