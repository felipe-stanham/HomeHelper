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

## Deployment Targets
| Target      | Environments | Description                        |
|-------------|--------------|------------------------------------|
| local       | dev          | Developer workstation              |
| homeserver  | dev, tst, prd| Self-hosted multi-environment      |
| clientA     | prd          | Client A production                |
| clientB     | prd          | Client B production                |
```

---