# HomeHelper — Project Instructions

## Project Context

HomeHelper is a home automation platform running on a Raspberry Pi (aarch64). It uses a Python backend with Redis for messaging, and a web UI for managing devices and services.

## Gotchas

### Python dependencies must use version ranges for Pi deployment
Use `>=x.y.z,<x+1` ranges instead of exact pins in `requirements.txt`. Exact pins often lack pre-built wheels for Python 3.13 on aarch64, causing source builds to fail (e.g., `pydantic-core` breaks due to `ForwardRef._evaluate()` changes in Python 3.13).

### SSH host key changes after a fresh Pi OS install
If the Pi's IP was previously known, SSH will refuse with "REMOTE HOST IDENTIFICATION HAS CHANGED". Fix: `ssh-keygen -R <ip>` before reconnecting.
