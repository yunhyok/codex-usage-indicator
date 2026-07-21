from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys
import winreg

from .constants import APP_NAME

RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"


def quote_windows_argument(value: str) -> str:
    return subprocess.list2cmdline([value])


def autostart_command() -> str:
    if getattr(sys, "frozen", False):
        return quote_windows_argument(str(Path(sys.executable).resolve()))
    pythonw = Path(sys.executable).with_name("pythonw.exe")
    interpreter = pythonw if pythonw.exists() else Path(sys.executable)
    return f"{quote_windows_argument(str(interpreter.resolve()))} -m codex_usage_indicator"


def is_autostart_enabled() -> bool:
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as key:
            value, _ = winreg.QueryValueEx(key, APP_NAME)
        return bool(value)
    except FileNotFoundError:
        return False
    except OSError:
        return False


def set_autostart_enabled(enabled: bool) -> None:
    if enabled:
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as key:
            winreg.SetValueEx(key, APP_NAME, 0, winreg.REG_SZ, autostart_command())
        return
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE) as key:
            winreg.DeleteValue(key, APP_NAME)
    except FileNotFoundError:
        return


def open_folder(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)
    os.startfile(str(path))  # type: ignore[attr-defined]
