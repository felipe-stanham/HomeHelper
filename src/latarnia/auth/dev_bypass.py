"""Dev-only TOTP bypass gate (T-0010).

Lets browser test automation (Playwright) get past `/auth/login` without a real
TOTP code. Two independent conditions must both hold:

1. ENV is exactly ``dev``.
2. The ``LATARNIA_DEV_TOTP_BYPASS`` secret parses truthy.

Gating on ENV alone was rejected: MEMORY.md ``deploy-needs-host-config-json``
records per-host config going missing on a **prd** host, so config drift here is
demonstrated rather than hypothetical. The second condition is a secret that
exists in no ``tst`` or ``prd`` secrets.env.

This lives in its own module, separate from main.py, so the gate is unit-testable
without importing main's module-level manager construction. A security control
that cannot be tested is not a control.

**Why this does NOT use ConfigManager.get_env().** That helper is deliberately
lenient — anything outside `{dev, tst, prd}` falls back to `"dev"`, and so does an
unset ENV (`core/config.py:170-171`). Correct for choosing a DB name; catastrophic
here, because it makes condition 1 *fail-open*: `ENV="PRD "` with a stray trailing
space, `ENV=production`, or a missing `ENV=` line all resolve to `"dev"` and would
satisfy the gate on a production host. This module therefore reads the **raw** ENV
value and demands the exact three characters `dev` — no case folding, no
whitespace tolerance, no default. A dev box with a typo simply loses the bypass,
which is the harmless direction to fail.
"""
from __future__ import annotations

from typing import Callable, Optional

DEV_TOTP_BYPASS_SECRET = "LATARNIA_DEV_TOTP_BYPASS"

# The one and only ENV value that permits a bypass. Compared exactly.
_DEV_ENV_EXACT = "dev"

_TRUTHY = {"1", "true", "yes", "on"}


def is_truthy(raw) -> bool:
    """Parse a secrets.env value as a boolean. Anything unrecognised is False."""
    return str(raw or "").strip().lower() in _TRUTHY


def dev_totp_bypass_enabled(
    raw_env_getter: Callable[[], Optional[str]],
    secret_loader: Callable[[str], Optional[str]],
) -> bool:
    """True only when ENV is exactly `dev` AND the opt-in secret is set.

    `raw_env_getter` must return the **unprocessed** ENV value (typically
    `os.environ.get("ENV")`) — not `ConfigManager.get_env()`, whose fallback would
    make this fail open. See the module docstring.

    ENV is checked first, so `tst`/`prd` cost one string comparison and never
    touch secrets.env on the login path.
    """
    if raw_env_getter() != _DEV_ENV_EXACT:
        return False
    return is_truthy(secret_loader(DEV_TOTP_BYPASS_SECRET))
