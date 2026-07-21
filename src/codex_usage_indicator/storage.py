from __future__ import annotations

import json
import logging
from logging.handlers import RotatingFileHandler
import os
from pathlib import Path
import tempfile
from typing import Any

from .constants import APP_NAME, app_data_dir
from .models import UsagePayloadError, UsageSnapshot


def cache_path() -> Path:
    return app_data_dir() / "state.json"


def logs_dir() -> Path:
    return app_data_dir() / "logs"


def configure_logging() -> Path:
    directory = logs_dir()
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / "app.log"
    handler = RotatingFileHandler(
        path, maxBytes=1_000_000, backupCount=3, encoding="utf-8"
    )
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    if not any(isinstance(existing, RotatingFileHandler) for existing in root.handlers):
        root.addHandler(handler)
    logging.getLogger(__name__).info("%s logging started", APP_NAME)
    return path


def load_snapshot() -> UsageSnapshot | None:
    path = cache_path()
    try:
        payload: Any = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            return None
        return UsageSnapshot.from_cache(payload)
    except (OSError, json.JSONDecodeError, UsagePayloadError, ValueError):
        return None


def save_snapshot(snapshot: UsageSnapshot) -> None:
    path = cache_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    handle, temporary_name = tempfile.mkstemp(
        prefix="state-", suffix=".tmp", dir=path.parent, text=True
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(handle, "w", encoding="utf-8", newline="\n") as stream:
            json.dump(snapshot.to_cache(), stream, ensure_ascii=False, separators=(",", ":"))
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink(missing_ok=True)
