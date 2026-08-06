from __future__ import annotations

import time
import os
from pathlib import Path
import subprocess
import sys
from unittest.mock import patch

import pytest
from PySide6.QtNetwork import QLocalServer

from codex_usage_indicator.app import (
    AlreadyRunningError,
    DetailsDialog,
    SINGLE_INSTANCE_NAME,
    SingleInstance,
    _credits_text,
    _format_credit_balance,
    build_tooltip,
)
from codex_usage_indicator.constants import DISPLAY_NAME, TOOLTIP_MAX_CHARS
from codex_usage_indicator.icon import IconStatus
from codex_usage_indicator.models import CreditsSnapshot, snapshot_from_result


def make_snapshot(credits=None, fetched_at=100):
    rate_limits = {
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
    if credits is not None:
        rate_limits["credits"] = credits
    return snapshot_from_result({"rateLimits": rate_limits}, fetched_at=fetched_at)


def test_tooltip_has_version_and_both_ring_values():
    tooltip = build_tooltip(make_snapshot(), IconStatus.LIVE)
    assert DISPLAY_NAME in tooltip
    assert "외부 7일 남음 75%" in tooltip
    assert "내부 5시간 남음 40%" in tooltip
    assert len(tooltip) <= TOOLTIP_MAX_CHARS


def test_tooltip_prominently_reports_additional_credit_balance():
    tooltip = build_tooltip(
        make_snapshot({"hasCredits": True, "unlimited": False, "balance": "12.5000"}),
        IconStatus.LIVE,
    )
    assert tooltip.splitlines()[1] == "추가 크레딧 잔액: 13 크레딧"
    assert "외부 7일 남음 75%" in tooltip
    assert "내부 5시간 남음 40%" in tooltip
    assert len(tooltip) <= TOOLTIP_MAX_CHARS


@pytest.mark.parametrize(
    ("credits", "expected"),
    [
        (None, "추가 크레딧 잔액: 정보 없음"),
        (CreditsSnapshot(has_credits=False, unlimited=True), "추가 크레딧 잔액: 무제한"),
        (
            CreditsSnapshot(has_credits=True, unlimited=False),
            "추가 크레딧 잔액: 사용 가능 (잔액 미상)",
        ),
        (
            CreditsSnapshot(has_credits=False, unlimited=False, balance="0"),
            "추가 크레딧 잔액: 없음",
        ),
    ],
)
def test_credits_text_preserves_credit_states(credits, expected):
    assert _credits_text(credits) == expected


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("12", "12"),
        ("12.4900", "12"),
        ("00012.5000", "13"),
        ("1234.9000", "1,235"),
        ("0.49", "<1"),
        ("0", "0"),
        ("1e3", "1,000"),
        ("1e999999", None),
        ("9" * 65, None),
        ("not-a-number", None),
        (None, None),
    ],
)
def test_credit_balance_matches_codex_whole_credit_display(raw, expected):
    assert _format_credit_balance(raw) == expected


def test_details_dialog_exposes_purchased_credit_balance_separately():
    class LabelStub:
        def __init__(self):
            self.value = ""

        def setText(self, value):  # noqa: N802 - Qt-compatible stub
            self.value = value

    class TableStub:
        def setRowCount(self, _value):  # noqa: N802 - Qt-compatible stub
            pass

    class DialogStub:
        state_label = LabelStub()
        credits_label = LabelStub()
        meta_label = LabelStub()
        table = TableStub()

        @staticmethod
        def _add_bucket_window(*_args):
            pass

    dialog = DialogStub()
    DetailsDialog.update_snapshot(
        dialog,
        make_snapshot(
            {"hasCredits": True, "unlimited": False, "balance": "12.5000"},
            fetched_at=1_700_000_000,
        ),
        IconStatus.LIVE,
        "사용량을 정상적으로 갱신했습니다.",
    )
    assert dialog.credits_label.value == "추가 크레딧 잔액: 13 크레딧"
    assert "추가 크레딧" not in dialog.meta_label.value


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
        source_root = Path(__file__).resolve().parents[1] / "src"
        sender = subprocess.Popen(
            [
                sys.executable,
                "-c",
                (
                    "import sys; sys.path.insert(0, sys.argv[2]); "
                    "from codex_usage_indicator.app import SingleInstance; "
                    "raise SystemExit(0 if SingleInstance.notify_existing('quit', sys.argv[1]) else 1)"
                ),
                server_name,
                str(source_root),
            ]
        )
        deadline = time.time() + 5
        while time.time() < deadline and (not commands or sender.poll() is None):
            qapp.processEvents()
            time.sleep(0.01)
        assert sender.wait(timeout=2) == 0
        assert commands == ["quit"]
        with patch.object(SingleInstance, "notify_existing", return_value=True):
            with pytest.raises(AlreadyRunningError):
                SingleInstance(lock_path=lock_path, server_name=server_name)
    finally:
        # Let the server-side socket deliver `disconnected` and delete itself
        # while its SingleInstance parent is still alive. Processing that
        # deferred delete after the parent is destroyed can crash PySide on
        # Windows during pytest-qt teardown.
        qapp.processEvents()
        instance.close()
        qapp.processEvents()
        QLocalServer.removeServer(server_name)
