"""
Launcher routing for service-app lifecycle requests (P-0005 flow-02).

Decides per-app which launcher (`ServiceManager`, `SubprocessLauncher`, or
`StreamlitManager`) handles a start/stop/restart. Routing is by
(`platform.system()`, `manifest.type`):

  - streamlit type           → StreamlitManager (subprocess + TTL)
  - service type + Linux     → ServiceManager   (systemctl --user)
  - service type + Darwin    → SubprocessLauncher (Popen fork)

Service-typed launchers (`ServiceManager` / `SubprocessLauncher`) expose the
same verbs (`start_service`, `stop_service`, `restart_service`) so callers
can dispatch uniformly. `StreamlitManager` is returned for completeness, but
the platform's auto-start loop and `/api/apps/{id}/process/*` endpoints
filter to service-typed apps before invoking pick_launcher.
"""
import platform


def pick_launcher(app_entry, service_manager, subprocess_launcher, streamlit_manager):
    """Pick the launcher that should handle lifecycle requests for `app_entry`."""
    if app_entry.type == "streamlit":
        return streamlit_manager
    if platform.system() == "Linux":
        return service_manager
    return subprocess_launcher
