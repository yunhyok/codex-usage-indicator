from __future__ import annotations

import time
import threading
import os

import pytest
from PySide6.QtNetwork import QLocalServer

from codex_usage_indicator.app import (
    AlreadyRunningError,
    SINGLE_INSTANCE_NAME,
    SingleInstance,
    build_tooltip,
)
from codex_usage_indicator.constants import DISPLAY_NAME, TOOLTIP_MAX_CHARS
from codex_usage_indicator.icon import IconStatus
from codex_usage_indicator.models import snapshot_from_result


def make_snapshot():
    return snapshot_from_result(
        {
            "rateLimits": {
                "limitId": "codex",
                "primary": {
                    "usedPercent": 25,
                    "windowDurationMins": 10080,
                    "resetsAt": 1_800_000_000,
                },
                "secondary": {
                    "usedPercent": 60,
                    "windowDurationMins": 300,
                    "resetsAt": 1_800_010_000,
                },
            }
        },
        fetched_at=100,
    )


def test_tooltip_has_version_and_both_ring_values():
    tooltip = build_tooltip(make_snapshot(), IconStatus.LIVE)
    assert DISPLAY_NAME in tooltip
    assert "외부 7일 남음 75%" in tooltip
    assert "내부 5시간 남음 40%" in tooltip
    assert len(tooltip) <= TOOLTIP_MAX_CHARS


def test_stale_tooltip_keeps_exact_values_and_marks_age():
    tooltip = build_tooltip(make_snapshot(), IconStatus.STALE, now=220)
    assert "남음 75%" in tooltip
    assert "오래된 값" in tooltip


def test_unknown_tooltip_reports_detail():
    tooltip = build_tooltip(None, IconStatus.ERROR, "Codex CLI를 찾을 수 없습니다.")
    assert "Codex CLI" in tooltip


def test_single_instance_notifies_and_rejects_second_listener(qapp, tmp_path):
    server_name = f"{SINGLE_INSTANCE_NAME}-pytest-{os.getpid()}"
    QLocalServer.removeServer(server_name)
    commands = []
    lock_path = tmp_path / "instance.lock"
    instance = SingleInstance(
        lambda: commands.append("show"),
        lambda: commands.append("quit"),
        lock_path=lock_path,
        server_name=server_name,
    )
    try:
        result = []
        sender = threading.Thread(
            target=lambda: result.append(SingleInstance.notify_existing("quit", server_name))
        )
        sender.start()
        deadline = time.time() + 1
        while time.time() < deadline and (not commands or sender.is_alive()):
            qapp.processEvents()
            time.sleep(0.01)
        sender.join(timeout=1)
        assert result == [True]
        assert commands == ["quit"]
        with pytest.raises(AlreadyRunningError):
            SingleInstance(lock_path=lock_path, server_name=server_name)
    finally:
        instance.close()
        QLocalServer.removeServer(server_name)
