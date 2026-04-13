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
5. Restart the service
6. Run smoke tests against the deployed instance
7. Log the deployment in `DEPLOYMENTS.md`
