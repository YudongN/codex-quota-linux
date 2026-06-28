from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .accounts import AccountSlot, discover_account_slots
from .auth_info import read_account_info
from .client import CodexAppServerClient, CodexClientError
from .config import AppConfig
from .quota import QuotaSnapshot, failed_snapshot, parse_rate_limits, save_cache


@dataclass(frozen=True)
class QuotaState:
    current: QuotaSnapshot
    standby: list[QuotaSnapshot]


def fetch_snapshot(config: AppConfig) -> QuotaSnapshot:
    return _fetch_account_snapshot(
        alias=config.current_alias,
        codex_home=None,
        cache_path=config.runtime_dir / "cache.json",
    )


def fetch_state(config: AppConfig) -> QuotaState:
    current = fetch_snapshot(config)
    standby = [
        _fetch_slot_snapshot(slot)
        for slot in discover_account_slots(config.accounts_dir)
        if slot.alias != config.current_alias
    ]
    return QuotaState(current=current, standby=standby)


def _fetch_slot_snapshot(slot: AccountSlot) -> QuotaSnapshot:
    return _fetch_account_snapshot(
        alias=slot.alias,
        codex_home=slot.codex_home,
        cache_path=slot.codex_home / "cache.json",
    )


def _fetch_account_snapshot(
    *,
    alias: str,
    codex_home: Path | None,
    cache_path: Path,
) -> QuotaSnapshot:
    account = read_account_info(codex_home)
    try:
        response = CodexAppServerClient(codex_home=codex_home).read_rate_limits()
        snapshot = parse_rate_limits(
            response,
            alias=alias,
            email=account.email,
        )
        save_cache(cache_path, snapshot)
        return snapshot
    except CodexClientError as exc:
        return failed_snapshot(
            alias=alias,
            email=account.email,
            error=str(exc),
            cache_path=cache_path,
        )
