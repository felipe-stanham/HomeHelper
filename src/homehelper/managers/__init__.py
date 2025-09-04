"""
HomeHelper Managers Package

This package contains the core management components for HomeHelper:
- App Manager: Application discovery and lifecycle management
- Service Manager: systemd integration for background services
- UI Manager: On-demand Streamlit application management
"""

from .app_manager import AppManager, AppRegistry
from .port_manager import PortManager

__all__ = [
    "AppManager",
    "AppRegistry", 
    "PortManager"
]
