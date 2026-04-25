"""
Unit tests for launcher_router.pick_launcher (P-0005 cap-003, cap-004).

The router decides which launcher handles a lifecycle request based on
(platform.system(), manifest.type). Logic is intentionally trivial — the
tests exhaustively cover the truth table.
"""
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "src"))

from latarnia.managers.launcher_router import pick_launcher


@pytest.fixture
def launchers():
    return SimpleNamespace(
        service_manager=object(),
        subprocess_launcher=object(),
        streamlit_manager=object(),
    )


def _entry(app_type: str):
    return SimpleNamespace(type=app_type)


@patch("latarnia.managers.launcher_router.platform.system", return_value="Linux")
def test_linux_service_routes_to_service_manager(_sys, launchers):
    target = pick_launcher(
        _entry("service"),
        launchers.service_manager,
        launchers.subprocess_launcher,
        launchers.streamlit_manager,
    )
    assert target is launchers.service_manager


@patch("latarnia.managers.launcher_router.platform.system", return_value="Darwin")
def test_darwin_service_routes_to_subprocess_launcher(_sys, launchers):
    target = pick_launcher(
        _entry("service"),
        launchers.service_manager,
        launchers.subprocess_launcher,
        launchers.streamlit_manager,
    )
    assert target is launchers.subprocess_launcher


@pytest.mark.parametrize("os_name", ["Linux", "Darwin", "Windows"])
def test_streamlit_routes_to_streamlit_manager_regardless_of_os(os_name, launchers):
    with patch("latarnia.managers.launcher_router.platform.system", return_value=os_name):
        target = pick_launcher(
            _entry("streamlit"),
            launchers.service_manager,
            launchers.subprocess_launcher,
            launchers.streamlit_manager,
        )
    assert target is launchers.streamlit_manager
