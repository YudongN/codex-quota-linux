from __future__ import annotations

import os
import shutil
import tempfile
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
    slot = _selected_slot(config)
    if slot is None:
        return failed_snapshot(
            alias="No account",
            email=None,
            error="no account selected",
            cache_path=None,
        )
    return _fetch_slot_snapshot(slot, config.runtime_dir)


def fetch_state(config: AppConfig) -> QuotaState:
    slots = discover_account_slots(config.accounts_dir)
    selected = _selected_slot(config, slots=slots)
    if selected is None:
        return QuotaState(current=fetch_snapshot(config), standby=[])
    current = _fetch_slot_snapshot(selected, config.runtime_dir)
    standby = [
        _fetch_slot_snapshot(slot, config.runtime_dir)
        for slot in slots
        if slot.alias != selected.alias
    ]
    return QuotaState(current=current, standby=standby)


def _fetch_slot_snapshot(slot: AccountSlot, runtime_dir: Path | None = None) -> QuotaSnapshot:
    return _fetch_account_snapshot(
        alias=slot.alias,
        auth_home=slot.codex_home,
        cache_path=slot.codex_home / "cache.json",
        runtime_dir=runtime_dir,
    )


def _fetch_account_snapshot(
    *,
    alias: str,
    auth_home: Path,
    cache_path: Path,
    runtime_dir: Path | None,
) -> QuotaSnapshot:
    account = read_account_info(auth_home)
    try:
        with _temporary_codex_home(auth_home, runtime_dir) as codex_home:
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


def _selected_slot(
    config: AppConfig,
    *,
    slots: list[AccountSlot] | None = None,
) -> AccountSlot | None:
    slots = slots if slots is not None else discover_account_slots(config.accounts_dir)
    if not slots:
        return None
    for slot in slots:
        if slot.alias == config.selected_alias:
            return slot
    return slots[0]


class _temporary_codex_home:
    def __init__(self, auth_home: Path, runtime_dir: Path | None):
        self.auth_home = auth_home
        self.runtime_dir = runtime_dir
        self.temp_dir: tempfile.TemporaryDirectory[str] | None = None

    def __enter__(self) -> Path:
        tmp_parent = None
        if self.runtime_dir is not None:
            tmp_parent = self.runtime_dir / "tmp" / "app-server"
            tmp_parent.mkdir(parents=True, exist_ok=True)
        self.temp_dir = tempfile.TemporaryDirectory(
            prefix="codex-home-",
            dir=tmp_parent,
        )
        home = Path(self.temp_dir.name)
        source_auth = self.auth_home / "auth.json"
        target_auth = home / "auth.json"
        shutil.copy2(source_auth, target_auth)
        os.chmod(target_auth, 0o600)
        return home

    def __exit__(self, exc_type, exc, tb) -> None:
        if self.temp_dir is not None:
            self.temp_dir.cleanup()
