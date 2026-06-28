from __future__ import annotations

import json
import time
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Any


CACHE_EXPIRES_AFTER_SECONDS = 10 * 60


@dataclass(frozen=True)
class QuotaWindow:
    key: str
    label: str
    left_percent: int
    reset_at: int | None = None


@dataclass(frozen=True)
class QuotaSnapshot:
    alias: str
    email: str | None
    plan: str | None
    windows: list[QuotaWindow]
    updated_at: int
    error: str | None = None

    @property
    def is_stale(self) -> bool:
        return self.error is not None


def parse_rate_limits(
    response: dict[str, Any],
    *,
    alias: str,
    email: str | None,
    now: int | None = None,
) -> QuotaSnapshot:
    snapshot = _select_codex_snapshot(response)
    windows = _extract_windows(snapshot)
    plan = snapshot.get("planType")
    if not isinstance(plan, str):
        plan = None
    return QuotaSnapshot(
        alias=alias,
        email=email,
        plan=plan,
        windows=windows,
        updated_at=now or int(time.time()),
    )


def failed_snapshot(
    *,
    alias: str,
    email: str | None,
    error: str,
    cache_path: Path | None = None,
) -> QuotaSnapshot:
    cached = load_cache(cache_path) if cache_path else None
    if cached:
        return QuotaSnapshot(
            alias=cached.alias,
            email=cached.email or email,
            plan=cached.plan,
            windows=cached.windows,
            updated_at=cached.updated_at,
            error=error,
        )
    return QuotaSnapshot(
        alias=alias,
        email=email,
        plan=None,
        windows=[],
        updated_at=0,
        error=error,
    )


def indicator_label(snapshot: QuotaSnapshot) -> str:
    if not snapshot.windows:
        return "Quota unavailable"
    return " · ".join(f"{window.key}{window.left_percent}%" for window in snapshot.windows)


def status_name(snapshot: QuotaSnapshot, now: int | None = None) -> str:
    if not snapshot.windows:
        return "unknown"
    if snapshot.error and _cache_is_expired(snapshot, now):
        return "stale"
    window = _status_window(snapshot.windows)
    if window.left_percent < 30:
        return "danger"
    if window.left_percent <= 70:
        return "warning"
    return "ok"


def progress_bar(percent: int, width: int = 10) -> str:
    filled = round(_clamp_percent(percent) / 100 * width)
    return "█" * filled + "░" * (width - filled)


def menu_window_line(window: QuotaWindow) -> str:
    reset = _format_reset(window.reset_at)
    reset_text = f" (resets {reset})" if reset else ""
    return f"{window.label}: {window.left_percent}% left{reset_text}"


def header_line(snapshot: QuotaSnapshot) -> str:
    plan = f" · {snapshot.plan.title()}" if snapshot.plan else ""
    return f"Codex Quota — {snapshot.alias}{plan}"


def account_line(snapshot: QuotaSnapshot) -> str:
    account = snapshot.email or "Unknown account"
    plan = f" ({snapshot.plan.title()})" if snapshot.plan else ""
    return f"{snapshot.alias}: {account}{plan}"


def account_summary_line(snapshot: QuotaSnapshot, *, current: bool = False) -> str:
    marker = "●" if current else " "
    return f"{marker} {snapshot.alias:<8} {indicator_label(snapshot)}"


def last_updated_line(
    snapshot: QuotaSnapshot,
    now: int | None = None,
    *,
    include_error: bool = False,
) -> str:
    if snapshot.updated_at <= 0 or (snapshot.error and not snapshot.windows):
        text = "never"
    else:
        text = datetime.fromtimestamp(snapshot.updated_at).astimezone().strftime("%H:%M:%S")
    if snapshot.error and include_error:
        return f"Last updated: {text} (stale: {snapshot.error})"
    return f"Last updated: {text}"


def save_cache(path: Path, snapshot: QuotaSnapshot) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = asdict(snapshot)
    payload["windows"] = [asdict(window) for window in snapshot.windows]
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")


def load_cache(path: Path | None) -> QuotaSnapshot | None:
    if path is None or not path.exists():
        return None
    try:
        payload = json.loads(path.read_text())
        windows = [
            QuotaWindow(
                key=str(item["key"]),
                label=str(item["label"]),
                left_percent=int(item["left_percent"]),
                reset_at=item.get("reset_at"),
            )
            for item in payload.get("windows", [])
            if isinstance(item, dict)
        ]
        return QuotaSnapshot(
            alias=str(payload.get("alias") or "Main"),
            email=payload.get("email") if isinstance(payload.get("email"), str) else None,
            plan=payload.get("plan") if isinstance(payload.get("plan"), str) else None,
            windows=windows,
            updated_at=int(payload.get("updated_at") or 0),
            error=payload.get("error") if isinstance(payload.get("error"), str) else None,
        )
    except Exception:
        return None


def _select_codex_snapshot(response: dict[str, Any]) -> dict[str, Any]:
    by_limit = response.get("rateLimitsByLimitId")
    if isinstance(by_limit, dict):
        codex = by_limit.get("codex")
        if isinstance(codex, dict):
            return codex
    fallback = response.get("rateLimits")
    return fallback if isinstance(fallback, dict) else {}


def _extract_windows(snapshot: dict[str, Any]) -> list[QuotaWindow]:
    windows: list[QuotaWindow] = []
    for field in ("primary", "secondary"):
        raw = snapshot.get(field)
        if not isinstance(raw, dict):
            continue
        used = raw.get("usedPercent")
        if not isinstance(used, int | float):
            continue
        key, label = _labels_for_duration(raw.get("windowDurationMins"))
        windows.append(
            QuotaWindow(
                key=key,
                label=label,
                left_percent=_clamp_percent(round(100 - used)),
                reset_at=raw.get("resetsAt") if isinstance(raw.get("resetsAt"), int) else None,
            )
        )
    if windows:
        return windows
    individual = snapshot.get("individualLimit")
    if isinstance(individual, dict):
        remaining = individual.get("remainingPercent")
        if isinstance(remaining, int | float):
            windows.append(
                QuotaWindow(
                    key="M",
                    label="M",
                    left_percent=_clamp_percent(round(remaining)),
                    reset_at=individual.get("resetsAt")
                    if isinstance(individual.get("resetsAt"), int)
                    else None,
                )
            )
    return windows


def _labels_for_duration(duration_mins: Any) -> tuple[str, str]:
    if duration_mins == 300:
        return "H", "5h"
    if duration_mins == 10080:
        return "W", "7d"
    if isinstance(duration_mins, int) and duration_mins >= 28 * 24 * 60:
        return "M", "M"
    if isinstance(duration_mins, int) and duration_mins > 0:
        hours = duration_mins // 60
        if hours and hours % 24 == 0:
            days = hours // 24
            return f"{days}d", f"{days}d"
        if hours:
            return f"{hours}h", f"{hours}h"
    return "Q", "Quota"


def _format_reset(
    timestamp: int | None,
    *,
    now: datetime | None = None,
) -> str | None:
    if not timestamp:
        return None
    dt = datetime.fromtimestamp(timestamp).astimezone()
    current = now or datetime.now().astimezone()
    if dt.date() == current.date():
        return dt.strftime("%H:%M")
    return dt.strftime("%-d %b")


def _cache_is_expired(snapshot: QuotaSnapshot, now: int | None = None) -> bool:
    current = now or int(time.time())
    if snapshot.updated_at <= 0:
        return True
    return current - snapshot.updated_at > CACHE_EXPIRES_AFTER_SECONDS


def _status_window(windows: list[QuotaWindow]) -> QuotaWindow:
    for window in windows:
        if window.key == "H":
            return window
    return windows[0]


def _clamp_percent(value: int) -> int:
    return max(0, min(100, value))
