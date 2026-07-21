from __future__ import annotations

from pathlib import Path
import os
import sys

APP_NAME = "Codex Usage Indicator"
APP_VERSION = "0.1.0"
DISPLAY_NAME = f"{APP_NAME} v{APP_VERSION}"
ORGANIZATION_NAME = "CodexUsageIndicator"
POLL_INTERVAL_SECONDS = 60.0
STARTUP_TIMEOUT_SECONDS = 10.0
REQUEST_TIMEOUT_SECONDS = 15.0
STALE_AFTER_SECONDS = 120.0
TOOLTIP_MAX_CHARS = 127


def app_data_dir() -> Path:
    base = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
    return base / APP_NAME


def resource_path(relative: str) -> Path:
    bundle = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parents[2]))
    return bundle / relative
