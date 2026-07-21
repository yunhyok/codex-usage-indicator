from __future__ import annotations

import json

from codex_usage_indicator.models import snapshot_from_result
from codex_usage_indicator.storage import load_snapshot, save_snapshot


def test_atomic_cache_round_trip(monkeypatch, tmp_path):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    snapshot = snapshot_from_result(
        {"rateLimits": {"limitId": "codex", "primary": {"usedPercent": 5}}},
        fetched_at=123.5,
    )
    save_snapshot(snapshot)
    assert load_snapshot() == snapshot
    raw = next(tmp_path.rglob("state.json")).read_text(encoding="utf-8")
    payload = json.loads(raw)
    assert set(payload) == {"schemaVersion", "fetchedAt", "buckets"}


def test_corrupt_cache_is_ignored(monkeypatch, tmp_path):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    target = tmp_path / "Codex Usage Indicator" / "state.json"
    target.parent.mkdir(parents=True)
    target.write_text("{broken", encoding="utf-8")
    assert load_snapshot() is None


def test_semantically_invalid_reset_timestamp_is_ignored(monkeypatch, tmp_path):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    target = tmp_path / "Codex Usage Indicator" / "state.json"
    target.parent.mkdir(parents=True)
    target.write_text(
        '{"schemaVersion":1,"fetchedAt":123,"buckets":[{"limitId":"codex",'
        '"primary":{"usedPercent":5,"resetsAt":999999999999999999999}}]}',
        encoding="utf-8",
    )
    assert load_snapshot() is None
