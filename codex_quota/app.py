from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import os
import shutil
import tempfile
import threading
from dataclasses import dataclass
from pathlib import Path

from .accounts import AccountSlot, discover_account_slots
from .auth_info import read_account_info
from .client import CodexAppServerClient, CodexClientError
from .config import AppConfig
from .quota import QuotaSnapshot, failed_snapshot, load_cache, parse_rate_limits, save_cache


APP_SERVER_TIMEOUT_SECONDS = 8.0
MAX_FETCH_WORKERS = 4
_TEMP_HOME_LOCK = threading.Lock()
_ACTIVE_TEMP_HOMES: set[Path] = set()


@dataclass(frozen=True)
class QuotaState:
    current: QuotaSnapshot
    standby: list[QuotaSnapshot]


def fetch_snapshot(config: AppConfig) -> QuotaSnapshot:
    _prune_temporary_codex_homes(config.runtime_dir)
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
    _prune_temporary_codex_homes(config.runtime_dir)
    slots = discover_account_slots(config.accounts_dir)
    selected = _selected_slot(config, slots=slots)
    if selected is None:
        return QuotaState(current=fetch_snapshot(config), standby=[])
    ordered_slots = [selected]
    ordered_slots.extend(slot for slot in slots if slot.alias != selected.alias)
    snapshots = _fetch_slots_parallel(ordered_slots, config.runtime_dir)
    return QuotaState(current=snapshots[0], standby=snapshots[1:])


def load_cached_state(config: AppConfig) -> QuotaState:
    slots = discover_account_slots(config.accounts_dir)
    selected = _selected_slot(config, slots=slots)
    if selected is None:
        return QuotaState(
            current=failed_snapshot(
                alias="No account",
                email=None,
                error="no account selected",
                cache_path=None,
            ),
            standby=[],
        )
    current = _cached_slot_snapshot(selected)
    standby = [
        _cached_slot_snapshot(slot)
        for slot in slots
        if slot.alias != selected.alias
    ]
    return QuotaState(current=current, standby=standby)


def _fetch_slots_parallel(
    slots: list[AccountSlot],
    runtime_dir: Path,
) -> list[QuotaSnapshot]:
    if not slots:
        return []
    workers = min(len(slots), MAX_FETCH_WORKERS)
    with ThreadPoolExecutor(max_workers=workers) as executor:
        return list(
            executor.map(
                lambda slot: _fetch_slot_snapshot(slot, runtime_dir),
                slots,
            )
        )


def _fetch_slot_snapshot(slot: AccountSlot, runtime_dir: Path | None = None) -> QuotaSnapshot:
    return _fetch_account_snapshot(
        alias=slot.alias,
        auth_home=slot.path,
        cache_path=slot.path / "cache.json",
        runtime_dir=runtime_dir,
    )


def _cached_slot_snapshot(slot: AccountSlot) -> QuotaSnapshot:
    cached = load_cache(slot.path / "cache.json")
    if cached is not None:
        return cached
    account = read_account_info(slot.path)
    return failed_snapshot(
        alias=slot.alias,
        email=account.email,
        error="not refreshed yet",
        cache_path=None,
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
            response = CodexAppServerClient(
                codex_home=codex_home,
                timeout_seconds=APP_SERVER_TIMEOUT_SECONDS,
            ).read_rate_limits()
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
        self.home: Path | None = None

    def __enter__(self) -> Path:
        tmp_parent = None
        if self.runtime_dir is not None:
            tmp_parent = self.runtime_dir / "tmp" / "app-server"
            tmp_parent.mkdir(parents=True, exist_ok=True)
        home = Path(tempfile.mkdtemp(prefix="codex-home-", dir=tmp_parent))
        with _TEMP_HOME_LOCK:
            _ACTIVE_TEMP_HOMES.add(home)
        self.home = home
        source_auth = self.auth_home / "auth.json"
        target_auth = home / "auth.json"
        shutil.copy2(source_auth, target_auth)
        os.chmod(target_auth, 0o600)
        return home

    def __exit__(self, exc_type, exc, tb) -> None:
        if self.home is None:
            return
        try:
            shutil.rmtree(self.home, ignore_errors=True)
        finally:
            with _TEMP_HOME_LOCK:
                _ACTIVE_TEMP_HOMES.discard(self.home)
            if self.runtime_dir is not None:
                _prune_temporary_codex_homes(self.runtime_dir)


def _prune_temporary_codex_homes(runtime_dir: Path | None) -> None:
    if runtime_dir is None:
        return
    root = runtime_dir / "tmp" / "app-server"
    if not root.exists():
        return
    with _TEMP_HOME_LOCK:
        active = set(_ACTIVE_TEMP_HOMES)
    for path in root.glob("codex-home-*"):
        if path in active:
            continue
        shutil.rmtree(path, ignore_errors=True)
