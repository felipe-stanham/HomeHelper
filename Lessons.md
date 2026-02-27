# Lessons Learned

## Deployment

### Python dependency versions must be flexible for Pi deployment
- **Date**: 2026-02-27
- **Issue**: The original `requirements.txt` had pinned exact versions (e.g., `pydantic==2.5.0`) that didn't have pre-built wheels for Python 3.13 on aarch64 (Raspberry Pi). Building `pydantic-core` from source failed due to `ForwardRef._evaluate()` API changes in Python 3.13.
- **Fix**: Changed to compatible version ranges (e.g., `pydantic>=2.5.0,<3.0.0`) so pip can resolve to the latest version with pre-built aarch64 wheels.
- **Lesson**: Always use version ranges instead of exact pins when targeting multiple platforms (macOS dev + ARM64 Pi production).

### SSH host key changes on fresh OS installs
- **Date**: 2026-02-27
- **Issue**: After a fresh Raspbian install, SSH connection fails with "REMOTE HOST IDENTIFICATION HAS CHANGED" if the Pi's IP was previously known.
- **Fix**: Run `ssh-keygen -R <ip>` to remove the stale host key before connecting.
