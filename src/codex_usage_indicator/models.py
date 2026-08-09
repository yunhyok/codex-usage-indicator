from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime
import math
from typing import Any, Mapping
import time


class UsagePayloadError(ValueError):
    """Raised when an app-server usage payload lacks its required shape."""


def _optional_int(value: Any) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool):
        raise UsagePayloadError("boolean is not a valid integer")
    if isinstance(value, float) and not value.is_integer():
        raise UsagePayloadError(f"non-integral value: {value!r}")
    try:
        return int(value)
    except (TypeError, ValueError) as exc:
        raise UsagePayloadError(f"invalid integer value: {value!r}") from exc


def _optional_timestamp(value: Any) -> int | None:
    timestamp = _optional_int(value)
    if timestamp is not None and not 0 <= timestamp <= 32_503_680_000:
        raise UsagePayloadError("timestamp is outside the supported range")
    return timestamp


@dataclass(frozen=True, slots=True)
class RateLimitWindow:
    used_percent: int
    resets_at: int | None = None
    window_duration_mins: int | None = None

    @property
    def remaining_percent(self) -> int:
        return max(0, min(100, 100 - self.used_percent))

    @classmethod
    def from_payload(cls, payload: Mapping[str, Any] | None) -> "RateLimitWindow | None":
        if payload is None:
            return None
        if not isinstance(payload, Mapping) or "usedPercent" not in payload:
            raise UsagePayloadError("rate-limit window requires usedPercent")
        used = _optional_int(payload.get("usedPercent"))
        if used is None:
            raise UsagePayloadError("usedPercent cannot be null")
        return cls(
            used_percent=max(0, min(100, used)),
            resets_at=_optional_timestamp(payload.get("resetsAt")),
            window_duration_mins=_optional_int(payload.get("windowDurationMins")),
        )

    def to_cache(self) -> dict[str, int | None]:
        return {
            "usedPercent": self.used_percent,
            "resetsAt": self.resets_at,
            "windowDurationMins": self.window_duration_mins,
        }


@dataclass(frozen=True, slots=True)
class CreditsSnapshot:
    has_credits: bool
    unlimited: bool
    balance: str | None = None

    @classmethod
    def from_payload(cls, payload: Mapping[str, Any] | None) -> "CreditsSnapshot | None":
        if payload is None:
            return None
        if not isinstance(payload, Mapping):
            raise UsagePayloadError("credits must be an object or null")
        return cls(
            has_credits=bool(payload.get("hasCredits", False)),
            unlimited=bool(payload.get("unlimited", False)),
            balance=None if payload.get("balance") is None else str(payload.get("balance")),
        )

    def to_cache(self) -> dict[str, bool | str | None]:
        return {
            "hasCredits": self.has_credits,
            "unlimited": self.unlimited,
            "balance": self.balance,
        }


@dataclass(frozen=True, slots=True)
class RateLimitBucket:
    limit_id: str
    limit_name: str | None
    plan_type: str | None
    primary: RateLimitWindow | None
    secondary: RateLimitWindow | None
    credits: CreditsSnapshot | None
    reached_type: str | None

    @property
    def display_name(self) -> str:
        if self.limit_id == "codex" and not self.limit_name:
            return "Codex"
        return self.limit_name or self.limit_id

    @classmethod
    def from_payload(
        cls, payload: Mapping[str, Any], fallback_limit_id: str = "codex"
    ) -> "RateLimitBucket":
        if not isinstance(payload, Mapping):
            raise UsagePayloadError("rate-limit bucket must be an object")
        limit_id = str(payload.get("limitId") or fallback_limit_id)
        return cls(
            limit_id=limit_id,
            limit_name=None if payload.get("limitName") is None else str(payload.get("limitName")),
            plan_type=None if payload.get("planType") is None else str(payload.get("planType")),
            primary=RateLimitWindow.from_payload(payload.get("primary")),
            secondary=RateLimitWindow.from_payload(payload.get("secondary")),
            credits=CreditsSnapshot.from_payload(payload.get("credits")),
            reached_type=(
                None
                if payload.get("rateLimitReachedType") is None
                else str(payload.get("rateLimitReachedType"))
            ),
        )

    def to_cache(self) -> dict[str, Any]:
        return {
            "limitId": self.limit_id,
            "limitName": self.limit_name,
            "planType": self.plan_type,
            "primary": None if self.primary is None else self.primary.to_cache(),
            "secondary": None if self.secondary is None else self.secondary.to_cache(),
            "credits": None if self.credits is None else self.credits.to_cache(),
            "rateLimitReachedType": self.reached_type,
        }


@dataclass(frozen=True, slots=True)
class UsageSnapshot:
    buckets: tuple[RateLimitBucket, ...]
    fetched_at: float

    @property
    def icon_bucket(self) -> RateLimitBucket | None:
        for bucket in self.buckets:
            if bucket.limit_id == "codex":
                return bucket
        return self.buckets[0] if self.buckets else None

    def with_bucket(self, updated: RateLimitBucket, fetched_at: float | None = None) -> "UsageSnapshot":
        found = False
        buckets: list[RateLimitBucket] = []
        for bucket in self.buckets:
            if bucket.limit_id == updated.limit_id:
                buckets.append(updated)
                found = True
            else:
                buckets.append(bucket)
        if not found:
            buckets.append(updated)
        return replace(
            self,
            buckets=_sort_buckets(buckets),
            fetched_at=time.time() if fetched_at is None else fetched_at,
        )

    def to_cache(self) -> dict[str, Any]:
        return {
            "schemaVersion": 1,
            "fetchedAt": self.fetched_at,
            "buckets": [bucket.to_cache() for bucket in self.buckets],
        }

    @classmethod
    def from_cache(cls, payload: Mapping[str, Any]) -> "UsageSnapshot":
        if payload.get("schemaVersion") != 1:
            raise UsagePayloadError("unsupported cache schema")
        buckets_raw = payload.get("buckets")
        if not isinstance(buckets_raw, list):
            raise UsagePayloadError("cache buckets must be a list")
        buckets = [RateLimitBucket.from_payload(item) for item in buckets_raw]
        fetched_at_raw = payload.get("fetchedAt")
        if isinstance(fetched_at_raw, bool):
            raise UsagePayloadError("invalid cache timestamp")
        try:
            fetched_at = float(fetched_at_raw)
        except (TypeError, ValueError) as exc:
            raise UsagePayloadError("invalid cache timestamp") from exc
        if not math.isfinite(fetched_at) or not 0 <= fetched_at <= 32_503_680_000:
            raise UsagePayloadError("cache timestamp is outside the supported range")
        return cls(buckets=_sort_buckets(buckets), fetched_at=fetched_at)


def _sort_buckets(buckets: list[RateLimitBucket]) -> tuple[RateLimitBucket, ...]:
    unique: dict[str, RateLimitBucket] = {bucket.limit_id: bucket for bucket in buckets}
    return tuple(
        sorted(
            unique.values(),
            key=lambda b: (b.limit_id != "codex", b.display_name.casefold(), b.limit_id.casefold()),
        )
    )


def snapshot_from_result(result: Mapping[str, Any], fetched_at: float | None = None) -> UsageSnapshot:
    if not isinstance(result, Mapping):
        raise UsagePayloadError("rate-limit result must be an object")
    buckets: list[RateLimitBucket] = []
    by_id = result.get("rateLimitsByLimitId")
    if isinstance(by_id, Mapping):
        for limit_id, payload in by_id.items():
            if isinstance(payload, Mapping):
                try:
                    effective_payload = dict(payload)
                    effective_payload["limitId"] = str(limit_id)
                    buckets.append(RateLimitBucket.from_payload(effective_payload, str(limit_id)))
                except UsagePayloadError:
                    continue
    base = result.get("rateLimits")
    if isinstance(base, Mapping):
        try:
            base_bucket = RateLimitBucket.from_payload(base, "codex")
        except UsagePayloadError:
            base_bucket = None
        if base_bucket and not any(bucket.limit_id == base_bucket.limit_id for bucket in buckets):
            buckets.append(base_bucket)
    if not buckets:
        raise UsagePayloadError("rate-limit result contains no usable buckets")
    return UsageSnapshot(
        buckets=_sort_buckets(buckets),
        fetched_at=time.time() if fetched_at is None else fetched_at,
    )


def snapshot_from_notification(
    params: Mapping[str, Any], previous: UsageSnapshot | None, fetched_at: float | None = None
) -> UsageSnapshot:
    raw = params.get("rateLimits") if isinstance(params, Mapping) else None
    if not isinstance(raw, Mapping):
        raise UsagePayloadError("rate-limit notification has no rateLimits object")
    if not raw.get("limitId"):
        raise UsagePayloadError("rate-limit notification has no limitId")
    limit_id = str(raw.get("limitId"))
    existing = None
    if previous is not None:
        existing = next((bucket for bucket in previous.buckets if bucket.limit_id == limit_id), None)
    if existing is None:
        bucket = RateLimitBucket.from_payload(raw)
    else:
        merged = existing.to_cache()
        for key in ("limitName", "rateLimitReachedType"):
            if key in raw:
                merged[key] = raw[key]
        # App Server rolling notifications are sparse. Nullable account
        # metadata can be unavailable in an update and must not erase the last
        # value from account/rateLimits/read.
        for key in ("planType", "credits"):
            if raw.get(key) is not None:
                merged[key] = raw[key]
        for key in ("primary", "secondary"):
            if key not in raw:
                continue
            incoming_window = raw[key]
            existing_window = merged.get(key)
            if isinstance(incoming_window, Mapping) and isinstance(existing_window, Mapping):
                combined_window = dict(existing_window)
                combined_window.update(incoming_window)
                merged[key] = combined_window
            else:
                merged[key] = incoming_window
        merged["limitId"] = limit_id
        bucket = RateLimitBucket.from_payload(merged)
    timestamp = time.time() if fetched_at is None else fetched_at
    if previous is None:
        return UsageSnapshot(buckets=(bucket,), fetched_at=timestamp)
    return previous.with_bucket(bucket, timestamp)


def format_duration(minutes: int | None) -> str:
    if minutes is None:
        return "기간 미상"
    if minutes % 1440 == 0:
        return f"{minutes // 1440}일"
    if minutes % 60 == 0:
        return f"{minutes // 60}시간"
    if minutes >= 60:
        hours, mins = divmod(minutes, 60)
        return f"{hours}시간 {mins}분"
    return f"{minutes}분"


def format_reset(timestamp: int | None, compact: bool = False) -> str:
    if timestamp is None:
        return "미정"
    try:
        dt = datetime.fromtimestamp(timestamp).astimezone()
    except (OSError, OverflowError, ValueError):
        return "유효하지 않음"
    return dt.strftime("%m/%d %H:%M" if compact else "%Y-%m-%d %H:%M:%S")
