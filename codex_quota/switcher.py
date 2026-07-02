from __future__ import annotations

import fcntl
from dataclasses import dataclass
from pathlib import Path

from .accounts import account_slot_path
from .auth_sync import sync_refreshed_auth, write_auth_bytes
from .config import AppConfig, save_config


class SwitchError(RuntimeError):
    pass


@dataclass(frozen=True)
class SwitchResult:
    alias: str
    auth_path: Path


def switch_account(
    config: AppConfig,
    alias: str,
    *,
    codex_home: Path | None = None,
) -> SwitchResult:
    slot_home = account_slot_path(config.accounts_dir, alias)
    selected_alias = slot_home.name
    slot_auth = slot_home / "auth.json"
    if not slot_auth.is_file():
        raise SwitchError(f"account slot '{selected_alias}' does not have auth.json")

    target_home = codex_home or Path.home() / ".codex"
    target_auth = target_home / "auth.json"
    target_home.mkdir(parents=True, exist_ok=True)
    config.runtime_dir.mkdir(parents=True, exist_ok=True)

    lock_path = config.runtime_dir / "app.lock"
    with lock_path.open("w") as lock_file:
        fcntl.flock(lock_file, fcntl.LOCK_EX)
        _sync_selected_slot_from_codex_home(config, target_auth)
        _replace_auth(source=slot_auth, target=target_auth)
        save_config(config, selected_alias=selected_alias)
        return SwitchResult(
            alias=selected_alias,
            auth_path=target_auth,
        )


def _sync_selected_slot_from_codex_home(config: AppConfig, source_auth: Path) -> bool:
    if not config.selected_alias:
        return False
    try:
        selected_home = account_slot_path(config.accounts_dir, config.selected_alias)
    except ValueError:
        return False
    selected_auth = selected_home / "auth.json"
    if not source_auth.is_file() or not selected_auth.is_file():
        return False
    return sync_refreshed_auth(source=source_auth, target=selected_auth)


def _replace_auth(*, source: Path, target: Path) -> None:
    write_auth_bytes(target, source.read_bytes())
