from __future__ import annotations

import pytest

from codex_usage_indicator.models import (
    RateLimitWindow,
    UsagePayloadError,
    UsageSnapshot,
    format_duration,
    snapshot_from_notification,
    snapshot_from_result,
)


def bucket_payload(limit_id="codex", used=25, secondary=None):
    return {
        "limitId": limit_id,
        "limitName": None,
        "primary": {
            "usedPercent": used,
            "windowDurationMins": 10080,
            "resetsAt": 1_800_000_000,
        },
        "secondary": secondary,
        "credits": {"hasCredits": False, "unlimited": False, "balance": "0"},
        "planType": "prolite",
        "rateLimitReachedType": None,
    }


def test_remaining_is_clamped():
    assert RateLimitWindow.from_payload({"usedPercent": -5}).remaining_percent == 100
    assert RateLimitWindow.from_payload({"usedPercent": 130}).remaining_percent == 0


@pytest.mark.parametrize("value", [True, None, 1.5, "not-a-number"])
def test_invalid_used_percent_is_rejected(value):
    with pytest.raises(UsagePayloadError):
        RateLimitWindow.from_payload({"usedPercent": value})


def test_root_only_payload_uses_codex_bucket():
    snapshot = snapshot_from_result({"rateLimits": bucket_payload()}, fetched_at=123.0)
    assert [bucket.limit_id for bucket in snapshot.buckets] == ["codex"]
    assert snapshot.icon_bucket.primary.remaining_percent == 75
    assert snapshot.fetched_at == 123.0


def test_multi_bucket_map_deduplicates_root_and_sorts_codex_first():
    result = {
        "rateLimits": bucket_payload("codex", 30),
        "rateLimitsByLimitId": {
            "codex_bengalfox": {
                **bucket_payload(None, 5),
                "limitId": None,
                "limitName": "GPT-5.3-Codex-Spark",
            },
            "codex": bucket_payload("codex", 30),
        },
        "unknownFutureField": {"safe": True},
    }
    snapshot = snapshot_from_result(result)
    assert [bucket.limit_id for bucket in snapshot.buckets] == ["codex", "codex_bengalfox"]


def test_malformed_named_bucket_does_not_drop_valid_bucket():
    result = {
        "rateLimits": bucket_payload("codex", 30),
        "rateLimitsByLimitId": {
            "bad": {"limitId": "bad", "primary": {"usedPercent": True}},
            "codex": bucket_payload("codex", 30),
        },
    }
    snapshot = snapshot_from_result(result)
    assert [bucket.limit_id for bucket in snapshot.buckets] == ["codex"]


def test_notification_merges_one_bucket_and_preserves_others():
    previous = snapshot_from_result(
        {
            "rateLimits": bucket_payload("codex", 30),
            "rateLimitsByLimitId": {
                "codex": bucket_payload("codex", 30),
                "spark": {**bucket_payload("spark", 5), "limitName": "Spark"},
            },
        },
        fetched_at=10,
    )
    updated = snapshot_from_notification(
        {"rateLimits": bucket_payload("codex", 50)}, previous, fetched_at=20
    )
    assert [bucket.limit_id for bucket in updated.buckets] == ["codex", "spark"]
    assert updated.icon_bucket.primary.used_percent == 50
    assert updated.fetched_at == 20


def test_sparse_notification_preserves_existing_bucket_metadata():
    secondary = {
        "usedPercent": 10,
        "windowDurationMins": 300,
        "resetsAt": 1_800_001_000,
    }
    previous = snapshot_from_result(
        {
            "rateLimits": {
                **bucket_payload("codex", 30, secondary),
                "limitName": "Default Codex",
            }
        },
        fetched_at=10,
    )
    updated = snapshot_from_notification(
        {
            "rateLimits": {
                "limitId": "codex",
                "primary": {"usedPercent": 45},
            }
        },
        previous,
        fetched_at=20,
    )
    bucket = updated.icon_bucket
    assert bucket.primary.used_percent == 45
    assert bucket.primary.window_duration_mins == 10080
    assert bucket.primary.resets_at == 1_800_000_000
    assert bucket.secondary.used_percent == 10
    assert bucket.limit_name == "Default Codex"
    assert bucket.plan_type == "prolite"
    assert bucket.credits.balance == "0"


def test_sparse_notification_null_metadata_preserves_credit_balance_and_plan():
    payload = bucket_payload("codex", 30)
    payload["credits"] = {
        "hasCredits": True,
        "unlimited": False,
        "balance": "12.5000",
    }
    payload["planType"] = "pro"
    previous = snapshot_from_result({"rateLimits": payload}, fetched_at=10)

    updated = snapshot_from_notification(
        {
            "rateLimits": {
                "limitId": "codex",
                "primary": {"usedPercent": 45},
                "credits": None,
                "planType": None,
            }
        },
        previous,
        fetched_at=20,
    )

    assert updated.icon_bucket.primary.used_percent == 45
    assert updated.icon_bucket.credits.balance == "12.5000"
    assert updated.icon_bucket.plan_type == "pro"


def test_sparse_notification_can_clear_reached_state():
    payload = bucket_payload("codex", 100)
    payload["rateLimitReachedType"] = "rate_limit_reached"
    previous = snapshot_from_result({"rateLimits": payload}, fetched_at=10)

    updated = snapshot_from_notification(
        {
            "rateLimits": {
                "limitId": "codex",
                "rateLimitReachedType": None,
            }
        },
        previous,
        fetched_at=20,
    )

    assert updated.icon_bucket.reached_type is None


def test_notification_without_limit_id_requests_full_refresh_instead_of_guessing():
    previous = snapshot_from_result({"rateLimits": bucket_payload()})
    payload = bucket_payload()
    payload["limitId"] = None
    with pytest.raises(UsagePayloadError):
        snapshot_from_notification({"rateLimits": payload}, previous)


def test_cache_round_trip_contains_sanitized_usage_only():
    original = snapshot_from_result({"rateLimits": bucket_payload()}, fetched_at=100)
    cache = original.to_cache()
    serialized = str(cache).lower()
    assert "token" not in serialized
    assert "email" not in serialized
    restored = UsageSnapshot.from_cache(cache)
    assert restored == original


@pytest.mark.parametrize("timestamp", [float("inf"), float("nan"), -1, 1e30])
def test_invalid_cache_timestamp_is_rejected(timestamp):
    original = snapshot_from_result({"rateLimits": bucket_payload()}, fetched_at=100)
    cache = original.to_cache()
    cache["fetchedAt"] = timestamp
    with pytest.raises(UsagePayloadError):
        UsageSnapshot.from_cache(cache)


def test_invalid_reset_timestamp_is_rejected():
    with pytest.raises(UsagePayloadError):
        RateLimitWindow.from_payload({"usedPercent": 5, "resetsAt": 10**40})


@pytest.mark.parametrize(
    ("minutes", "expected"),
    [(10080, "7일"), (300, "5시간"), (90, "1시간 30분"), (15, "15분"), (None, "기간 미상")],
)
def test_format_duration(minutes, expected):
    assert format_duration(minutes) == expected
