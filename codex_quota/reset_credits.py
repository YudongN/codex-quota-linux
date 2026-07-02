from __future__ import annotations

import json
import math
import time
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Any


class ResetCreditsSchemaError(ValueError):
    pass


@dataclass(frozen=True)
class ResetCredit:
    status: str
    title: str
    granted_at: str
    expires_at: str


@dataclass(frozen=True)
class ResetCreditsSnapshot:
    alias: str
    available_count: int
    credits: list[ResetCredit]
    updated_at: int
    error: str | None = None

    @property
    def is_stale(self) -> bool:
        return self.error is not None


def parse_reset_credits(
    response: dict[str, Any],
    *,
    alias: str,
    now: int | None = None,
) -> ResetCreditsSnapshot:
    available_count = response.get("available_count")
    if not isinstance(available_count, int):
        available_count = response.get("availableCount")
    if not isinstance(available_count, int):
        raise ResetCreditsSchemaError("Backend changed")
    raw_credits = response.get("credits")
    if not isinstance(raw_credits, list):
        raise ResetCreditsSchemaError("Backend changed")
    credits = [_parse_credit(item) for item in raw_credits]
    return ResetCreditsSnapshot(
        alias=alias,
        available_count=max(0, available_count),
        credits=credits,
        updated_at=now or int(time.time()),
    )


def failed_reset_credits_snapshot(
    *,
    alias: str,
    error: str,
    cache_path: Path | None = None,
) -> ResetCreditsSnapshot:
    cached = load_reset_credits_cache(cache_path) if cache_path else None
    if cached:
        return ResetCreditsSnapshot(
            alias=cached.alias,
            available_count=cached.available_count,
            credits=cached.credits,
            updated_at=cached.updated_at,
            error=error,
        )
    return ResetCreditsSnapshot(
        alias=alias,
        available_count=0,
        credits=[],
        updated_at=0,
        error=error,
    )


def save_reset_credits_cache(path: Path, snapshot: ResetCreditsSnapshot) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = asdict(snapshot)
    payload["credits"] = [asdict(credit) for credit in snapshot.credits]
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")


def load_reset_credits_cache(path: Path | None) -> ResetCreditsSnapshot | None:
    if path is None or not path.exists():
        return None
    try:
        payload = json.loads(path.read_text())
        raw_credits = payload.get("credits")
        credits = [
            _parse_credit(item)
            for item in raw_credits
            if isinstance(raw_credits, list) and isinstance(item, dict)
        ]
        return ResetCreditsSnapshot(
            alias=str(payload.get("alias") or "Main"),
            available_count=int(payload.get("available_count") or 0),
            credits=credits,
            updated_at=int(payload.get("updated_at") or 0),
            error=payload.get("error") if isinstance(payload.get("error"), str) else None,
        )
    except Exception:
        return None


def reset_credits_cache_is_fresh(
    snapshot: ResetCreditsSnapshot | None,
    *,
    now: int | None = None,
    ttl_seconds: int,
) -> bool:
    if snapshot is None or snapshot.error or snapshot.updated_at <= 0:
        return False
    current = now if now is not None else int(time.time())
    return current - snapshot.updated_at < ttl_seconds


def reset_credits_table_rows(
    snapshots: list[ResetCreditsSnapshot],
    *,
    now: int | None = None,
) -> list[dict[str, str]]:
    del now
    rows: list[dict[str, str]] = []
    for snapshot in snapshots:
        if snapshot.error and not snapshot.credits:
            rows.append(
                {
                    "alias": snapshot.alias,
                    "available_count": str(snapshot.available_count),
                    "status": _short_error(snapshot.error),
                    "title": "",
                    "granted_at": "",
                    "expires_at": "",
                }
            )
            continue
        for credit in snapshot.credits:
            rows.append(
                {
                    "alias": snapshot.alias,
                    "available_count": str(snapshot.available_count),
                    "status": credit.status,
                    "title": credit.title,
                    "granted_at": _format_datetime(credit.granted_at),
                    "expires_at": _format_datetime(credit.expires_at),
                }
            )
        if not snapshot.credits:
            rows.append(
                {
                    "alias": snapshot.alias,
                    "available_count": str(snapshot.available_count),
                    "status": "none",
                    "title": "",
                    "granted_at": "",
                    "expires_at": "",
                }
            )
    return sorted(rows, key=_row_sort_key)


def format_reset_credits_menu_line(
    snapshot: ResetCreditsSnapshot | None,
    *,
    now: int | None = None,
) -> str:
    if snapshot is None:
        return "Resets unknown"
    actionable = _actionable_error_line(snapshot.error)
    if actionable:
        return f"Resets {actionable}"
    if snapshot.error:
        if snapshot.available_count > 0:
            return f"Resets {snapshot.available_count} · stale"
        return "Resets stale"
    suffix = _next_expiry_suffix(snapshot, now=now)
    if suffix:
        return f"Resets {snapshot.available_count} · {suffix}"
    return f"Resets {snapshot.available_count}"


def _parse_credit(item: Any) -> ResetCredit:
    if not isinstance(item, dict):
        raise ResetCreditsSchemaError("Backend changed")
    status = item.get("status")
    title = item.get("title")
    granted_at = item.get("granted_at")
    expires_at = item.get("expires_at")
    if not all(isinstance(value, str) for value in (status, title, granted_at, expires_at)):
        raise ResetCreditsSchemaError("Backend changed")
    return ResetCredit(
        status=status,
        title=title,
        granted_at=granted_at,
        expires_at=expires_at,
    )


def _next_expiry_suffix(
    snapshot: ResetCreditsSnapshot,
    *,
    now: int | None,
) -> str | None:
    expiries = [
        timestamp
        for timestamp in (_timestamp(credit.expires_at) for credit in snapshot.credits)
        if timestamp is not None
    ]
    if not expiries:
        return None
    current = now if now is not None else int(time.time())
    seconds = min(expiries) - current
    if seconds <= 0:
        return "expires now"
    days = max(1, math.ceil(seconds / 86400))
    if days <= 60:
        return f"expires in {days}d"
    expiry = datetime.fromtimestamp(min(expiries)).astimezone()
    return f"expires {expiry.strftime('%b')} {expiry.day}"


def _actionable_error_line(error: str | None) -> str | None:
    if not error:
        return None
    normalized = error.lower()
    if "backend changed" in normalized:
        return "Backend changed"
    if any(
        needle in normalized
        for needle in (
            "auth",
            "token",
            "unauthorized",
            "forbidden",
        )
    ):
        return "Auth needed"
    return None


def _short_error(error: str) -> str:
    return _actionable_error_line(error) or "stale"


def _format_datetime(value: str) -> str:
    timestamp = _timestamp(value)
    if timestamp is None:
        return value
    return datetime.fromtimestamp(timestamp).astimezone().strftime("%Y-%m-%d %H:%M")


def _timestamp(value: str) -> int | None:
    try:
        return int(datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp())
    except ValueError:
        return None


def _row_sort_key(row: dict[str, str]) -> tuple[int, str, str]:
    timestamp = _timestamp(row["expires_at"])
    if timestamp is None:
        return (2, row["alias"].lower(), row["title"].lower())
    return (0, f"{timestamp:020d}", row["alias"].lower())
